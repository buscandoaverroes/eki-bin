# micropython/led_sandbox.py
# Quick side-by-side comparisons of colour/animation treatments — e.g. "does a
# hue-shifted second train read better than a dimmed one?" (see
# docs/insights.md §6) — without waiting on WiFi/schedule/the full main.py loop.
#
# `import main` pulls in main.py's REAL primitives (PALETTE, gamma, dithering,
# breathe, hue_rotate, ...) without starting the WiFi/NTP loop — main.py's own
# `if __name__ == "__main__": main()` guard only fires when main.py itself is
# the entry point, not when it's imported as a module. So whatever looks good
# here renders with the exact same math the real contracts use, and it uses
# the real `np` (built from config.py's LED_PIN) — no separate hardcoded pin
# to keep in sync, unlike led_test.py.
#
# Edit SCENES below (or add your own), then:  mpremote run micropython/led_sandbox.py
#
# ⚠ `import main` resolves against whatever main.py is CURRENTLY ON THE DEVICE
# (from the last `make upload`), not your local repo copy — `mpremote run` only
# transfers this one script. If main.py's primitives changed since your last
# upload, `make upload` first, or you'll get an AttributeError (e.g. a new
# helper like hue_rotate not existing yet on-device) — or worse, silently test
# against stale logic if the change wasn't additive.

import time

import main

# ── Segment painter ──────────────────────────────────────────────
# Bypasses the arc/_paint_layers abstraction on purpose — a sandbox scene
# isn't driven by a LeaveSignal, it's an arbitrary set of LED ranges you're
# comparing directly. Goes through the same gamma/dither/_physical pipeline
# _paint_layers does, so brightness reads exactly like it would for real.


def _write_segment(start, end, color, mult=1.0):
    level = main.BRIGHTNESS * main.gamma(mult)
    for logical in range(start, end):
        phys = main._physical(logical)
        if main.DITHER:
            res = main._residual[phys]
            main.np[phys] = tuple(
                main._quantize(color[ch] * level, res, ch) for ch in range(3)
            )
        else:
            main.np[phys] = tuple(int(color[ch] * level) for ch in range(3))


# ── Scenes ────────────────────────────────────────────────────────
# Each scene is a list of segments: (start, end, color, anim_fn_or_None).
#   anim_fn(phase_ms) -> mult (0.0-1.0); None = static, full brightness.
# Adjust the boundaries/colours freely — this is meant to be edited a lot.

RED = (255, 0, 0)
YELLOW = (255, 200, 0)
LEVEL_2_COLOR = main.PALETTE[main.LEVEL_2]

SCENES = {
    # Your literal example: half static red, half breathing yellow.
    # Longer period = more floor/static contrast at any glance (found: too
    # short and a breath peak can read as "primary, fully lit" by mistake).
    "half_static_half_breathe": [
        (0, main.NUM_LEDS // 2, RED, None),
        (main.NUM_LEDS // 2, main.NUM_LEDS, YELLOW, lambda ms: main.breathe(ms, 6000, 0.35)),
    ],
    # Colour-shift comparison: same urgency colour vs. a hue-rotated variant,
    # both at full brightness — the candidate fix for insights.md §6.
    "hue_shift_demo": [
        (0, main.NUM_LEDS // 2, LEVEL_2_COLOR, None),
        (main.NUM_LEDS // 2, main.NUM_LEDS, main.hue_rotate(LEVEL_2_COLOR, 20), None),
    ],
    # Same idea, but the "second train" band also breathes — animation-style
    # differentiation instead of (or combined with) colour.
    "hue_shift_plus_breathe": [
        (0, main.NUM_LEDS // 2, LEVEL_2_COLOR, None),
        (
            main.NUM_LEDS // 2, main.NUM_LEDS, main.hue_rotate(LEVEL_2_COLOR, 20),
            lambda ms: main.breathe(ms, 4000, 0.6),
        ),
    ],
    # Two different breathing curves side by side, same period — compares the
    # SHAPE of the envelope (exponential build vs. plain sine), not the speed.
    "two_breathing_patterns": [
        (0, main.NUM_LEDS // 2, RED, lambda ms: main.breathe(ms, 4000, 0.6, ceiling=0.9)),
        (main.NUM_LEDS // 2, main.NUM_LEDS, YELLOW, lambda ms: main.breathe(ms, 6000, 0.6)),
    ],
    "hue_shift_plus_two_breathing_patterns": [
        (0, main.NUM_LEDS // 2, LEVEL_2_COLOR, lambda ms: main.breathe(ms, 3000, 0.6)),
        (main.NUM_LEDS // 2, main.NUM_LEDS, main.hue_rotate(LEVEL_2_COLOR, 20), lambda ms: main.breathe(ms, 4000, 0.6, 0.9)),
    ],
    "hue_shift_plus_one_breathing_patterns": [
        (0, main.NUM_LEDS // 2, LEVEL_2_COLOR, None),
        (main.NUM_LEDS // 2, main.NUM_LEDS, main.hue_rotate(LEVEL_2_COLOR, 20), lambda ms: main.breathe(ms, 3000, 0.7)),
    ],
}

ACTIVE_SCENE = "hue_shift_plus_one_breathing_patterns"  # ← change this to try another


def run(scene_name=ACTIVE_SCENE, seconds=None):
    """Run a scene. `seconds=None` runs until Ctrl+C; otherwise stops after."""
    segments = SCENES[scene_name]
    print(f"\n== led_sandbox: {scene_name!r} ==")
    for s, e, color, anim in segments:
        print(f"  [{s}:{e})  color={color}  animated={anim is not None}")
    print("  Ctrl+C to stop\n")

    start = time.ticks_ms()
    try:
        while seconds is None or time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
            now = time.ticks_ms()
            for s, e, color, anim in segments:
                mult = anim(now) if anim else 1.0
                _write_segment(s, e, color, mult)
            main.np.write()
            time.sleep_ms(30)
    except KeyboardInterrupt:
        pass
    finally:
        main.clear()
        print("  cleared — bye")


if __name__ == "__main__":
    run()
