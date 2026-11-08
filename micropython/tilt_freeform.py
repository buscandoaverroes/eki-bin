# micropython/tilt_freeform.py — eki-bin
#
# Tilt-to-adjust, the way it will actually be used: no target, no score,
# just "make it look about right" — the way anyone sets screen brightness.
# Nobody reaches for 0.45. They reach for *about there*, and what makes it
# good or bad is whether it went too fast, too slow, or the wrong way.
#
# So this measures nothing on the operator's behalf. It logs everything and
# asks one question afterwards: **how did that feel?**
#
# ⚠ WHY THIS IS NOT curve_test. A fixed target is a legitimate way to
# measure a control loop and a poor model of the task. It rewards precision
# the real user never needs and it hides the failures they will actually
# hit — overshoot, reversal confusion, a rate that feels wrong in the hand.
# The label you type at the end is the only place those live.
#
# ⚠ TELEMETRY IS LOGGED, NOT PRINTED. The loop samples at ~40Hz and the
# console printed 1 in 10 — so nine of every ten samples were being thrown
# away, and the one that survived scrolled past too fast to read. The file
# gets all of them; the console gets three words.
#
# Run (two steps — `input()` needs a REAL REPL, which `mpremote run` does
# not give you; same caveat vibration_sandbox.py documents):
#
#   make upload-file FILE=micropython/tilt_freeform.py   # → device :main.py
#   make screen                                           # then Ctrl-D
#   ...runs...   afterwards:  make upload                 # restore firmware
#
# Pull the log off with:  mpremote cp :tilt-freeform.jsonl .
# Clear device data files with:  make clear-vibes

import json
import time

import gestures
import leds
import settings
import tilt
from settings import NUM_LEDS

LOG_PATH = "tilt-freeform.jsonl"
POLL_MS = 25
FEEDBACK_COLOR = settings.STARTUP_COLOR

# Knobs to sweep between runs. Edit, run, label, repeat — the label is what
# turns a pile of samples into something you can compare later.
RUN_KNOBS = ("TILT_EXPO", "TILT_RATE_PER_SEC", "TILT_FULL_DEG",
             "TILT_DEADZONE_DEG", "TILT_STILL_MS")


def _snapshot():
    return {k: getattr(settings, k) for k in RUN_KNOBS}


def _render():
    """Whole ring at the current BRIGHTNESS — what a real display would do.

    No bar, no marker: freeform IS the glare test as well as the feel test,
    and a level readout would let you aim at a number instead of at a look."""
    leds._write_frame([(FEEDBACK_COLOR, 1.0)] * NUM_LEDS)


def run(label=None):
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU — nothing to tilt. Check wiring, `make i2c-scan`.")
        return

    knobs = _snapshot()
    print("\n== tilt_freeform ==")
    for k in RUN_KNOBS:
        print("   %-22s %s" % (k, knobs[k]))
    print("\n   Set it to whatever looks right. Ctrl+C when you're done,")
    print("   then say how it felt. Console shows state only — everything")
    print("   else is going to %s.\n" % LOG_PATH)

    ctl = tilt.TiltController()
    samples = []
    started = time.ticks_ms()
    last_ms = started
    last_err = started
    last_state = None

    try:
        while True:
            now = time.ticks_ms()
            dt = time.ticks_diff(now, last_ms)
            last_ms = now

            raw, last_err = gestures._safe_read_accel(i2c, addr, now, last_err)
            if raw is None:
                time.sleep_ms(POLL_MS)
                continue

            state = ctl.update(raw, now, dt)

            # EVERY sample, not every tenth — the whole point of logging
            # instead of printing.
            samples.append((time.ticks_diff(now, started), state,
                            round(ctl.deg, 2),
                            round(ctl.jitter, 3) if ctl.jitter is not None else None,
                            round(ctl.rate, 4),
                            round(settings.BRIGHTNESS, 4)))

            # Three words, and only on a CHANGE. A line per sample would be
            # the same wall of text this was written to get rid of.
            if state != last_state and state in ("up", "down", "idle", "released"):
                print("   %s" % {"up": "▲ up", "down": "▼ down",
                                 "idle": "· neutral",
                                 "released": "— set down, neutral re-learned"}[state])
                last_state = state

            _render()
            time.sleep_ms(POLL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()

    print("\n   %d samples over %.1fs, %d rejected by the magnitude gate."
          % (len(samples), time.ticks_diff(time.ticks_ms(), started) / 1000.0,
             ctl.rejected))
    if label is None:
        print("\n   How did that feel? (too fast / too slow / wrong way /")
        print("   fine / couldn't settle / anything at all)")
        try:
            label = input("   > ").strip()
        except (EOFError, OSError):
            label = ""

    with open(LOG_PATH, "a") as f:
        f.write(json.dumps({
            "ts": time.time(), "label": label, "knobs": knobs,
            "final_brightness": round(settings.BRIGHTNESS, 4),
            "rejected": ctl.rejected, "n": len(samples),
            "fields": ["ms", "state", "deg", "jitter", "rate", "brightness"],
            "samples": samples,
        }) + "\n")
    print("\n   ✓ appended to %s — change a knob and run again." % LOG_PATH)


if __name__ == "__main__":
    run()
