#!/usr/bin/env python3
"""scripts/replay.py — Phase 1 of docs/imu-interaction-plan.md.

Feed a raw-sensor recording (make imu-record) through the REAL firmware tap
and tilt code, on the Mac, at a simulated loop rate — and score what it
decided against what the human labelled.

    make replay                              # every session marked use:true
    make replay LOOP_HZ=57,139,240           # sweep loop rates
    python scripts/replay.py data/imu-....jsonl --loop-hz 57 --json out.json

WHAT IS REAL AND WHAT IS SIMULATED
Real, imported unchanged from micropython/: the tilt controller
(tilt.TiltController), the trigger's magnitude and median
(gestures._gesture_magnitude_mg / _gesture_median), the capture-window
features (gestures.extract_gesture_features) and the verdict
(gestures.classify_valid_input). Simulated here, because they live inline in
main.py's loop: the trigger buffer and threshold test, the ~1.2 s capture,
and the loop's blindness after an accepted tap (BLIND_MS, the response
animation). Taken from the recording: the samples, at the sensor's ~234 Hz.

The production loop reads ONE sample per iteration, so at LOOP_HZ it sees
only every (234 / LOOP_HZ)-th sample. The capture window is read at full rate
in the firmware (its own ~4 ms loop), and is here too.

Simplifications, stated so they are not mistaken for findings: the unit is
always awake and never in quiet hours; the boot-ignore window is skipped;
knobs not recorded in data/knobs-<unit>.json come from config.example.py.

SCORING
Labels are pressed AFTER the action, so a point label claims an event in
[label - PRE_MS, label + POST_MS]. A tap label (tap_top/body/base) is a HIT if
an accepted tap falls in its window, a MISS otherwise. Every other point label
(knocks, bumps, lift, set_down, grab, release) is a FALSE TAP if an accepted
tap falls in its window. Accepted taps near no label are UNEXPLAINED. For
states, the score is how long the tilt controller was ENGAGED inside each
segment: in rest_flat / rest_lean it should be zero (engaged there is the
stuck tilt); in tilting it should be most of the time.
"""

import argparse
import importlib
import json
import math
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from host_fakes import install_device_fakes  # noqa: E402
from imu_record import apply_corrections, effective, segments  # noqa: E402

# Measured on the 2026-10-04 recordings: labels land a median ~330 ms after
# the trigger they describe (p10 ~20-240 ms), and are pressed ~1.3 s apart.
# A window wider than the spacing lets neighbouring labels steal each other's
# events, so it is kept tight.
PRE_MS = 1000
POST_MS = 200
BLIND_MS = 1500
TAP_LABELS = ("tap_top", "tap_body", "tap_base")
NOT_A_TAP = ("knock_table", "knock_object", "knock_shelf", "bump_other",
             "lift", "set_down", "grab", "release")
# Gyro sensitivity by CTRL6 FS_G code, mdps/LSB. Code 3 verified on bottle-01
# against the gravity vector (33-35 measured, docs/imu-interaction-plan.md).
GYRO_MDPS = {0: 4.375, 1: 8.75, 2: 17.5, 3: 35.0, 4: 70.0}


# ── firmware on the host ──────────────────────────────────────────────────
def load_firmware(knobs=None):
    """Import the real gestures + tilt modules against config.example.py
    overlaid with `knobs`. Returns a namespace with the two modules."""
    install_device_fakes()
    cfg = types.ModuleType("config")
    exec(compile((REPO / "micropython" / "config.example.py").read_text(),
                 "config.example.py", "exec"), cfg.__dict__)
    cfg.TIME_SOURCE = "ds3231"
    for k, v in (knobs or {}).items():
        setattr(cfg, k, v)
    for name in list(sys.modules):
        if name in ("config", "settings", "gestures", "tilt", "leds", "motion",
                    "primitives", "palette", "contracts", "signals", "status",
                    "schedule", "clock", "diag", "horizon", "interlog"):
            sys.modules.pop(name, None)
    sys.modules["config"] = cfg
    mp = str(REPO / "micropython")
    if mp not in sys.path:
        sys.path.insert(0, mp)
    ns = types.SimpleNamespace()
    ns.settings = importlib.import_module("settings")
    ns.gestures = importlib.import_module("gestures")
    ns.tilt = importlib.import_module("tilt")
    return ns


# ── recordings ────────────────────────────────────────────────────────────
class Sample:
    __slots__ = ("t", "ax", "ay", "az", "gx", "gy", "gz")

    def __init__(self, t, ax, ay, az, gx, gy, gz):
        self.t, self.ax, self.ay, self.az = t, ax, ay, az
        self.gx, self.gy, self.gz = gx, gy, gz


def load_recording(path, entry=None):
    """-> (header, samples sorted by device ms, labels with device ms 'tm')."""
    recs = [json.loads(line) for line in open(path)]
    header = recs[0]
    meta = next((r for r in recs if r.get("k") == "m"), {})
    batches = [r for r in recs if r.get("k") == "b"]
    samples = []
    for b in batches:
        for row in b["d"]:
            dt, gx, gy, gz, ax, ay, az = row[:7]
            samples.append(Sample((b["t0"] + dt) / 1000.0, ax, ay, az, gx, gy, gz))
    samples.sort(key=lambda s: s.t)
    # host time -> device ms: the earliest-arriving batch sets the latency
    # floor; everything else arrived later than that, never earlier.
    off = min(b["h"] - (b["t0"] + b["d"][-1][0]) / 1e6 for b in batches) if batches else 0.0
    labels = effective(apply_corrections(recs, entry))
    for r in labels:
        r["tm"] = (r["h"] - off) * 1000.0
    end_h = recs[-1].get("h", header.get("h", 0))
    segs = [(name, (a - off) * 1000.0, (b - off) * 1000.0)
            for name, a, b in segments(labels, end_h)]
    header = dict(header, gyro_mdps=GYRO_MDPS.get(meta.get("CTRL6"), None))
    return header, samples, labels, segs


# ── the replay ────────────────────────────────────────────────────────────
def capture_features(fw, samples, i0, t0, window_ms, gyro_mdps):
    """The capture window, as the firmware would see it, plus candidate
    features the firmware does not use yet (for analysis only):

      gyro_late_dps  mean rotation rate over the window from 400 ms on, with
                     the gyro's bias (median of the 0.5 s before the trigger)
                     removed — without that, the zero-rate offset and noise
                     floor read as ~0.3+ dps of "rotation" on a still bottle
      z_share        fraction of the first 150 ms of accel impulse energy on
                     the z axis (the ambient-knock lead)
    """
    cap, j = [], i0
    while j < len(samples) and samples[j].t - t0 <= window_ms:
        s = samples[j]
        cap.append((int(s.t - t0), s.ax, s.ay, s.az))
        j += 1
    feats = fw.gestures.extract_gesture_features(cap) if len(cap) >= 2 else {"energy": 0}
    pre = [samples[k] for k in range(max(0, i0 - 200), i0) if t0 - 600 <= samples[k].t <= t0 - 100]
    late = [samples[k] for k in range(i0, j) if samples[k].t - t0 >= 400]
    mid = [samples[k] for k in range(i0, j) if 150 <= samples[k].t - t0 < 400]
    if gyro_mdps and (late or mid):
        if pre:
            bx = _median([p.gx for p in pre])
            by = _median([p.gy for p in pre])
            bz = _median([p.gz for p in pre])
        else:
            bx = by = bz = 0

        def rot(ss):
            return sum(math.sqrt((s.gx - bx) ** 2 + (s.gy - by) ** 2 + (s.gz - bz) ** 2)
                       for s in ss) / len(ss) * gyro_mdps / 1000.0
        if late:
            feats["gyro_late_dps"] = rot(late)
        # 150-400 ms: after the impact's own ring-down, before the next thing
        # a person does. The classifier memo (docs/classifier-approach.md)
        # found this window, not the late one, is what a tree picks — the
        # late window also catches the NEXT event when events are ~1.3 s apart.
        if mid:
            feats["gyro_mid_dps"] = rot(mid)
    if pre:
        base = [_median([p.ax for p in pre]), _median([p.ay for p in pre]), _median([p.az for p in pre])]
        e = [0.0, 0.0, 0.0]
        for k in range(i0, j):
            s = samples[k]
            if s.t - t0 > 150:
                break
            e[0] += (s.ax - base[0]) ** 2
            e[1] += (s.ay - base[1]) ** 2
            e[2] += (s.az - base[2]) ** 2
        tot = sum(e)
        feats["z_share"] = e[2] / tot if tot else 0.0
    return feats, j


def _median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def replay(fw, samples, loop_hz=57.0, blind_ms=BLIND_MS, gyro_mdps=None,
           candidates=None, ideal=False):
    """Run the stream through the firmware. `ideal=True` removes the loop's
    blindness (the 1.2 s capture and the response) so every impulse is judged
    on its own — the CLASSIFIER's score, separate from the loop's. Returns a
    list of event dicts:
       {"e": "tap", "t", "dev", "feats", "valid", "cand": {name: bool}}
       {"e": "tilt", "t", "state", "engaged"}  — on change only
    """
    g = fw.gestures
    st = fw.settings
    window_ms = g._GESTURE_WINDOW_MS
    buf_len = g._GESTURE_TRIGGER_BUFFER_LEN
    threshold = st.TAP_TRIGGER_THRESHOLD_MG
    ctl = fw.tilt.TiltController() if st.TILT_ENABLED else None
    period = 1000.0 / loop_hz
    events, trig = [], []
    next_t = samples[0].t if samples else 0
    blind_until = -1e18
    last_tilt_t = None
    tilt_key = None
    i = 0
    while i < len(samples):
        s = samples[i]
        if s.t < next_t or s.t < blind_until:
            i += 1
            continue
        # Keep the IDEAL schedule, not "one period after the sample we got":
        # the latter rounds every period up to a whole number of sensor
        # samples (57 Hz became 47 Hz at a 234 Hz stream).
        while next_t <= s.t:
            next_t += period
        raw = (s.ax, s.ay, s.az)
        if ctl is not None:
            dt = 0 if last_tilt_t is None else int(s.t - last_tilt_t)
            state = ctl.update(raw, int(s.t), dt)
            last_tilt_t = s.t
            key = (state if state in ("up", "down", "released") else "idle", ctl.engaged)
            if key != tilt_key:
                tilt_key = key
                events.append({"e": "tilt", "t": s.t, "state": key[0], "engaged": ctl.engaged})
        mag = g._gesture_magnitude_mg((s.t,) + raw)
        baseline = g._gesture_median(trig) if len(trig) >= buf_len else None
        trig.append(mag)
        if len(trig) > buf_len:
            trig.pop(0)
        if baseline is not None and abs(mag - baseline) >= threshold:
            feats, j = capture_features(fw, samples, i, s.t, window_ms, gyro_mdps)
            valid = bool(g.classify_valid_input(feats))
            cand = {name: bool(fn(feats)) for name, fn in (candidates or {}).items()}
            blind_until = s.t + (300 if ideal else window_ms + (blind_ms if valid else 0))
            events.append({"e": "tap", "t": s.t, "dev": abs(mag - baseline),
                           "feats": feats, "valid": valid, "cand": cand,
                           "blind_until": blind_until})
            trig = []
            i = i + 1 if ideal else j
            continue
        i += 1
    return events


# ── scoring ───────────────────────────────────────────────────────────────
def score(events, labels, segs, accept=lambda ev: ev["valid"]):
    """One accepted tap answers at most ONE label. Windows overlap when labels
    are seconds apart, so without one-to-one matching a single tap was being
    credited to two labels. Pairs are matched nearest-first."""
    taps = [ev for ev in events if ev["e"] == "tap" and accept(ev)]
    points = [r for r in labels if "label" in r]
    out = {"hit": 0, "miss": 0, "false": {}, "true_n": 0, "unexplained": 0,
           "per_label": {}, "miss_why": {}}
    pairs = sorted(
        (abs(ev["t"] - r["tm"]), li, ti)
        for li, r in enumerate(points)
        for ti, ev in enumerate(taps)
        if r["tm"] - PRE_MS <= ev["t"] <= r["tm"] + POST_MS)
    match, used = {}, set()
    for _, li, ti in pairs:
        if li not in match and ti not in used:
            match[li] = ti
            used.add(ti)
    explained = set(used)
    for li, r in enumerate(points):
        lab = r["label"]
        got = li in match
        pl = out["per_label"].setdefault(lab, [0, 0])     # [with an accepted tap, total]
        pl[1] += 1
        if got:
            pl[0] += 1
        if lab in TAP_LABELS:
            out["true_n"] += 1
            out["hit" if got else "miss"] += 1
            if not got:
                why = _miss_reason(events, r["tm"])
                out["miss_why"][why] = out["miss_why"].get(why, 0) + 1
        elif lab in NOT_A_TAP and got:
            out["false"][lab] = out["false"].get(lab, 0) + 1
    # a tap inside some label's window but matched to none is still "near a
    # label" — the extra one of a pair — and counted as unexplained
    out["unexplained"] = len(taps) - len(explained)
    # tilt engaged time per segment
    engaged_spans, on = [], None
    for ev in events:
        if ev["e"] != "tilt":
            continue
        if ev["engaged"] and on is None:
            on = ev["t"]
        elif not ev["engaged"] and on is not None:
            engaged_spans.append((on, ev["t"]))
            on = None
    if on is not None:
        engaged_spans.append((on, float("inf")))
    seg_out = []
    for name, a, b in segs:
        eng = sum(max(0.0, min(b, y) - max(a, x)) for x, y in engaged_spans)
        seg_out.append({"state": name, "s": (b - a) / 1000.0, "engaged_s": eng / 1000.0})
    out["segments"] = seg_out
    in_state = {}
    for k, ev in enumerate(taps):
        if k in explained:
            continue
        for name, a, b in segs:
            if a <= ev["t"] <= b:
                in_state[name] = in_state.get(name, 0) + 1
                break
    out["taps_in_states"] = in_state
    return out


def _miss_reason(events, tm):
    """Why did a labelled tap get no accepted tap? In priority order:
    'blind'     the loop was still busy with an earlier accepted tap
                (capture + response) — a test-protocol artefact as much as a
                firmware failure when taps are 2-3 s apart
    'rejected'  it triggered, and the classifier said no
    'untriggered' the trigger never fired (below threshold, or between the
                samples the loop happened to read)"""
    for ev in events:
        if ev["e"] != "tap":
            continue
        # The tap was made shortly before its label; if the loop was still
        # busy with an earlier accepted tap at any point in that lead-in, it
        # could not have seen it.
        if ev["valid"] and ev["t"] < tm - PRE_MS and ev["blind_until"] > tm - PRE_MS:
            return "blind"
    for ev in events:
        if ev["e"] == "tap" and not ev["valid"] and tm - PRE_MS <= ev["t"] <= tm + POST_MS:
            return "rejected"
    return "untriggered"


def candidate_rules(gyro_late_max_dps=1.5, z_share_max=0.5):
    """Rules to compare against the shipped classifier — analysis only, not
    firmware. Thresholds are first guesses from the 2026-10-04 feature
    distributions (see the report's feature table), not tuned.

      gyro_veto  still rotating after the impact -> handling, not a tap
      z_veto     impulse mostly vertical -> came through the surface (a knock)
      both       either veto
    """
    def gyro_ok(f):
        return f.get("gyro_late_dps", 0.0) < gyro_late_max_dps

    def z_ok(f):
        return f.get("z_share", 0.0) < z_share_max

    def gyro_mid_ok(f):
        return f.get("gyro_mid_dps", 0.0) < 1.15        # docs/classifier-approach.md

    return {"gyro_veto": gyro_ok, "gyro_mid": gyro_mid_ok, "z_veto": z_ok,
            "both": lambda f: gyro_ok(f) and z_ok(f)}


# ── CLI ───────────────────────────────────────────────────────────────────
def nearest_label(labels, t):
    """The point label whose window claims time t, if any."""
    best = None
    for r in labels:
        if "label" in r and r["tm"] - PRE_MS <= t <= r["tm"] + POST_MS:
            if best is None or abs(r["tm"] - t) < abs(best["tm"] - t):
                best = r
    return best["label"] if best else ""


def write_csv(path, results):
    import csv
    cols = ["file", "loop_hz", "t_s", "label", "valid", "dev", "energy",
            "gyro_late_dps", "z_share", "peak_dev", "duration_ms"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for res in results:
            for ev in res["events"]:
                if ev["e"] != "tap":
                    continue
                ft = ev["feats"]
                w.writerow([res["file"], res["loop_hz"], round(ev["t"] / 1000, 3),
                            nearest_label(res["labels"], ev["t"]), int(ev["valid"]),
                            round(ev["dev"], 1), round(ft.get("energy", 0)),
                            round(ft.get("gyro_late_dps", 0), 3), round(ft.get("z_share", 0), 3),
                            round(ft.get("peak_dev", 0), 1), ft.get("duration_ms", "")])


def _fmt_report(name, loop_hz, sc, cand_scores):
    lines = [f"\n== {name}   loop {loop_hz:g} Hz"]
    if sc["true_n"]:
        why = ", ".join(f"{k} {v}" for k, v in sorted(sc["miss_why"].items()))
        blind = sc["miss_why"].get("blind", 0)
        scorable = sc["true_n"] - blind
        lines.append(f"   taps: {sc['hit']}/{sc['true_n']} hit, {sc['miss']} missed"
                     + (f"  ({why})" if why else "")
                     + (f"  → {sc['hit']}/{scorable} of taps the loop could see" if blind else ""))
    if sc["false"] or any(k in sc["per_label"] for k in NOT_A_TAP):
        tot = sum(sc["per_label"].get(k, [0, 0])[1] for k in NOT_A_TAP)
        lines.append(f"   false taps: {sum(sc['false'].values())}/{tot}  "
                     + "  ".join(f"{k} {sc['per_label'][k][0]}/{sc['per_label'][k][1]}"
                                 for k in NOT_A_TAP if k in sc["per_label"]))
    lines.append(f"   unexplained accepted taps: {sc['unexplained']}"
                 + (f"  (inside states: {sc['taps_in_states']})" if sc.get("taps_in_states") else ""))
    for cname, cs in cand_scores.items():
        lines.append(f"   [{cname}] taps {cs['hit']}/{cs['true_n']}, false "
                     f"{sum(cs['false'].values())}, unexplained {cs['unexplained']}")
    by = {}
    for s in sc["segments"]:
        b = by.setdefault(s["state"], [0, 0.0, 0.0, 0])
        b[0] += 1
        b[1] += s["s"]
        b[2] += s["engaged_s"]
        b[3] += 1 if s["engaged_s"] > 0.5 else 0
    for st, (n, tot, eng, k) in by.items():
        lines.append(f"   tilt in {st:<9}: engaged {eng:5.1f}/{tot:5.1f} s "
                     f"({k}/{n} segments engaged >0.5 s)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--loop-hz", default="57", help="comma list, e.g. 57,139,240")
    ap.add_argument("--blind-ms", type=int, default=BLIND_MS)
    ap.add_argument("--ideal", action="store_true",
                    help="no loop blindness: score the classifier, not the loop")
    ap.add_argument("--unit", default="bottle-01")
    ap.add_argument("--knob", action="append", default=[], help="NAME=VALUE override")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--csv", type=Path, help="one row per trigger: features + nearest label")
    args = ap.parse_args()

    sessions_path = REPO / "data" / "imu-sessions.json"
    sessions = json.loads(sessions_path.read_text()) if sessions_path.exists() else {}
    files = args.files or [REPO / "data" / f for f, e in sessions.items()
                           if isinstance(e, dict) and e.get("use") is True]
    knobs_path = REPO / "data" / f"knobs-{args.unit}.json"
    knobs = json.loads(knobs_path.read_text())["knobs"] if knobs_path.exists() else {}
    for kv in args.knob:
        k, v = kv.split("=", 1)
        knobs[k] = json.loads(v)
    fw = load_firmware(knobs)
    print(f"knobs: {knobs_path.name if knobs_path.exists() else 'config.example only'}"
          f"  trigger {fw.settings.TAP_TRIGGER_THRESHOLD_MG} mg, "
          f"energy < {fw.settings.TAP_ENERGY_THRESHOLD}, deadzone {fw.settings.TILT_DEADZONE_DEG} deg")

    results = []
    for hz in [float(x) for x in args.loop_hz.split(",")]:
        for path in files:
            entry = sessions.get(path.name)
            header, samples, labels, segs = load_recording(path, entry)
            fw = load_firmware(knobs)            # fresh tilt state per file
            cands = candidate_rules()
            events = replay(fw, samples, hz, args.blind_ms, header.get("gyro_mdps"), cands,
                            ideal=args.ideal)
            sc = score(events, labels, segs)
            cs = {n: score(events, labels, segs, accept=lambda ev, n=n: ev["valid"] and ev["cand"][n])
                  for n in cands}
            print(_fmt_report(f"{path.name}  ({header.get('note', '')})", hz, sc, cs))
            results.append({"file": path.name, "loop_hz": hz, "score": sc, "candidates": cs,
                            "events": events, "labels": labels})
    if args.csv:
        write_csv(args.csv, results)
        print(f"\nfeatures per trigger → {args.csv}")
    if args.json:
        args.json.write_text(json.dumps(results, default=str))
        print(f"\nevents + scores → {args.json}")


if __name__ == "__main__":
    main()
