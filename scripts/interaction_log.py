#!/usr/bin/env python3
"""scripts/interaction_log.py — record a tap/tilt session to the Mac.

Run it:  make interaction-log UNIT=bottle-01 [MOUNT=base|lid] [NOTE="..."]

Phase 0 of docs/imu-interaction-plan.md. Runs the real firmware with
recording on (micropython/interlog_run.py, mounted from this Mac — nothing is
written to the board's flash) and tees everything it prints to a JSONL file
under data/. While it runs, single keypresses label what just happened:

    Right hand only (the left is holding the bottle), one row per theme:

      tap    7 true     8 FALSE    9 missed
      tilt   u true     i FALSE    o missed    p stuck
      grab   j grabbed  k false    l missed
      env    m ambient  — a knock on the TABLE / shelf / room, not the bottle
      ⌫      undo the last label  (Backspace, or 0)
      q      quit  (Ctrl-C also works)

    "true"   = it did what I meant.  "FALSE" = it responded and I meant
    nothing (the failure to catch).  "missed" = I meant it and nothing
    happened.  "stuck" = tilt still engaged when it should have let go.
    `m` ambient is for vibration that did not come from touching the bottle
    (a tap on the table, a door, footsteps). Press it whether you did it on
    purpose — a deliberate negative control, the bottle SHOULD ignore it — or
    it just happened; then ALSO press 8 (false tap) if the bottle responded.
    Ambient events look exactly like taps to every feature but their source,
    so they are the class the recogniser has least evidence about.
    Grab labels are ground truth for a HANDLING state the arbiter does not
    have yet (docs/imu-interaction-plan.md §5, Phase 2): today only `j`
    means anything, but `k`/`l` cost nothing to record now.

    A wrong key is not a lost cause: Backspace (or 0) UNDOES the last label,
    then press the right one. The file is append-only — an undo is a record
    that voids an earlier label by id, never an edit — so a mislabel and its
    correction are both visible later, and `effective_labels()` is what a
    loader should use.

    Labels arrive BEFORE the response they describe. A tap blocks the device
    ~1.2 s while it captures, so a label pressed right after the tap is
    written before that tap's `tap_response` record exists. That is not a
    bug; association has to be by time window, never "the last event". Each
    label therefore records `near`, the events of the previous few seconds.

    Line markers:  ▶ something the bottle DID (label it)   · information

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
    "7": "true_tap", "8": "false_tap", "9": "missed_tap",
    "u": "true_tilt", "i": "false_tilt", "o": "missed_tilt", "p": "stuck_tilt",
    "j": "grabbed", "k": "false_grab", "l": "missed_grab",
    "m": "ambient",
}
# Rows for the legend, in the order they sit under the right hand.
LEGEND = (
    ("tap ", ("7", "8", "9")),
    ("tilt", ("u", "i", "o", "p")),
    ("grab", ("j", "k", "l")),
    ("env ", ("m",)),
)
LABEL_MAP_VERSION = 2   # v1 had t/f/m/u/k/g and "unwanted_tilt"


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


# Things the bottle DID — the ones worth a label. Everything else an event
# stream carries (a trigger, a capture summary, tilt sitting idle) is context.
_ACTION_TILT_STATES = ("up", "down", "released")


def event_symbol(rec):
    """▶ for a pipeline ACTION (label it), · for information."""
    e = rec.get("e")
    if e in ("tap_response", "asleep"):
        return "▶"
    if e == "tilt" and rec.get("state") in _ACTION_TILT_STATES:
        return "▶"
    return "·"


def describe_event(rec):
    e = rec.get("e", "?")
    if e == "tap_response":
        return "tap_response  %s" % rec.get("response")
    if e == "tilt":
        return "tilt          %s%s" % (rec.get("state"),
                                        "  (engaged)" if rec.get("engaged") else "")
    if e == "rate":
        return "loop rate     %.0f Hz   (longest gap %d ms)" % (rec.get("hz") or 0,
                                                              rec.get("gap_ms") or 0)
    if e == "trigger":
        return "trigger       dev=%s%s" % (int(rec.get("dev") or 0),
                                            "  (quiet hours)" if rec.get("quiet") else "")
    if e == "capture_end":
        return "capture_end   energy=%s  %s" % (int(rec.get("energy") or 0),
                                                 "tap" if rec.get("valid") else "handling")
    return e


def legend_lines():
    out = []
    for name, keys in LEGEND:
        cells = []
        for k in keys:
            label = LABELS[k]
            word = label if label in ("grabbed", "ambient") else label.split("_")[0]
            cells.append("%s %s" % (k, word))
        out.append("    %s   %s" % (name, "   ".join(cells)))
    out.append("    ⌫      undo last label   (Backspace or 0)")
    out.append("    q      quit")
    return out


UNDO_KEYS = ("\x7f", "\x08", "0")
NEAR_WINDOW_S = 4.0


def label_record(key, now, seq=None, near=None):
    name = LABELS.get(key)
    if name is None:
        return None
    rec = {"k": "l", "h": now, "label": name}
    if seq is not None:
        rec["id"] = seq
    if near:
        rec["near"] = list(near)
    return rec


def undo_record(target_id, now):
    """Voids an earlier label. Never an edit: the mislabel stays in the file."""
    return {"k": "l", "h": now, "undo": target_id}


def effective_labels(records):
    """The labels that stand: every label record minus the ones an undo voids."""
    voided = {r["undo"] for r in records if r.get("k") == "l" and "undo" in r}
    return [r for r in records
            if r.get("k") == "l" and "label" in r and r.get("id") not in voided]


def near_events(recent, now, window=NEAR_WINDOW_S):
    """Descriptions of events in the last `window` seconds, oldest first."""
    return [d for t, d in recent if now - t <= window]


def header_record(unit, mount, note, git, now):
    return {"k": "h", "h": now, "unit": unit, "mount": mount, "note": note or "",
            "label_map": LABEL_MAP_VERSION, "git": git, "started": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
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
    ap.add_argument("--level", default="full", choices=("full", "rate"),
                    help="'rate' = loop-rate meter and events only (no gyro, no samples): "
                         "compare with 'full' to see how much slowness is the recorder")
    ap.add_argument("--note", default="", help="free text stored in the header")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data")
    args = ap.parse_args()

    if not MPREMOTE.exists():
        sys.exit(f"✗ {MPREMOTE} missing — run `make setup`")

    now = time.time()
    path = out_path(args.out_dir, args.unit, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(MPREMOTE), "mount", "micropython"]
    if args.level != "full":
        # Runs on the device BEFORE the wrapper; `settings` stays imported, so
        # the wrapper and main.py see the level without editing config.py.
        cmd += ["exec", f"import settings; settings.INTERACTION_LOG_LEVEL = {args.level!r}"]
    cmd += ["run", "micropython/interlog_run.py"]
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
    label_seq = 0
    standing = []          # ids of labels not yet undone, newest last
    recent = []            # (host time, description) of recent events
    last_event = "—"
    last_console = ""
    last_tagged = None
    warned_silent = False
    last_status = time.time()
    buf = b""

    print(f"● recording → {path}")
    print(f"  unit={args.unit} mount={args.mount}\n")
    print("  keys (right hand):")
    print("\n".join(legend_lines()))
    print("\n  ▶ = the bottle did something (label it)     · = information\n")

    with open(path, "w") as f:
        f.write(json.dumps(header_record(args.unit, args.mount,
                                         (args.note + f" [level={args.level}]").strip(),
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
                        t_now = time.time()
                        if ch in UNDO_KEYS:
                            if not standing:
                                print("  (nothing to undo)")
                                continue
                            target = standing.pop()
                            f.write(json.dumps(undo_record(target, t_now)) + "\n")
                            f.flush()
                            print(f"  ✖ undid label #{target} — press the right key")
                            continue
                        near = near_events(recent, t_now)
                        label_seq += 1
                        rec = label_record(ch, t_now, seq=label_seq, near=near)
                        if rec:
                            standing.append(label_seq)
                            f.write(json.dumps(rec) + "\n")
                            f.flush()
                            counts["l"] += 1
                            ctx = ", ".join(near[-3:]) if near else "nothing recent"
                            print(f"  ✎ #{label_seq} {rec['label']:<13} (near: {ctx})")
                        else:
                            label_seq -= 1
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
                                print(f"  {event_symbol(rec)} {describe_event(rec)}")
                                recent.append((time.time(), " ".join(describe_event(rec).split())))
                                del recent[:-20]
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
