#!/usr/bin/env python3
"""scripts/sim.py — the IMU pipeline on the Mac: detect → arbiter → classify.

    make sim                                   # every use:true session, what ships
    make sim DETECT=magnitude,vector LOOP_HZ=240,145
    make sim-live                              # follow the recording being made now

THE FRAME (docs/imu-interaction-plan.md, "Between Phase 1 and 2"):

    samples ─► LOOP ─► DETECT ─► ARBITER ─► CLASSIFY ─► verdict
               which   "should I   "when do    "what was
               samples  look?"      I decide?"  it?"
               the loop                 ▲
               sees                     └─ tilt controller (parallel)

Every block is swappable, and what ships fills every slot by default:

  DETECT    magnitude  |a| − median(|a|) ≥ 50 mg — the firmware's own
                       functions (gestures._gesture_magnitude_mg/_median)
            vector     ‖a − median(a)‖ ≥ 50 mg, per axis — the SAME buffer
                       and threshold, so the one thing changed is geometry
                       (a sideways tap turns the vector; it barely lengthens it)
  ARBITER   capture    today's: capture a fixed window, decide once, then go
                       blind (window + the response, after an accepted tap)
  CLASSIFY  firmware   gestures.reject_reason — energy · vertical · gyro
            accept     everything detect hands over is a tap (scores detect alone)

This is replay.py with the blocks pulled apart, not a second firmware:
the features, the gyro baseline and the verdict are imported from
micropython/ as replay.py imports them, and with the shipped blocks the
events it produces are replay.replay()'s, sample for sample
(tests/test_sim.py). The arbiter to come is written as a firmware module and
plugged in here — one implementation, never a parallel copy.

STREAMING. The pipeline takes one sample at a time (feed()), never looking
ahead, so the same code runs over a finished recording and over one being
written (--follow): the capture decides when a sample past its window
arrives, as the firmware would.

SCORING. Guided recordings (PROTOCOL=..., scripts/imu_protocol.py) score per
trial: taps accepted in T; any accepted tap in G/H (a false tap); in D, the
tap and anything accepted ≥1.5 s after it; and accepted taps in no attempt's
window (the hands-off countdowns). Hand-labelled recordings score with
replay.score(). Both also count detect's TRIGGERS, because detect is judged
on recall (did every tap trigger?) and on what wakes it in rest_flat — the
noise floor — not on verdicts.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import imu_protocol  # noqa: E402
import replay  # noqa: E402

D_FOLLOW_MS = 1500      # in a D trial, accepted taps this long after the first trigger are false


# ── LOOP: which samples the production loop gets to see ──────────────────
class Loop:
    """The production loop reads one sample per turn, so at `hz` it sees
    only some of them. Same schedule as replay.replay: keep the IDEAL
    schedule, don't round each period up to whole sensor samples."""

    def __init__(self, hz):
        self.period = 1000.0 / hz
        self.next_t = None

    def sees(self, t):
        if self.next_t is None:
            self.next_t = t
        if t < self.next_t:
            return False
        while self.next_t <= t:
            self.next_t += self.period
        return True


# ── DETECT ───────────────────────────────────────────────────────────────
class MagnitudeTrigger:
    """What ships: the change in |a| against the median of the last few
    samples the loop saw. Built from the firmware's own functions."""
    name = "magnitude"

    def __init__(self, fw):
        self.g = fw.gestures
        self.thr = fw.settings.TAP_TRIGGER_THRESHOLD_MG
        self.n = self.g._GESTURE_TRIGGER_BUFFER_LEN
        self.buf = []

    def update(self, s):
        """-> the deviation in mg if this sample fires, else None."""
        mag = self.g._gesture_magnitude_mg((s.t, s.ax, s.ay, s.az))
        base = self.g._gesture_median(self.buf) if len(self.buf) >= self.n else None
        self.buf.append(mag)
        if len(self.buf) > self.n:
            self.buf.pop(0)
        if base is not None and abs(mag - base) >= self.thr:
            return abs(mag - base)
        return None

    def reset(self):
        self.buf = []


class VectorTrigger(MagnitudeTrigger):
    """The distance between a and the per-axis median of the same buffer:
    a sideways push counts in full. Slow tilts move the median with them, so
    they don't fire; the buffer is ~33 ms at 240 Hz."""
    name = "vector"

    def update(self, s):
        v = (s.ax, s.ay, s.az)
        base = None
        if len(self.buf) >= self.n:
            base = [self.g._gesture_median([b[k] for b in self.buf]) for k in range(3)]
        self.buf.append(v)
        if len(self.buf) > self.n:
            self.buf.pop(0)
        if base is None:
            return None
        # The firmware's own scale (±2 g, 0.061 mg/LSB, _gesture_magnitude_mg),
        # so the two triggers' 50 mg mean the same thing.
        dev = sum((v[k] - base[k]) ** 2 for k in range(3)) ** 0.5 * 0.061
        return dev if dev >= self.thr else None


DETECT = {"magnitude": MagnitudeTrigger, "vector": VectorTrigger}


# ── CLASSIFY ───────────────────────────────────────────────────────────────
class FirmwareClassifier:
    name = "firmware"

    def __init__(self, fw):
        self.g = fw.gestures

    def judge(self, feats):
        """-> (is it a tap, why not)."""
        why = self.g.reject_reason(feats)
        return why is None, why


class AcceptClassifier:
    name = "accept"

    def __init__(self, fw):
        pass

    def judge(self, feats):
        return True, None


CLASSIFY = {"firmware": FirmwareClassifier, "accept": AcceptClassifier}


# ── ARBITER ───────────────────────────────────────────────────────────────
class CaptureArbiter:
    """What ships, which is barely an arbiter: on a trigger, capture a fixed
    window, judge it once, and stay blind until the window (plus the response
    animation, if it was a tap) is over. No provisional state, no veto, no
    view of the tilt controller. `ideal` removes the blindness so every
    impulse is judged on its own (replay --ideal)."""
    name = "capture"

    def __init__(self, fw, classify, gyro_mdps=None, blind_ms=replay.BLIND_MS, ideal=False):
        self.fw, self.classify = fw, classify
        self.window = fw.gestures._GESTURE_WINDOW_MS
        self.blind_ms, self.ideal, self.gyro_mdps = blind_ms, ideal, gyro_mdps
        self.pending = []           # [(t0, i0, dev, gyro baseline)] captures still filling
        self.busy_until = -1e18

    def open(self, t):
        """Is detect listening at t?"""
        return t >= self.busy_until

    def trigger(self, t, i, dev, bias=None):
        # The gyro baseline as it stands NOW. The firmware's capture runs in
        # its own inner loop, so the baseline doesn't learn during the window;
        # with overlapping captures (ideal) it would here, unless frozen.
        # (A copy: estimate() hands back GyroBias's own list, which update()
        # changes in place — holding the reference would freeze nothing.)
        est = bias.estimate() if bias is not None else None
        frozen = _Frozen(list(est) if est is not None else None) if bias is not None else None
        self.pending.append((t, i, dev, frozen))
        self.busy_until = t + (300 if self.ideal else self.window)

    def sample(self, samples, i, bias, end=False):
        """Called with every sample; returns the verdicts that completed.
        `end`: the stream is over — judge what is still capturing on the
        samples it has (as replay.replay does at the end of a recording)."""
        out = []
        t = samples[i].t
        while self.pending and (end or t - self.pending[0][0] > self.window):
            t0, i0, dev, frozen = self.pending.pop(0)
            feats, _ = replay.capture_features(self.fw, samples, i0, t0, self.window,
                                               self.gyro_mdps, frozen)
            ok, why = self.classify.judge(feats)
            if ok and not self.ideal:
                self.busy_until = t0 + self.window + self.blind_ms
            out.append({"e": "tap", "t": t0, "dev": dev, "feats": feats, "valid": ok,
                        "why": why, "blind_until": self.busy_until})
        return out


class _Frozen:
    """A GyroBias stand-in that answers with one estimate."""
    def __init__(self, est):
        self._est = est

    def estimate(self):
        return self._est


ARBITERS = {"capture": CaptureArbiter}


# ── the pipeline ──────────────────────────────────────────────────────────
class Pipeline:
    def __init__(self, fw, loop_hz=240.0, detect="magnitude", arbiter="capture",
                 classify="firmware", gyro_mdps=None, ideal=False, blind_ms=replay.BLIND_MS):
        self.fw = fw
        self.loop = Loop(loop_hz)
        self.detect = DETECT[detect](fw)
        self.arbiter = ARBITERS[arbiter](fw, CLASSIFY[classify](fw), gyro_mdps=gyro_mdps,
                                         blind_ms=blind_ms, ideal=ideal)
        self.bias = fw.gestures.GyroBias(mdps=gyro_mdps) if gyro_mdps else None
        self.tilt = fw.tilt.TiltController() if fw.settings.TILT_ENABLED else None
        self.samples, self.events = [], []
        self._last_t = None
        self._tilt_key = None
        self.label = f"{detect} · {arbiter} · {classify}"

    def feed(self, s):
        """One sample in; the events it completed out (also kept in .events)."""
        i = len(self.samples)
        self.samples.append(s)
        out = self.arbiter.sample(self.samples, i, self.bias)
        if self.arbiter.open(s.t) and self.loop.sees(s.t):
            # The loop's turn: the gyro baseline, the tilt controller and
            # detect all see this sample, in the firmware's order.
            if self.bias is not None:
                self.bias.update((s.gx, s.gy, s.gz), 0 if self._last_t is None else s.t - self._last_t)
            if self.tilt is not None:
                dt = 0 if self._last_t is None else int(s.t - self._last_t)
                state = self.tilt.update((s.ax, s.ay, s.az), int(s.t), dt)
                key = (state if state in ("up", "down", "released") else "idle", self.tilt.engaged)
                if key != self._tilt_key:
                    self._tilt_key = key
                    out.append({"e": "tilt", "t": s.t, "state": key[0], "engaged": self.tilt.engaged})
            self._last_t = s.t
            dev = self.detect.update(s)
            if dev is not None:
                self.arbiter.trigger(s.t, i, dev, self.bias)
                self.detect.reset()
                out.append({"e": "trigger", "t": s.t, "dev": dev})
        self.events.extend(out)
        return out

    def run(self, samples):
        for s in samples:
            self.feed(s)
        return self.finish()

    def finish(self):
        if self.samples:
            self.events.extend(self.arbiter.sample(self.samples, len(self.samples) - 1,
                                                   self.bias, end=True))
        return self.events


# ── scoring ───────────────────────────────────────────────────────────────
def device_offset(recs):
    """host seconds − device seconds, from the earliest-arriving batch (as
    replay.load_recording computes it)."""
    bs = [r for r in recs if r.get("k") == "b"]
    return min(b["h"] - (b["t0"] + b["d"][-1][0]) / 1e6 for b in bs)


def score_trials(events, recs, d_follow_ms=D_FOLLOW_MS):
    """Per-trial counts for a guided recording; see the module docstring."""
    off = device_offset(recs)
    dm = lambda h: (h - off) * 1000.0  # noqa: E731
    attempts = imu_protocol.trials(recs)
    taps = [e for e in events if e["e"] == "tap"]
    trigs = [e for e in events if e["e"] == "trigger"]
    out = {"T": [0, 0], "T_trig": 0, "GH": [0, 0], "GH_false": 0, "D": [0, 0], "D_false_after": 0,
           "rest_false": 0, "rest_trig": 0, "why": {}}
    claimed = set()
    for a in attempts:
        lo = dm(a["go"])
        hi = (dm(a["done"]) if a["done"] else lo + 8000) + 300
        mine = [e for e in taps if lo <= e["t"] <= hi]
        claimed.update(id(e) for e in mine)
        claimed.update(id(e) for e in trigs if lo <= e["t"] <= hi)
        if a["status"] != "ok":
            continue
        ok = [e for e in mine if e["valid"]]
        for e in mine:
            if not e["valid"]:
                key = f"{a['type']}:{e['why']}"
                out["why"][key] = out["why"].get(key, 0) + 1
        k = a["type"]
        if k == "T":
            out["T"][1] += 1
            out["T"][0] += bool(ok)
            out["T_trig"] += any(lo <= e["t"] <= hi for e in trigs)
        elif k in "GH":
            out["GH"][1] += 1
            out["GH"][0] += bool(ok)
            out["GH_false"] += len(ok)
        else:
            out["D"][1] += 1
            first = mine[0]["t"] if mine else None
            out["D"][0] += bool(first is not None and any(e["t"] - first < d_follow_ms for e in ok))
            out["D_false_after"] += sum(1 for e in ok if first is not None and e["t"] - first >= d_follow_ms)
    out["rest_trig"] = sum(1 for e in trigs if id(e) not in claimed)
    out["rest_false"] = sum(1 for e in taps if e["valid"] and id(e) not in claimed)
    return out


def score_labelled(events, labels, segs):
    sc = replay.score(events, labels, segs)
    trigs = [e for e in events if e["e"] == "trigger"]
    flat = [(a, b) for name, a, b in segs if name == "rest_flat"]
    flat_s = sum(b - a for a, b in flat) / 1000.0
    sc["flat_s"] = flat_s
    sc["flat_trig"] = sum(1 for e in trigs if any(a <= e["t"] <= b for a, b in flat))
    taps_l = [r for r in labels if r.get("label") in replay.TAP_LABELS]
    sc["tap_trig"] = sum(1 for r in taps_l
                         if any(r["tm"] - replay.PRE_MS <= e["t"] <= r["tm"] + replay.POST_MS for e in trigs))
    return sc


def fmt_trials(name, sc):
    T, GH, D = sc["T"], sc["GH"], sc["D"]
    why = "  ".join(f"{k} {v}" for k, v in sorted(sc["why"].items()))
    return (f"   {name:<34} taps {T[0]:2}/{T[1]} (triggered {sc['T_trig']:2}/{T[1]})"
            f"   grab trials w/ false tap {GH[0]:2}/{GH[1]} ({sc['GH_false']} taps)"
            f"   D tap {D[0]}/{D[1]}, false after {sc['D_false_after']}"
            f"   hands-off: {sc['rest_false']} taps / {sc['rest_trig']} triggers"
            + (f"\n   {'':<34} rejected: {why}" if why else ""))


def fmt_labelled(name, sc):
    fal = sum(sc["false"].values())
    nfal = sum(sc["per_label"].get(k, [0, 0])[1] for k in replay.NOT_A_TAP)
    rate = (sc["flat_trig"] / sc["flat_s"] * 60) if sc["flat_s"] else None
    return (f"   {name:<34} taps {sc['hit']:2}/{sc['true_n']} (triggered {sc['tap_trig']:2}/{sc['true_n']})"
            f"   false {fal}/{nfal}   unexplained {sc['unexplained']}"
            + (f"   rest_flat: {sc['flat_trig']} triggers in {sc['flat_s']:.0f} s"
               f" ({rate:.1f}/min)" if rate is not None else ""))


# ── live: follow a recording as it is written ─────────────────────────────
def follow(path, poll_s=0.05, stop=lambda: False):
    """Yield records from a JSONL file that is still being appended to.
    A line is only parsed once its newline has arrived: the recorder writes
    whole lines, but a read can land mid-write."""
    with open(path) as f:
        buf = ""
        while not stop():
            chunk = f.read()
            if not chunk:
                time.sleep(poll_s)
                continue
            buf += chunk
            *lines, buf = buf.split("\n")
            for line in lines:
                if line.strip():
                    yield json.loads(line)


def samples_of(rec):
    """The Samples in one batch record, device ms."""
    return [replay.Sample((rec["t0"] + row[0]) / 1000.0, row[4], row[5], row[6],
                          row[1], row[2], row[3]) for row in rec["d"]]


def live(path, args, knobs):
    print(f"● following {path}  (Ctrl-C to stop)")
    fw = replay.load_firmware(knobs)
    pipe = None
    for rec in follow(path):
        k = rec.get("k")
        if k == "m" and pipe is None:
            mdps = replay.GYRO_MDPS.get(rec.get("CTRL6"))
            pipe = Pipeline(fw, float(args.loop_hz.split(",")[0]), args.detect.split(",")[0],
                            args.arbiter, args.classify, gyro_mdps=mdps, ideal=args.ideal)
            print(f"  pipeline: {pipe.label} at {args.loop_hz.split(',')[0]} Hz, gyro {mdps} mdps/LSB\n")
        elif k == "l" and rec.get("edge") == "go":
            kind, where = rec["type"], rec.get("where")
            print(f"  ── trial {rec['trial']}  {imu_protocol.describe(kind, where)[0]}")
        elif k == "b" and pipe is not None:
            for s in samples_of(rec):
                for e in pipe.feed(s):
                    if e["e"] == "trigger":
                        print(f"     ▲ detect   {e['dev']:4.0f} mg   → capturing")
                    elif e["e"] == "tap":
                        f = e["feats"]
                        g = f.get("gyro_mid_dps")
                        # None = the gyro baseline is still warming up and the
                        # check ABSTAINED — not "measured no rotation".
                        detail = (f"energy {f.get('energy', 0):,.0f}  vertical {f.get('vert_share', 0):.2f}"
                                  + (f"  gyro {g:.2f} dps" if g is not None else "  gyro — (warming up)"))
                        print(("     ✓ TAP        " if e["valid"] else f"     ✗ not a tap ({e['why']})  ")
                              + detail)
                    elif e["e"] == "tilt" and e["engaged"]:
                        print(f"     ↕ tilt {e['state']}")


def newest_recording(unit):
    files = sorted((REPO / "data").glob(f"imu-{unit}-*.jsonl"), key=os.path.getmtime)
    return files[-1] if files else None


# ── CLI ───────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--detect", default="magnitude", help=f"comma list of {sorted(DETECT)}")
    ap.add_argument("--arbiter", default="capture", choices=sorted(ARBITERS))
    ap.add_argument("--classify", default="firmware", help=f"comma list of {sorted(CLASSIFY)}")
    ap.add_argument("--loop-hz", default="240", help="comma list, e.g. 240,145,57")
    ap.add_argument("--ideal", action="store_true", help="no loop blindness")
    ap.add_argument("--knob", action="append", default=[], help="NAME=VALUE over what ships")
    ap.add_argument("--follow", nargs="?", const="newest", metavar="FILE",
                    help="live: follow a recording being made (default: the newest)")
    ap.add_argument("--unit", default="bottle-01")
    args = ap.parse_args(argv)
    knobs = {}
    for kv in args.knob:
        k, v = kv.split("=", 1)
        knobs[k] = json.loads(v)

    if args.follow:
        path = newest_recording(args.unit) if args.follow == "newest" else Path(args.follow)
        if path is None:
            sys.exit("✗ no recording to follow — start `make imu-record` first")
        try:
            live(path, args, knobs)
        except KeyboardInterrupt:
            print()
        return

    sessions_path = REPO / "data" / "imu-sessions.json"
    sessions = json.loads(sessions_path.read_text()) if sessions_path.exists() else {}
    files = args.files or [REPO / "data" / f for f, e in sessions.items()
                           if isinstance(e, dict) and e.get("use") is True]
    fw = replay.load_firmware(knobs)
    print(f"what ships{' + ' + str(knobs) if knobs else ''}: trigger "
          f"{fw.settings.TAP_TRIGGER_THRESHOLD_MG} mg, energy < {fw.settings.TAP_ENERGY_THRESHOLD:,}, "
          f"vertical ≤ {fw.settings.TAP_VERTICAL_SHARE_MAX}, gyro ≤ {fw.settings.TAP_GYRO_MID_MAX_DPS} dps")
    for path in files:
        entry = sessions.get(path.name)
        header, samples, labels, segs = replay.load_recording(path, entry)
        recs = [json.loads(line) for line in open(path)] if header.get("protocol") else None
        print(f"\n== {path.name}" + (f"  (guided: {header['protocol']})" if recs else ""))
        for hz in [float(x) for x in args.loop_hz.split(",")]:
            print(f"  loop {hz:g} Hz{' ideal' if args.ideal else ''}")
            for s1 in args.detect.split(","):
                for s2 in args.classify.split(","):
                    fw = replay.load_firmware(knobs)        # fresh tilt state per run
                    pipe = Pipeline(fw, hz, s1, args.arbiter, s2,
                                    gyro_mdps=header.get("gyro_mdps"), ideal=args.ideal)
                    ev = pipe.run(samples)
                    print(fmt_trials(pipe.label, score_trials(ev, recs)) if recs
                          else fmt_labelled(pipe.label, score_labelled(ev, labels, segs)))


if __name__ == "__main__":
    main()
