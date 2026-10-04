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
      not the bottle      u knock table   i knock shelf/other surface   o bump (door, footsteps, bag)
      handling            j lift off   k set down   l grab (touch/grip, no lift)
      p  mark — "something odd just happened"

  STATES (a stretch of time; press once to START, again to END, or press a
  different state key to switch)
      n  rest_flat   upright on a surface, untouched
      m  rest_lean   resting at a slight lean (4-12 deg, the deadzone edge) — this is
                     how to CAUSE a stuck tilt on purpose: put it down tilted
      ,  hand_hold   held in the hand, trying to be still
      .  tilting     actively tilting to adjust brightness
      ;  carry       walking with it

  Backspace or 0 undoes the last label. Append-only, same as interaction_log.py.
  q quits.

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
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interaction_log import MPREMOTE, REPO, UNDO_KEYS, _git_sha, parse_line  # noqa: E402

POINTS = {
    "7": "tap_top", "8": "tap_body", "9": "tap_base",
    "u": "knock_table", "i": "knock_shelf", "o": "bump_other",
    "j": "lift", "k": "set_down", "l": "grab",
    "p": "mark",
}
STATES = {
    "n": "rest_flat", "m": "rest_lean", ",": "hand_hold", ".": "tilting", ";": "carry",
}
LABEL_MAP = "intent-1"
LEGEND = (
    ("glass ", "7 top   8 body   9 base"),
    ("other ", "u table   i shelf   o bump"),
    ("hands ", "j lift   k set down   l grab   p mark"),
    ("state ", "n flat   m lean   , hold   . tilt   ; carry   (press again to end)"),
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


def header_record(args, git, now):
    return {"k": "h", "h": now, "kind": "imu_stream", "unit": args.unit,
            "mount": args.mount, "odr_hz": args.odr, "surface": args.surface,
            "note": args.note, "label_map": LABEL_MAP, "git": git, "format": 2,
            "started": datetime.fromtimestamp(now).isoformat(timespec="seconds")}


def out_path(out_dir, unit, now):
    return Path(out_dir) / f"imu-{unit}-{datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}.jsonl"


# ── I/O ────────────────────────────────────────────────────────────────────
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
    ap.add_argument("--surface", default="", help="what it sits on (wood, stone, felt…)")
    ap.add_argument("--note", default="")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data")
    args = ap.parse_args()
    if not MPREMOTE.exists():
        sys.exit(f"✗ {MPREMOTE} missing — run `make setup`")

    now = time.time()
    path = out_path(args.out_dir, args.unit, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(MPREMOTE), "mount", "micropython",
           "exec", f"import interlog; interlog.STREAM_ODR = {args.odr}",
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
    standing = []
    current = None
    n_batches = n_labels = 0
    last_hz = None
    last_status = time.time()
    first_sample_at = None
    buf = b""

    print(f"● recording → {path}")
    print(f"  unit={args.unit} mount={args.mount} odr={args.odr} Hz surface={args.surface or '—'}\n")
    print("  keys (right hand):")
    for name, keys in LEGEND:
        print(f"    {name} {keys}")
    print("    undo   Backspace or 0          quit   q\n")

    with open(path, "w") as f:
        f.write(json.dumps(header_record(args, _git_sha(), now)) + "\n")
        try:
            while proc.poll() is None:
                watch = [out_fd] + ([sys.stdin] if tty else [])
                ready, _, _ = select.select(watch, [], [], 0.5)
                for r in ready:
                    if r is sys.stdin:
                        ch = sys.stdin.read(1)
                        t_now = time.time()
                        if ch == "q":
                            raise KeyboardInterrupt
                        if ch in UNDO_KEYS:
                            if not standing:
                                print("  (nothing to undo)")
                                continue
                            target = standing.pop()
                            f.write(json.dumps({"k": "l", "h": t_now, "undo": target}) + "\n")
                            f.flush()
                            print(f"  ✖ undid label #{target}")
                            continue
                        if ch in POINTS:
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
                                first_sample_at = first_sample_at or time.time()
                            elif rec["k"] == "t":
                                last_hz = rec.get("hz")
                            elif rec["k"] == "x":
                                print("  | " + rec["text"].rstrip())
                f.flush()
                if time.time() - last_status >= 10:
                    last_status = time.time()
                    print(f"  … {n_batches * 10} samples, {last_hz or 0:.0f} Hz achieved, "
                          f"{n_labels} labels" + (f", in [{current}]" if current else ""))
                if first_sample_at is None and time.time() - now > 30:
                    first_sample_at = -1
                    print("  ⚠ 30 s and no samples — see the lines above (IMU found? "
                          "config.py pins/IMU_I2C_ID?)")
        except KeyboardInterrupt:
            pass
        finally:
            if old_term is not None:
                import termios
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            print("  stopping… (tidying the device, a few seconds)")
            _restore_device()

    print(f"\n■ {path}\n  {n_batches * 10} samples, {n_labels} labels")


if __name__ == "__main__":
    main()
