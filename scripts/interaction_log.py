#!/usr/bin/env python3
"""scripts/interaction_log.py — record a tap/tilt session to the Mac.

Run it:  make interaction-log UNIT=bottle-01 [MOUNT=base|lid] [NOTE="..."]

Phase 0 of docs/imu-interaction-plan.md. Runs the real firmware with
recording on (micropython/interlog_run.py, mounted from this Mac — nothing is
written to the board's flash) and tees everything it prints to a JSONL file
under data/. While it runs, single keypresses label what just happened:

    t  true tap      — I tapped and it responded correctly
    f  FALSE tap     — it responded and I did not tap (the failure to catch)
    m  missed tap    — I tapped and nothing happened
    u  unwanted tilt — it started adjusting brightness and I was not tilting
    k  stuck tilt    — it is still "engaged" and should not be
    g  grabbed       — I grabbed/moved the bottle (context, not a failure)
    q  quit  (Ctrl-C also works)

Label the moment it happens, with one key. A label pressed AFTER the fact is
still useful — it is stamped with the host clock and attached to whatever the
device was doing in the seconds before — but the one-key habit is the whole
point: reconstructing failures from a day of logs is not something anyone
does.

--unit is REQUIRED, and goes into the file's header. Every per-unit fact in
this project (docs/gift-registry.md) has been established by hand and lost
track of once already; a recording of an unnamed bottle is a recording nobody
can use two months from now. --mount records where the IMU sits, because a
lid-mounted sensor sees a different signal from a base-mounted one
(docs/chandelier-concept.md addendum).
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
from rtc_drift import MPREMOTE, REPO  # noqa: E402  (worktree-stable paths)

TAG = "~L "
LABELS = {
    "t": "true_tap",
    "f": "false_tap",
    "m": "missed_tap",
    "u": "unwanted_tilt",
    "k": "stuck_tilt",
    "g": "grabbed",
}


# ── pure: record shaping (host-tested in tests/test_interaction_log.py) ────
def parse_line(line, now):
    """One console line → one record dict, or None for blank lines.

    Tagged lines are the device's own records (samples, events, capture
    chunks, meta) and keep their shape, gaining `h`, the HOST receive time.
    Everything else is ordinary print() output — kept as kind "x" rather than
    dropped, because the firmware's `[LINE]`/`[SLEEP]` prints are free context.
    A tagged line that fails to parse (a truncated line at a reset, say) is
    kept as text rather than lost or crashing the recording.
    """
    line = line.rstrip("\r\n")
    if not line.strip():
        return None
    if line.startswith(TAG):
        try:
            rec = json.loads(line[len(TAG):])
        except ValueError:
            return {"k": "x", "h": now, "text": line, "bad": True}
        rec["h"] = now
        return rec
    return {"k": "x", "h": now, "text": line}


def label_record(key, now):
    name = LABELS.get(key)
    if name is None:
        return None
    return {"k": "l", "h": now, "label": name}


def header_record(unit, mount, note, git, now):
    return {"k": "h", "h": now, "unit": unit, "mount": mount, "note": note or "",
            "git": git, "started": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "format": 1}


def out_path(out_dir, unit, now):
    stamp = datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S")
    return Path(out_dir) / f"interaction-{unit}-{stamp}.jsonl"


# ── I/O ────────────────────────────────────────────────────────────────────
def _git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def _restore_device():
    """Drop the stale mount, as scripts/dev.sh does: a soft reset re-runs the
    board's flashed main.py, so interrupt whatever auto-started afterwards.
    Takes a few seconds; an impatient second Ctrl-C is fine (the recording is
    already closed), it just skips the tidy-up."""
    try:
        for args in (["soft-reset"], ["exec", "pass"]):
            subprocess.run([str(MPREMOTE)] + args, capture_output=True, timeout=15)
            time.sleep(0.5)
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        print("  (device tidy-up skipped — press the board's reset if it looks stuck)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--unit", required=True, help="which physical bottle, e.g. bottle-01")
    ap.add_argument("--mount", default="base", choices=("base", "lid", "other"),
                    help="where the IMU is mounted (default base)")
    ap.add_argument("--note", default="", help="free text stored in the header")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data")
    args = ap.parse_args()

    if not MPREMOTE.exists():
        sys.exit(f"✗ {MPREMOTE} missing — run `make setup`")

    now = time.time()
    path = out_path(args.out_dir, args.unit, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(MPREMOTE), "mount", "micropython", "run", "micropython/interlog_run.py"]
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # stdin=DEVNULL: this process reads the keypress labels from the terminal,
    # and a child inheriting the same tty can swallow them (or reset its modes).
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

    counts = {"s": 0, "e": 0, "c": 0, "l": 0, "x": 0}
    last_event = "—"
    last_console = ""
    last_tagged = None
    warned_silent = False
    last_status = time.time()
    buf = b""

    print(f"● recording → {path}")
    print(f"  unit={args.unit} mount={args.mount}   keys: "
          + "  ".join(f"{k}={v}" for k, v in LABELS.items()) + "   q=quit\n")

    with open(path, "w") as f:
        f.write(json.dumps(header_record(args.unit, args.mount, args.note,
                                         _git_sha(), now)) + "\n")
        try:
            while proc.poll() is None:
                watch = [out_fd] + ([sys.stdin] if tty else [])
                ready, _, _ = select.select(watch, [], [], 0.5)
                for r in ready:
                    if r is sys.stdin:
                        ch = sys.stdin.read(1)
                        if ch == "q":
                            raise KeyboardInterrupt
                        rec = label_record(ch, time.time())
                        if rec:
                            f.write(json.dumps(rec) + "\n")
                            f.flush()
                            counts["l"] += 1
                            print(f"  ✎ {rec['label']:<14} (after: {last_event})")
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
                            counts[rec["k"]] = counts.get(rec["k"], 0) + 1
                            if rec["k"] == "e":
                                last_event = rec.get("e", "?")
                                print(f"  · {last_event}")
                            elif rec["k"] == "x":
                                # Show every console line. The device prints
                                # only a handful before the loop starts, and a
                                # silent terminal reads exactly like a hung one.
                                last_console = rec["text"].strip()
                                print("  | " + rec["text"].rstrip())
                            if rec["k"] in ("s", "e", "c"):
                                last_tagged = time.time()
                f.flush()
                if time.time() - last_status >= 30:
                    last_status = time.time()
                    print(f"  … {counts['s']} samples, {counts['e']} events, "
                          f"{counts['c']} capture chunks, {counts['l']} labels")
                if (last_tagged is None and not warned_silent
                        and time.time() - now > 60):
                    warned_silent = True
                    print("  ⚠ 60 s and no samples. Last console line was:\n"
                          f"      {last_console or '(nothing)'}\n"
                          "    Expect '[interlog] recording on' once the loop starts. Nothing after\n"
                          "    the startup lines means the loop is not running yet: slow imports over\n"
                          "    the mount, or GESTURE_ENABLED is off in config.py. Try `make dev` and\n"
                          "    compare when its `Station:` line appears.")
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

    print(f"\n■ {path}\n  {counts['s']} samples, {counts['e']} events, "
          f"{counts['c']} capture chunks, {counts['l']} labels")
    if counts["s"] == 0:
        print("  ⚠ no samples arrived — is GESTURE_ENABLED on in config.py, and did the IMU "
              "come up? Look for ✗/⚠ lines above.")


if __name__ == "__main__":
    main()
