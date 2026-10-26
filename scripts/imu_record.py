#!/usr/bin/env python3
"""scripts/imu_record.py — record the RAW sensor stream, labelled by what you DID.

Run it:  make imu-record UNIT=bottle-01 [MOUNT=base|lid] [ODR=240] [SURFACE=wood] [NOTE="..."]

The data-collection sandbox for docs/imu-interaction-plan.md. Unlike
`make interaction-log`, this runs NOTHING of the firmware: micropython/
imu_stream.py streams accel + gyro at the sensor's rate and the Mac writes it
to data/imu-<unit>-<time>.jsonl. Every decision the firmware would have made
can be reproduced afterwards by replaying the stream through the real code
(at any simulated loop rate), so what needs recording is the truth: the
sensor, and what the HUMAN did.

Labels are INTENT, not verdicts — "I knocked the table", not "it falsely
tapped". Right hand only; the left holds the bottle.

  POINTS (something that happens at a moment)
      taps on the glass   7 top/neck   8 body   9 base
      not the bottle      u knock the table   i tap ANOTHER object on it (cup, basket)
                          o bump (footsteps, door, sitting down on a chair)
      handling            l grab (hand closes on it)   j lift off   k set down
                          p release (hand lets go) — the natural sequence is l j k p
      h  mark — "something odd just happened"

  STATES (a stretch of time; press once to START, again to END, press /
  to end whichever is open, or press a different state key to switch.
  An open state is closed automatically when you quit.)
      n  rest_flat   on the surface, upright, NO hand on it
      m  rest_lean   on the surface, propped at a slight lean (4-12 deg — a coin or
                     folded card under one edge), NO hand on it. This is how to
                     CAUSE a stuck tilt on purpose: the deadzone is 8 deg
      ,  hand_hold   in the hand, trying to keep it still — no intent to adjust
      .  tilting     in the hand, deliberately tilting to change brightness
      ;  carry       walking with it
      (lean = surface does the holding; hold = hand does; tilt = hand moves it)

  Backspace or 0 undoes the last label. Append-only, same as interaction_log.py.
  q quits.

GUIDED (PROTOCOL=tap-vs-grab): the script says what to do. A countdown with
the instruction in words — hands off the bottle while it runs — then a beep
and GO. Do it, both hands free, and press SPACE when you've let go. r = "I
messed that up": the attempt is kept, labelled redo, and repeated at once —
also during the next countdown, if you only notice then. The label is the
cue, not a key press; why, and the trial records: scripts/imu_protocol.py.
START_AT=n resumes a session that was stopped part-way (a new file).

Session notes and relabels live in data/imu-sessions.json (gitignored with the
recordings): which files to analyse, which were dry runs, and what a label
actually meant in a given session.

Alignment: every batch from the device carries its own microsecond clock, and
the Mac stamps each batch (and each label) with its receive time. Offline,
fit device time -> host time over all batches; the residual is a few tens of
ms (one batch ~ 40 ms plus USB latency), fine for labels that mean "around
now". Press the key AFTER the thing, not before.
"""

import argparse
import json
import os
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imu_protocol  # noqa: E402
from interaction_log import (MPREMOTE, REPO, UNDO_KEYS, _git_sha, parse_line,  # noqa: E402
                             stop_child)

POINTS = {
    "7": "tap_top", "8": "tap_body", "9": "tap_base",
    "u": "knock_table", "i": "knock_object", "o": "bump_other",
    "j": "lift", "k": "set_down", "l": "grab", "p": "release",
    "h": "mark",
}
STATES = {
    "n": "rest_flat", "m": "rest_lean", ",": "hand_hold", ".": "tilting", ";": "carry",
}
END_STATE_KEY = "/"      # ends whatever state is open, without remembering its key
LABEL_MAP = "intent-3"   # intent-1: i was "knock_shelf"; intent-2: p was "mark"
#                          (used as release). See data/imu-sessions.json
LEGEND = (
    ("glass ", "7 top   8 body   9 base"),
    ("other ", "u table   i object on table   o bump (floor, door, chair)"),
    ("hands ", "l grab   j lift   k set down   p release        h mark"),
    ("state ", "n flat   m lean   , hold   . tilt   ; carry   (press again to end)"),
    ("end   ", "/  ends whatever state is open — quitting also ends it"),
)
ODRS = (60, 120, 240, 480, 960)


# ── pure: records (host-tested in tests/test_imu_record.py) ───────────────
def point_record(key, now, seq):
    name = POINTS.get(key)
    if name is None:
        return None
    return {"k": "l", "h": now, "id": seq, "label": name}


def state_toggle(key, now, seq, current):
    """Returns (record, new_current_state). Pressing the active state's key
    ends it; pressing another key switches (the previous one ends implicitly
    at that moment — segments() closes it)."""
    name = STATES.get(key)
    if name is None:
        return None, current
    if current == name:
        return {"k": "l", "h": now, "id": seq, "state": name, "edge": "end"}, None
    return {"k": "l", "h": now, "id": seq, "state": name, "edge": "start"}, name


def end_current(now, seq, current):
    """The record that ends `current`, or None if nothing is open."""
    if current is None:
        return None
    return {"k": "l", "h": now, "id": seq, "state": current, "edge": "end"}


def effective(records):
    voided = {r["undo"] for r in records if r.get("k") == "l" and "undo" in r}
    return [r for r in records
            if r.get("k") == "l" and "undo" not in r and r.get("id") not in voided]


def segments(records, end_h):
    """[(state, h_start, h_end)] from the label stream, honouring undo. A
    start closes whatever state was open; the last one closes at `end_h`."""
    out, cur, since = [], None, None
    for r in effective(records):
        if "state" not in r:
            continue
        if cur is not None:
            out.append((cur, since, r["h"]))
            cur = None
        if r["edge"] == "start":
            cur, since = r["state"], r["h"]
    if cur is not None:
        out.append((cur, since, end_h))
    return out


def apply_corrections(records, entry):
    """Apply a data/imu-sessions.json entry to a recording's records WITHOUT
    touching the file: `void` drops labels by id, `add` inserts labels written
    after the fact (in host-time order), `relabel` renames point labels. This is
    where post-hoc fixes live — the recording stays exactly as captured."""
    if not entry:
        return records
    void = set(entry.get("void", ()))
    relabel = entry.get("relabel", {})
    out = []
    for r in records:
        if r.get("k") == "l" and r.get("id") in void:
            continue
        if r.get("k") == "l" and r.get("label") in relabel:
            r = dict(r, label=relabel[r["label"]])
        out.append(r)
    for a in entry.get("add", ()):
        out.append(dict(a))
    labels = sorted((r for r in out if r.get("k") == "l"), key=lambda r: r["h"])
    rest = [r for r in out if r.get("k") != "l"]
    return rest + labels


def header_record(args, git, now):
    return {"k": "h", "h": now, "kind": "imu_stream", "unit": args.unit,
            "mount": args.mount, "odr_hz": args.odr, "gyro_fs_dps": args.gyro_fs, "surface": args.surface,
            "note": args.note, "label_map": LABEL_MAP, "git": git, "format": 2,
            "protocol": getattr(args, "protocol", None),
            "started": datetime.fromtimestamp(now).isoformat(timespec="seconds")}


def out_path(out_dir, unit, now):
    return Path(out_dir) / f"imu-{unit}-{datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}.jsonl"


# ── I/O ────────────────────────────────────────────────────────────────────
_SOUND = Path("/System/Library/Sounds/Tink.aiff")


def _beep():
    # The GO cue, so eyes can stay on the bottle. Fire-and-forget: the record
    # is stamped before this, and the sound lags it by tens of ms.
    if _SOUND.exists():
        subprocess.Popen(["afplay", str(_SOUND)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        sys.stdout.write("\a")


def _restore_device():
    try:
        for a in (["soft-reset"], ["exec", "pass"]):
            subprocess.run([str(MPREMOTE)] + a, capture_output=True, timeout=15)
            time.sleep(0.5)
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        print("  (device tidy-up skipped — press the board's reset if it looks stuck)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--unit", required=True)
    ap.add_argument("--mount", default="base", choices=("base", "lid", "other"))
    ap.add_argument("--odr", type=int, default=240, choices=ODRS,
                    help="sensor output rate; >240 is untested here — read the achieved Hz")
    ap.add_argument("--gyro-fs", type=int, default=1000, choices=(125, 250, 500, 1000, 2000),
                    help="gyro full scale, dps (default 1000: the default range clipped on "
                         "ordinary handling). The CTRL6 value actually set is in the header")
    ap.add_argument("--surface", default="", help="what it sits on (wood, stone, felt…)")
    ap.add_argument("--note", default="")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data")
    ap.add_argument("--protocol", choices=sorted(imu_protocol.PROTOCOLS),
                    help="guided trials: the script cues each one (see the docstring)")
    ap.add_argument("--rest", type=float, default=4.0,
                    help="guided: hands-off countdown before each trial, s")
    ap.add_argument("--start-at", type=int, default=1, help="guided: first trial number")
    ap.add_argument("--no-beep", action="store_true")
    args = ap.parse_args()
    guide = None
    if args.protocol:
        steps = imu_protocol.plan(args.protocol)
        if not 1 <= args.start_at <= len(steps):
            sys.exit(f"✗ --start-at must be 1..{len(steps)}")
        guide = imu_protocol.Guide(steps, rest_s=args.rest, start_at=args.start_at)
    if not MPREMOTE.exists():
        sys.exit(f"✗ {MPREMOTE} missing — run `make setup`")

    now = time.time()
    path = out_path(args.out_dir, args.unit, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(MPREMOTE), "mount", "micropython",
           "exec", (f"import interlog; interlog.STREAM_ODR = {args.odr}; "
                    f"interlog.STREAM_GYRO_FS = {args.gyro_fs}"),
           "run", "micropython/imu_stream.py"]
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_fd = proc.stdout.fileno()

    tty = sys.stdin.isatty()
    old_term = None
    if tty:
        import termios
        import tty as ttymod
        old_term = termios.tcgetattr(sys.stdin)
        ttymod.setcbreak(sys.stdin.fileno())

    seq = 0
    go_h = 0.0
    standing = []
    current = None
    n_batches = n_labels = 0
    last_hz = None
    n_samples = 0
    last_data_at = None     # host time of the last batch — a stall is its absence
    stalled = False
    resets = 0
    last_status = time.time()
    first_sample_at = None
    buf = b""

    print(f"● recording → {path}")
    print(f"  unit={args.unit} mount={args.mount} odr={args.odr} Hz surface={args.surface or '—'}\n")
    if guide:
        print(f"  guided: {args.protocol}, {len(guide.queue)} trials, {args.rest:g} s countdown")
        print("    SPACE  done (after you've let go)     r  I messed that up — redo it")
        print("    h      mark something odd             q  quit (START_AT= resumes)")
        print("  Hands off the bottle during every countdown. Starting when data flows…\n")
    else:
        print("  keys (right hand):")
        for name, keys in LEGEND:
            print(f"    {name} {keys}")
        print("    undo   Backspace or 0          quit   q\n")
    shown = None            # the countdown number on screen

    def emit(recs):
        nonlocal seq
        for r in recs:
            seq += 1
            f.write(json.dumps(dict(r, id=seq)) + "\n")
        f.flush()

    with open(path, "w") as f:
        f.write(json.dumps(header_record(args, _git_sha(), now)) + "\n")
        try:
            while proc.poll() is None:
                watch = [out_fd] + ([sys.stdin] if tty else [])
                ready, _, _ = select.select(watch, [], [], 0.1 if guide else 0.5)
                for r in ready:
                    if r is sys.stdin:
                        ch = sys.stdin.read(1)
                        t_now = time.time()
                        if ch == "q":
                            raise KeyboardInterrupt
                        if guide:
                            was = guide.current
                            recs, handled = guide.key(ch, t_now)
                            emit(recs)
                            for r in recs:
                                if r["edge"] == "done":
                                    mark = "✓ kept" if r["status"] == "ok" else "↺ redo"
                                    print(f"\r  {mark} {r['trial']}  "
                                          f"({r['h'] - go_h:.1f} s)  · {n_samples} samples, "
                                          f"{last_hz or 0:.0f} Hz" + " " * 10)
                                elif r["edge"] == "verdict":
                                    print(f"\r  ↺ {r['trial']} re-judged: redo, "
                                          f"then {was} again" + " " * 20)
                            if handled:
                                continue
                        if ch in UNDO_KEYS:
                            if not standing:
                                print("  (nothing to undo)")
                                continue
                            target = standing.pop()
                            f.write(json.dumps({"k": "l", "h": t_now, "undo": target}) + "\n")
                            f.flush()
                            print(f"  ✖ undid label #{target}")
                            continue
                        if ch == END_STATE_KEY:
                            if current is None:
                                print("  (no state is open)")
                                continue
                            seq += 1
                            rec = end_current(t_now, seq, current)
                            msg = f"▌#{seq} {current} end"
                            current = None
                        elif ch in POINTS:
                            seq += 1
                            rec = point_record(ch, t_now, seq)
                            msg = f"✎ #{seq} {rec['label']}"
                        elif ch in STATES:
                            seq += 1
                            rec, current = state_toggle(ch, t_now, seq, current)
                            msg = f"▌#{seq} {rec['state']} {rec['edge']}"
                        else:
                            continue
                        standing.append(seq)
                        n_labels += 1
                        f.write(json.dumps(rec) + "\n")
                        f.flush()
                        print("  " + msg + (f"   [state: {current}]" if current else ""))
                    else:
                        chunk = os.read(out_fd, 65536)
                        if not chunk:
                            continue
                        buf += chunk
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            rec = parse_line(raw.decode("utf-8", "replace"), time.time())
                            if rec is None:
                                continue
                            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                            if rec["k"] == "b":
                                n_batches += 1
                                n_samples += len(rec.get("d", ()))
                                first_sample_at = first_sample_at or time.time()
                                last_data_at = time.time()
                                if stalled:
                                    stalled = False
                                    print("  ✓ stream resumed")
                            elif rec["k"] == "t":
                                last_hz = rec.get("hz")
                                resets = rec.get("resets", resets)
                            elif rec["k"] == "e" and rec.get("e") == "imu_reset":
                                print("  ⚠ the sensor reset itself (stalled %s ms) — "
                                      "reconfigured, #%s this recording"
                                      % (rec.get("stalled_ms"), rec.get("n")))
                            elif rec["k"] == "x":
                                print("  | " + rec["text"].rstrip())
                f.flush()
                # Say so the MOMENT data stops. The 2026-10-26 dry run streamed
                # 2.1 s and then nothing, and this loop went on printing
                # "234 Hz achieved" for the rest of it — the Hz came from the
                # last heartbeat, which had stopped arriving.
                if (last_data_at is not None and not stalled
                        and time.time() - last_data_at > 1.5):
                    stalled = True
                    if guide:
                        emit(guide.stall(time.time()))
                        print(f"\n  ⚠ STREAM STALLED — trial {guide.current} paused (voided "
                              "if it had started); it restarts when data returns.")
                    else:
                        print("  ⚠ STREAM STALLED — no samples for 1.5 s. Labels pressed now "
                              "have no data under them; stop (q) and check before carrying on.")
                if guide:
                    t_now = time.time()
                    if guide.phase == "idle" and first_sample_at and first_sample_at > 0:
                        emit(guide.begin(t_now))
                    elif guide.phase == "paused" and not stalled:
                        emit(guide.resume(t_now))
                    recs = guide.tick(t_now)
                    if recs:
                        emit(recs)
                        go_h = recs[0]["h"]
                        if not args.no_beep:
                            _beep()
                        print("\r     ▶ GO" + " " * 20, flush=True)
                        shown = None
                    if guide.fresh:
                        guide.fresh = False
                        print("\n" + guide.announce())
                    left = guide.countdown(t_now)
                    if left is not None and left != shown:
                        shown = left
                        print(f"\r     {left} …", end="", flush=True)
                    if guide.phase == "finished":
                        kept, redone = guide.summary()
                        print("\n  ● protocol complete — kept "
                              + ", ".join(f"{k} {v}" for k, v in sorted(kept.items()))
                              + f"; {redone} redone. Stopping.")
                        raise KeyboardInterrupt
                elif time.time() - last_status >= 10:
                    last_status = time.time()
                    print(f"  … {n_samples} samples, {last_hz or 0:.0f} Hz now, "
                          f"{n_labels} labels" + (f", in [{current}]" if current else "")
                          + (f", sensor reset {resets}×" if resets else "")
                          + ("   ⚠ STALLED" if stalled else ""))
                if first_sample_at is None and time.time() - now > 30:
                    first_sample_at = -1
                    print("  ⚠ 30 s and no samples — see the lines above (IMU found? "
                          "config.py pins/IMU_I2C_ID?)")
        except KeyboardInterrupt:
            pass
        finally:
            if guide:
                recs = guide.abandon(time.time())
                if recs:
                    emit(recs)
                    print(f"\n  (trial {recs[0]['trial']} cut off — labelled abandoned)")
            if current is not None:
                # A recording that ends mid-state would leave a segment with no
                # end; close it here so every state in the file is a closed
                # interval, and say so.
                seq += 1
                f.write(json.dumps(end_current(time.time(), seq, current)) + "\n")
                print(f"  (closed open state: {current})")
            if old_term is not None:
                import termios
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
            print("  stopping… (tidying the device, a few seconds)")
            stop_child(proc)
            _restore_device()

    tally = (f"{len(guide.kept)}/{len(guide.trials)} trials kept" if guide
             else f"{n_labels} labels")
    print(f"\n■ {path}\n  {n_samples} samples, {tally}")


if __name__ == "__main__":
    main()
