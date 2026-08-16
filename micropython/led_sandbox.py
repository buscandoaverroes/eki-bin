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
    # _clamp255 matters here now, not just belt-and-suspenders: jolt-style
    # scenes (see "Gesture jolt prototypes" below) push mult above 1.0 —
    # gamma(mult) for mult>1 is mult**GAMMA, e.g. gamma(2.0)≈4.6 at the
    # default GAMMA=2.2 — so color[ch]*level can clear 255 well before
    # BRIGHTNESS_PRESETS' top end (0.6). main._paint clamps for exactly
    # this reason; every prior scene here just never multiplied past 1.0
    # so it never came up.
    level = main.BRIGHTNESS * main.gamma(mult)
    for logical in range(start, end):
        phys = main._physical(logical)
        if main.DITHER:
            # _quantize clamps internally — same split main._paint uses.
            res = main._residual[phys]
            main.np[phys] = tuple(
                main._quantize(color[ch] * level, res, ch) for ch in range(3)
            )
        else:
            main.np[phys] = tuple(main._clamp255(color[ch] * level) for ch in range(3))


# ── Scenes ────────────────────────────────────────────────────────
# Each scene is a list of segments: (start, end, color, anim_fn_or_None).
#   anim_fn(phase_ms) -> mult, usually 0.0-1.0; None = static, full
#   brightness. The jolt prototypes below intentionally go above 1.0 —
#   see _write_segment's clamping.
# Adjust the boundaries/colours freely — this is meant to be edited a lot.

RED = (255, 0, 0)
YELLOW = (255, 200, 0)
LEVEL_2_COLOR = main.PALETTE[main.LEVEL_2]
STARTUP_COLOR = main.STARTUP_COLOR  # reuse the boot ceremony's colour language

# ── Gesture jolt prototypes — gesture-envelope.md §11 ───────────────
# The two-phase ACK/CONFIRM response has no LED rendering yet (only
# terminal prints, via gesture_sandbox.py's run_v1()) — this is where that
# gets designed, before it's wired into main.py's real loop. The "double
# hill" idea from real-hardware testing: an instant, tiny ACK the moment
# a tap is felt (no verdict yet — the recognizer hasn't run), then a
# bigger CONFIRM jolt once the ~1.2s capture window resolves. Two humps,
# deliberately different in character so they don't blur into one event.
#
# anim_fn(phase_ms) here is a ONE-SHOT shape over elapsed time since the
# scene started, not a period — it settles to 0 and stays there once the
# sequence ends (real content would take over at that point; here it's
# just black). run() still works fine with that — Ctrl+C or seconds=N to
# stop watching once you've seen it play out.
#
# All timings pulled from main's real config knobs (ACK_FLASH_MS,
# main._GESTURE_WINDOW_MS, WAKE_JOLT_MS, WAKE_JOLT_BRIGHTNESS_MULT) so
# this plays at the ACTUAL production budget, not a guessed one.
#
# Real-hardware feedback on the first live version (gesture_sandbox.py,
# 2026-08-16): dropping ACK straight to black made it and CONFIRM read as
# two disconnected blips with a stall in between, not one gesture. Fix:
# ACK now settles onto a "continental shelf" — a dim but non-zero held
# brightness — instead of 0, and CONFIRM rises FROM that shelf instead of
# from black. Both the ACK peak and the shelf level also scale with tap
# strength in the real (tap-triggered) version; there's no real strength
# signal in this scripted preview, so PREVIEW_STRENGTH below stands in
# for "a medium tap."
#
# ⚠ This preview's shelf will visibly dither, unlike the real thing: run()
# redraws every scene continuously via the animated (gamma+dither)
# _write_segment, every 30ms, for as long as the scene plays — fine for
# every other scene here (all genuinely animated throughout), but a
# HELD value redrawn repeatedly through the dithered path is exactly the
# flicker failure mode _play_startup_burst's docstring warns about.
# gesture_sandbox.py's real integration avoids this by writing the shelf
# via a separate static (no gamma, no dither) path exactly ONCE, then
# leaving it alone — see that file's _write_segment_static. Reproducing
# that here would mean teaching run()'s generic redraw loop about static
# holds, which every other scene doesn't need — not worth it for a shape/
# timing preview. Judge the SHAPE and TIMING here; judge the actual
# flicker-free feel on the real jar.
PREVIEW_STRENGTH = 0.5  # stand-in for "a medium tap" — see gesture_sandbox.py's _tap_strength
ACK_PEAK_FLOOR = 0.5
ACK_PEAK_CEIL = 1.0
SHELF_FLOOR = 0.08
SHELF_CEIL = 0.25
PREVIEW_PEAK_MULT = ACK_PEAK_FLOOR + PREVIEW_STRENGTH * (ACK_PEAK_CEIL - ACK_PEAK_FLOOR)
PREVIEW_SHELF_MULT = SHELF_FLOOR + PREVIEW_STRENGTH * (SHELF_CEIL - SHELF_FLOOR)


def ack_flash(phase_ms, peak_mult=1.0, shelf_mult=0.0, ack_ms=main.ACK_FLASH_MS):
    """Candidate A: bare on/off — "felt contact," no verdict yet. Jumps to
    peak_mult, holds, then drops to shelf_mult (not necessarily 0)."""
    return peak_mult if phase_ms < ack_ms else shelf_mult


def ack_flick(phase_ms, peak_mult=1.0, shelf_mult=0.0, ack_ms=main.ACK_FLASH_MS * 3):
    """Candidate B: a quick rise-then-dip instead of a flat flash — the
    "flick, down or up" idea, so ACK has its own shape distinct from
    CONFIRM's rise/decay even at a glance. Dips to shelf_mult, not
    necessarily 0 — see the "continental shelf" note above. 3x
    ACK_FLASH_MS because a flash that's ALSO a triangle needs a bit more
    than 50ms to read as a shape rather than a blip."""
    half = ack_ms / 2
    if phase_ms < half:
        return (phase_ms / half) * peak_mult
    if phase_ms < ack_ms:
        frac = (phase_ms - half) / half
        return peak_mult + (shelf_mult - peak_mult) * frac
    return shelf_mult


def confirm_jolt(phase_ms, total_ms=main.WAKE_JOLT_MS, peak_mult=main.WAKE_JOLT_BRIGHTNESS_MULT, start_mult=0.0):
    """The CONFIRM jolt: same linear rise/decay shape as _play_startup_burst
    (_startup_burst_mult) — quick bright rise, slower decay — but scaled to
    fit WAKE_JOLT_MS's real 500ms budget instead of the boot ceremony's
    2300ms (STARTUP_BURST_MS+STARTUP_FADE_MS), and peaking at
    WAKE_JOLT_BRIGHTNESS_MULT instead of 1.0 so it reads as brighter than
    steady-state, not just another breathe cycle. Same rise:decay ratio as
    the boot burst (800:1500 ≈ event feels sudden, recovery feels calmer).
    Rises from start_mult (the shelf, not necessarily 0) and decays all
    the way to 0 — the shelf said "still deciding," decaying past it to
    black says "decided, done." mult>1.0 during the rise/peak is expected
    and intentional — see _write_segment's clamping above."""
    rise_ms = total_ms * (main.STARTUP_BURST_MS / (main.STARTUP_BURST_MS + main.STARTUP_FADE_MS))
    decay_ms = total_ms - rise_ms
    if phase_ms < rise_ms:
        return start_mult + (phase_ms / rise_ms) * (peak_mult - start_mult)
    decay_elapsed = phase_ms - rise_ms
    if decay_elapsed >= decay_ms:
        return 0.0
    return peak_mult * (1.0 - decay_elapsed / decay_ms)


def double_hill(phase_ms, ack_fn=ack_flick, gap_ms=main._GESTURE_WINDOW_MS,
                 peak_mult=PREVIEW_PEAK_MULT, shelf_mult=PREVIEW_SHELF_MULT):
    """The full ACK -> (silent capture window, now bridged by the shelf) ->
    CONFIRM sequence. gap_ms defaults to the REAL capture window
    (main._GESTURE_WINDOW_MS, 1200ms) deliberately — that gap isn't a
    rendering choice, it's however long the recognizer actually takes to
    decide, so the prototype should feel exactly as long as production
    will."""
    if phase_ms < gap_ms:
        return ack_fn(phase_ms, peak_mult=peak_mult, shelf_mult=shelf_mult)
    return confirm_jolt(phase_ms - gap_ms, start_mult=shelf_mult)


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
    # gesture-envelope.md §11's open question: does an instant flat flash
    # or a quick rise-then-dip "flick" read better as the ACK? Left/right
    # both feed into the SAME confirm_jolt afterward — only the ACK shape
    # differs, so the comparison isolates that one variable.
    "jolt_ack_flash_vs_flick": [
        (0, main.NUM_LEDS // 2, STARTUP_COLOR, lambda ms: double_hill(ms, ack_fn=ack_flash)),
        (main.NUM_LEDS // 2, main.NUM_LEDS, STARTUP_COLOR, lambda ms: double_hill(ms, ack_fn=ack_flick)),
    ],
    # Whole-strip run of the full sequence — for feeling the overall
    # TIMING (is the ~1.2s gap too long, is the jolt itself still "too
    # slow" the way the boot burst was flagged) rather than comparing ACK
    # shapes side by side.
    "jolt_double_hill_full": [
        (0, main.NUM_LEDS, STARTUP_COLOR, lambda ms: double_hill(ms)),
    ],
}

ACTIVE_SCENE = "jolt_double_hill_full"  # ← change this to try another


def run(scene_name=ACTIVE_SCENE, seconds=None):
    """Run a scene. `seconds=None` runs until Ctrl+C; otherwise stops after."""
    segments = SCENES[scene_name]
    print(f"\n== led_sandbox: {scene_name!r} ==")
    for s, e, color, anim in segments:
        print(f"  [{s}:{e})  color={color}  animated={anim is not None}")
    print("  Ctrl+C to stop\n")

    start = time.ticks_ms()
    try:
        while True:
            elapsed = time.ticks_diff(time.ticks_ms(), start)
            if seconds is not None and elapsed >= seconds * 1000:
                break
            for s, e, color, anim in segments:
                mult = anim(elapsed) if anim else 1.0
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
