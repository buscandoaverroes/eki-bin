# micropython/gesture_sandbox.py — eki-bin live gesture model sandbox
# `import main` pulls in main.py's REAL HAL + recognizer + scrollwheel
# primitives (_imu_read_accel_raw, extract_gesture_features,
# classify_tap_or_flick, classify_position, _GestureMenu, _TapCycleState,
# ...) without starting the real loop — same pattern led_sandbox.py already
# established for the LED side ("import main resolves against whatever
# main.py is CURRENTLY ON THE DEVICE, not your local repo copy — see that
# file's header for the full caveat, it applies here identically").
#
# Two modes, set MODE below: "full" exercises the richer tap/flick/
# position/scrollwheel machinery (§4-10 of gesture-envelope.md); "v1"
# exercises the minimal tap-or-noise + two-phase ACK/CONFIRM contract
# (§11) that's actually shipping first. Both are real, tested main.py code
# — this script never re-derives recognizer or state-machine logic, only
# the trigger/capture timing around it.
#
# Why this exists, not just more iteration inside main.py's
# _run_gesture_debug_loop: real-hardware testing found that loop's trigger
# polls at FRAME_MS (16ms, borrowed from the LED render tick this loop
# never actually uses) instead of the ~4ms/240Hz the sandbox's validated
# 95-98% recognizer numbers were measured at — a real cause of missed taps,
# not a hardware limit. Tuning that kind of thing by repeatedly editing
# main.py risks reintroducing bugs into code that's supposed to be stable
# (see: the dropped `return samples` bug from the last round). This script
# is where the TRIGGER/CAPTURE timing gets tuned; main.py's recognizer
# logic (extract_gesture_features, classify_tap_or_flick, ...) is reused
# as-is, unchanged, exactly what should NOT be re-derived here.
#
# Every capture prints the full feature dict, not just the final
# tap/flick/None call — that's the "other model data" this exists to show:
# WHY a classification happened, not just what it was.
#
# run_v1() also drives the real LED stick now — gesture-envelope.md §11's
# jolt, live off a real tap instead of a scripted timer. The shape
# functions (_write_segment, ack_flick, confirm_jolt) are DUPLICATED from
# led_sandbox.py, not imported — `mpremote run` only transfers the one
# script named on the command line (see the module-level caveat below),
# and neither sandbox script is part of `make upload`'s payload, so
# `import led_sandbox` would fail on-device with no led_sandbox.py there
# to find. led_sandbox.py stays the place to compare candidate shapes
# side by side (e.g. jolt_ack_flash_vs_flick); this file is where the
# chosen shape gets tested against a real tap, on the real jar.
#
# ⚠ Same input()-needs-a-real-REPL caveat as vibration_sandbox.py — no
# input() here though (no human arming needed, the trigger runs on its
# own), so plain `mpremote run` / `make run-file` works fine.
#
# Run:  make run-file FILE=micropython/gesture_sandbox.py
#       (requires main.py already on-device via a prior `make upload` —
#       import main picks up whatever's there, including config.py's
#       threshold values)

import time

import main

MODE = "v1"  # "full" | "v1" — see header

# ── Trigger tuning — LOCAL to this sandbox, not main.py ────────────
# Faster than main.py's _run_gesture_debug_loop (FRAME_MS=16ms) — matches
# the sandbox tools' proven 240Hz/4ms cadence instead. Edit freely; this is
# exactly the kind of thing to validate here before (if ever) porting a
# fix back into main.py's debug loop.
TRIGGER_INTERVAL_MS = 4
TRIGGER_BUFFER_LEN = 20  # ~80ms of rolling local-baseline context at 4ms

# Quick threshold overrides for THIS session, without touching config.py —
# edit and re-run, no re-upload needed. Applied to the imported `main`
# module's globals below. Leave empty to use whatever's already in
# config.py on-device.
THRESHOLD_OVERRIDES = {
    # "TAP_TRIGGER_THRESHOLD_MG": 30,
    "FLICK_MAGNITUDE_THRESHOLD_MG": 328,
    # "FLICK_SPACING_STDEV_THRESHOLD_MS": 20,
}
for _name, _value in THRESHOLD_OVERRIDES.items():
    setattr(main, _name, _value)


# ── I2C resilience ────────────────────────────────────────────────
# A jumper wire jostled by the very tap/grab being measured can cause a
# transient I2C failure (OSError EIO) — vibration_sandbox.py hit this
# first ("check the sensor's wiring — likely a connection shaken loose by
# tapping") and retries interactively there. This script can't do the
# same interactive retry — it's deliberately autonomous, no input(), and
# mpremote run doesn't forward keystrokes anyway (see the module header).
# So: catch it, skip that one sample, keep the loop alive. Diagnostic is
# throttled to ~1/sec — a genuinely bad (not just momentarily jostled)
# connection would otherwise flood the terminal with one error per 4ms
# trigger tick.
I2C_ERROR_PRINT_INTERVAL_MS = 1000


def _safe_read_accel(i2c, addr, now_ms, last_error_print):
    """Returns (raw_xyz_or_None, updated last_error_print). Caller skips
    the sample on None instead of crashing the whole run."""
    try:
        return main._imu_read_accel_raw(i2c, addr), last_error_print
    except OSError as e:
        if now_ms - last_error_print >= I2C_ERROR_PRINT_INTERVAL_MS:
            print(f"  ⚠ I2C read failed ({e}) — likely a connection jostled by the tap/grab itself, same finding as vibration_sandbox.py. Check the IMU's wiring if this repeats. Skipping this sample.")
            last_error_print = now_ms
        return None, last_error_print


# A single dropped sample above gets no LED treatment — that's the whole
# point of skip-and-continue, it's meant to be a non-event. But
# docs/contracts/led-status-messages.md already committed to "errors are
# persistent and unambiguous... a broken device should look broken, not
# almost-normal," and "different failure causes get visually distinct
# colours" — a brief flash for a momentary blip would read as "almost
# normal" (working against that principle), and reusing ERROR_COLOR or
# SCHEDULE_ERROR_COLOR would collide with two DIFFERENT existing failure
# meanings. So: only a SUSTAINED failure — no successful read for
# SENSOR_ERROR_TIMEOUT_MS — escalates to that same persistent-breathe
# pattern, with its own distinct SENSOR_ERROR_COLOR. Unlike the
# production pattern ("forever, needs reset"), this sandbox's version
# clears itself once reads succeed again: deliberately, since this is a
# dev tool testing a failure mode (a wire) that's likely to self-heal,
# not a WiFi/schedule failure that genuinely won't fix itself.
SENSOR_ERROR_TIMEOUT_MS = 1000
SENSOR_ERROR_COLOR = (0, 180, 200)  # cyan — distinct from ERROR_COLOR (red)
#                       and SCHEDULE_ERROR_COLOR (magenta); a different
#                       failure cause should look like a different failure


# ── LED rendering — see led_sandbox.py for the design/comparison work ──
# Same _write_segment as led_sandbox.py (bypasses the arc abstraction,
# still goes through the real gamma/dither/_physical pipeline). mult can
# exceed 1.0 here (the CONFIRM jolt peaks at WAKE_JOLT_BRIGHTNESS_MULT) —
# see led_sandbox.py's _write_segment for why the clamping matters.
LED_RENDER_INTERVAL_MS = 16  # throttle LED writes independent of the 4ms
#                              sample rate — matches main.py's FRAME_MS,
#                              no reason to write() faster than a frame


def _write_segment(start, end, color, mult=1.0, use_gamma=True):
    """For a CHANGING value (rise/decay) — dithered, and gamma-corrected
    unless use_gamma=False. Do not use this for a held/static value; see
    _write_segment_static below for why.

    use_gamma=False matters for a range that stays mostly BELOW roughly
    0.3 (at GAMMA=2.2): gamma(mult) there is much smaller than mult
    itself, so it renders visibly dimmer than the SAME mult rendered
    through the linear static path. Real-hardware finding: ack_flick's
    whole range (peak 0.5-1.0, dipping to the shelf's 0.08-0.25) sits
    right in that zone, so its gamma-corrected descent visibly hit black
    well before reaching the shelf's own (linear) brightness, then jumped
    back up once the static shelf write took over — a real bug ("dive
    underground to 0, then back up to a plateau"), not a feel preference.
    Genuinely high-range content (confirm_jolt, cycle_flash) stays
    gamma-corrected as normal — that range doesn't hit this problem, and
    losing gamma's extra emphasis at the bright end (gamma(2.0)≈4.6 vs a
    linear 2.0) would blunt the jolt's whole "brighter than normal" point."""
    level = main.BRIGHTNESS * (main.gamma(mult) if use_gamma else mult)
    for logical in range(start, end):
        phys = main._physical(logical)
        if main.DITHER:
            res = main._residual[phys]
            main.np[phys] = tuple(
                main._quantize(color[ch] * level, res, ch) for ch in range(3)
            )
        else:
            main.np[phys] = tuple(main._clamp255(color[ch] * level) for ch in range(3))


def _write_segment_static(start, end, color, mult):
    """For a HELD value — the "continental shelf" between ACK and CONFIRM.
    No gamma, no dither: same fix main.py's MARKER_BRIGHTNESS already
    uses for the approach contract's idle ticks (see that comment). Two
    separate reasons, not one: dithering flickers on a value that ISN'T
    changing (nothing for the quantization noise to average against —
    _play_startup_burst's docstring), and gamma pushes a low mult toward
    invisible (gamma(0.15)≈0.014 at GAMMA=2.2) — exactly wrong for a
    shelf whose entire point is staying visibly non-zero. Call this ONCE
    per shelf, not every frame — nothing here needs re-rendering while
    the value isn't moving."""
    level = main.BRIGHTNESS * mult
    for logical in range(start, end):
        phys = main._physical(logical)
        main.np[phys] = tuple(main._clamp255(color[ch] * level) for ch in range(3))


# ── Tap-strength → brightness — "hardware-defined software" ─────────
# A harder tap reads brighter, both on the ACK's peak (the "up") and on
# the shelf it settles onto (the "down") — real-hardware testing found a
# fixed-brightness response regardless of tap strength wastes a signal
# that's sitting right there. Only `dev` (this trigger sample's deviation
# from baseline) is available this early — `energy`, the recognizer's
# real signal, isn't known until the capture window closes ~1.2s later.
#
# Round 1 (bare LED strip, out of the bottle): 0.5-1.0 (2x) wasn't
# differentiable even at the strength extremes; widened to 0.4-1.6 (4x),
# and that read as clearly distinguishable — but ONLY tested bare.
#
# Round 2 (2026-08-16, first IN-BOTTLE test — this is the real target,
# 駅瓶's whole premise is frosted glass, not a bare strip): the SAME
# 0.4-1.6 range that worked bare was only "subtly different" through the
# glass — a frosted diffuser compresses brightness contrast, so a range
# tuned bare will always under-deliver once the glass is on. Widened
# again, pushed mostly on the ceiling (not the floor — floor is already
# close to SHELF_CEIL=0.25 and eating that margin risks shelf/ACK
# ambiguity; ceiling has more room before it'd rival CONFIRM's
# gamma-amplified peak). Expect this may need a further round once
# retested in-bottle — there's no way to predict how much a frosted
# diffuser compresses contrast without just measuring it.
#
# STRENGTH_MAX_DEV_MG nudged 400→460: observed real dev crept from 444mg
# to 461mg between rounds, both clamping to strength=1.0 — a slightly
# higher ceiling keeps "hard" taps from all reading identically.
STRENGTH_MIN_DEV_MG = main.TAP_TRIGGER_THRESHOLD_MG  # at/below this → floor
STRENGTH_MAX_DEV_MG = 460
ACK_PEAK_FLOOR = 0.35  # lightest-tap ACK brightness
ACK_PEAK_CEIL = 2.2    # hardest-tap ACK brightness — >1.0 is fine, same
#                        "brighter than normal" precedent WAKE_JOLT_BRIGHTNESS_MULT
#                        already sets, and ack_flick renders without gamma
#                        (use_gamma=False) so this is a real linear multiplier,
#                        not further amplified the way confirm_jolt's peak is
SHELF_FLOOR = 0.08     # lightest-tap shelf — dim, not dark
SHELF_CEIL = 0.25      # hardest-tap shelf — stays below ACK_PEAK_FLOOR (0.35)
#                        with a real (if narrower than before) margin, so
#                        shelf never blurs into ACK

# Real-hardware feedback (2026-08-16): at the old ack_ms (main.ACK_FLASH_MS
# * 3 = 150ms out of the ~1200ms window), the rise-to-peak happened too
# fast to actually SEE a strength difference — 150ms isn't enough time to
# track "how high did it climb" before it's already dipping to the shelf.
# ACK_HOLD_MS widens that ratio; still well under half the window, so the
# shelf (the "still deciding" cue) keeps the larger share. LOCAL to this
# sandbox, not main.py's ACK_FLASH_MS (that's a different, smaller
# "instant acknowledgment" concept) — tune freely, no re-upload needed.
ACK_HOLD_MS = 400


def _tap_strength(dev_mg):
    """0..1, how hard the triggering tap read at the moment of contact.
    Clamped, linear."""
    span = STRENGTH_MAX_DEV_MG - STRENGTH_MIN_DEV_MG
    if span <= 0:
        return 1.0
    t = (dev_mg - STRENGTH_MIN_DEV_MG) / span
    return max(0.0, min(1.0, t))


def ack_flash(phase_ms, peak_mult=1.0, shelf_mult=0.0, ack_ms=ACK_HOLD_MS):
    """Candidate A: bare on/off — jumps to peak_mult, holds; the caller's
    static shelf write takes over once ack_ms elapses. See led_sandbox.py
    for the A/B against ack_flick."""
    return peak_mult if phase_ms < ack_ms else shelf_mult


def ack_flick(phase_ms, peak_mult=1.0, shelf_mult=0.0, ack_ms=ACK_HOLD_MS):
    """Candidate B (current default, ACK_FN below): rises to peak_mult,
    dips to shelf_mult — NOT necessarily 0 (the "continental shelf": a
    real but hard, real-hardware test found dropping straight to black
    made the ACK and CONFIRM read as two disconnected blips with a stall
    in between rather than one continuous gesture). The caller is
    responsible for holding shelf_mult statically once ack_ms elapses —
    see _capture_window."""
    half = ack_ms / 2
    if phase_ms < half:
        return (phase_ms / half) * peak_mult
    if phase_ms < ack_ms:
        frac = (phase_ms - half) / half
        return peak_mult + (shelf_mult - peak_mult) * frac
    return shelf_mult


def confirm_jolt(phase_ms, total_ms=main.WAKE_JOLT_MS, peak_mult=main.WAKE_JOLT_BRIGHTNESS_MULT, start_mult=0.0):
    """WAKE's response: rises from start_mult (continuing from wherever
    the shelf left off, not necessarily 0) to peak_mult, then decays all
    the way to 0 — the shelf's job was "still here, deciding"; decaying
    past it to black says "decided, done." Same rise:decay ratio as
    _play_startup_burst, scaled to WAKE_JOLT_MS's 500ms budget. See
    led_sandbox.py's confirm_jolt for the full rise/decay rationale.

    NOTE: this rises from start_mult through the SAME gamma-corrected
    path ack_flick's descent used to hit the "dive to black" bug on —
    unconfirmed whether it's actually noticeable here (this rise is much
    faster, ~174ms total, vs. the ack's ~200ms fall), and unlike
    ack_flick this range genuinely wants gamma at its high end
    (WAKE_JOLT_BRIGHTNESS_MULT's whole "brighter than normal" point), so
    not fixed pre-emptively. Watch for a brief dip right as CONFIRM
    starts; if it's there, a targeted fix (not a blanket use_gamma=False)
    would be needed."""
    rise_ms = total_ms * (main.STARTUP_BURST_MS / (main.STARTUP_BURST_MS + main.STARTUP_FADE_MS))
    decay_ms = total_ms - rise_ms
    if phase_ms < rise_ms:
        return start_mult + (phase_ms / rise_ms) * (peak_mult - start_mult)
    decay_elapsed = phase_ms - rise_ms
    if decay_elapsed >= decay_ms:
        return 0.0
    return peak_mult * (1.0 - decay_elapsed / decay_ms)


def cycle_flash(phase_ms, total_ms=main.CYCLE_TRANSITION_MS):
    """CYCLE's response: a quick flash + hard cut, not WAKE's fuller jolt —
    deliberately simpler, gesture-envelope.md §11's AWAKE→CYCLE decision
    (no crossfade, same reasoning as CHASE's transition redesign). Doesn't
    bother continuing from the shelf the way confirm_jolt does — CYCLE is
    meant to feel more abrupt, a plain jump reads that way regardless of
    where it starts from."""
    return 1.0 if phase_ms < total_ms else 0.0


ACK_FN = ack_flick  # swap to ack_flash to compare live, no re-upload needed


def _render_confirm_jolt(shelf_mult=0.0):
    """Blocking, ~WAKE_JOLT_MS — same accepted-tradeoff category as the
    capture window itself. By the time this returns, real wall-clock time
    has passed matching the "waking" phase duration, so the main loop's
    next state.advance() call naturally finds it already elapsed — no
    separate timer needed to keep the render and the state machine in
    sync."""
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= main.WAKE_JOLT_MS:
            break
        mult = confirm_jolt(elapsed, start_mult=shelf_mult)
        _write_segment(0, main.NUM_LEDS, main.STARTUP_COLOR, mult)
        main.np.write()
        time.sleep_ms(LED_RENDER_INTERVAL_MS)
    main.clear()


def _render_cycle_flash():
    """Blocking, ~CYCLE_TRANSITION_MS — see cycle_flash above."""
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= main.CYCLE_TRANSITION_MS:
            break
        _write_segment(0, main.NUM_LEDS, main.STARTUP_COLOR, cycle_flash(elapsed))
        main.np.write()
        time.sleep_ms(LED_RENDER_INTERVAL_MS)
    main.clear()


def _capture_window(i2c, addr, start_ms, ack_fn=None, ack_ms=0, shelf_mult=0.0):
    """Local, tunable capture loop — deliberately NOT main._capture_gesture_
    window, so its timing can be experimented with independently. Still
    calls main._imu_read_accel_raw (the real HAL), never re-derives the
    I2C register logic itself.

    ack_fn, if given, renders live during the capture window instead of
    after it — the ACK has to happen here, this is the only code running
    while the real recognizer hasn't decided anything yet. The rise/dip
    (0..ack_ms) is animated (throttled to LED_RENDER_INTERVAL_MS,
    independent of the 4ms sample rate the recognizer's accuracy numbers
    were measured at); once it settles, the shelf is written exactly ONCE
    via the static path and left alone for the rest of the window — see
    _write_segment_static for why re-writing a static value every frame
    is exactly the flicker failure mode to avoid.

    A dropped sample (see _safe_read_accel) just means one fewer of the
    ~300 samples a full window normally collects — negligible for feature
    extraction, so the capture keeps running rather than aborting."""
    samples = []
    last_render = start_ms
    last_error_print = start_ms
    shelf_written = False
    while True:
        now = time.ticks_ms()
        elapsed = now - start_ms
        raw, last_error_print = _safe_read_accel(i2c, addr, now, last_error_print)
        if raw is not None:
            samples.append((elapsed,) + raw)
        if ack_fn is not None:
            if elapsed < ack_ms:
                if now - last_render >= LED_RENDER_INTERVAL_MS:
                    _write_segment(0, main.NUM_LEDS, main.STARTUP_COLOR, ack_fn(elapsed), use_gamma=False)
                    main.np.write()
                    last_render = now
            elif not shelf_written:
                _write_segment_static(0, main.NUM_LEDS, main.STARTUP_COLOR, shelf_mult)
                main.np.write()
                shelf_written = True
        if elapsed >= main._GESTURE_WINDOW_MS:
            break
        time.sleep_ms(TRIGGER_INTERVAL_MS)
    return samples


def _fmt(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def run_full():
    """Exercises classify_tap_or_flick/classify_position/_GestureMenu —
    the richer scrollwheel machinery, §4-10 of gesture-envelope.md."""
    i2c, addr = main._get_imu()
    if addr is None:
        print("  ✗ No LSM6DSV16X found — run imu_test.py first to debug wiring")
        return

    print("\n══ eki-bin gesture model sandbox (full) ══════════════")
    print(f"  IMU confirmed at {hex(addr)}")
    print(
        f"  thresholds: trigger={main.TAP_TRIGGER_THRESHOLD_MG}mg"
        f"  flick={main.FLICK_MAGNITUDE_THRESHOLD_MG}mg"
        f"  flick_spacing={main.FLICK_SPACING_STDEV_THRESHOLD_MS}ms"
        f"  position={main.POSITION_THRESHOLD_MG}mg"
    )
    print(f"  trigger poll: {TRIGGER_INTERVAL_MS}ms  (vs. main.py's debug loop: FRAME_MS={main.FRAME_MS}ms)")
    print("  gesture anytime — Ctrl+C to stop\n")

    menu = main._GestureMenu(main.GESTURE_MENU_OPTIONS)
    trigger_buffer = []
    last_heartbeat = time.ticks_ms()
    last_error_print = time.ticks_ms()

    try:
        while True:
            now_ms = time.ticks_ms()
            raw, last_error_print = _safe_read_accel(i2c, addr, now_ms, last_error_print)
            if raw is None:
                time.sleep_ms(TRIGGER_INTERVAL_MS)
                continue
            sample = (now_ms,) + raw
            mag = main._gesture_magnitude_mg(sample)

            triggered = False
            baseline = None
            if len(trigger_buffer) >= TRIGGER_BUFFER_LEN:
                baseline = main._gesture_median(trigger_buffer)
                triggered = abs(mag - baseline) >= main.TAP_TRIGGER_THRESHOLD_MG

            trigger_buffer.append(mag)
            if len(trigger_buffer) > TRIGGER_BUFFER_LEN:
                trigger_buffer.pop(0)

            # Periodic heartbeat so a tap that DOESN'T trigger is visible
            # too — the whole point of "other model data," not just
            # successful captures. Throttled to ~1/sec, not every tick.
            if baseline is not None and now_ms - last_heartbeat >= 1000:
                print(f"  … mag={mag:.0f}mg  baseline={baseline:.0f}mg  dev={abs(mag - baseline):.0f}mg")
                last_heartbeat = now_ms

            if triggered:
                samples = _capture_window(i2c, addr, now_ms)
                trigger_buffer = []
                features = main.extract_gesture_features(samples)
                physical = main.classify_tap_or_flick(features)
                position = main.classify_position(features) if physical is not None else None

                print("\n  ── capture ──")
                print(
                    f"    peak={_fmt(features['peak_deviation_mg'])}mg"
                    f"  energy={_fmt(features['energy'])}"
                    f"  crossings={features['num_crossings']}"
                    f"  ring_down={_fmt(features['ring_down_ms'], 0)}ms"
                )
                print(
                    f"    spacing_mean={_fmt(features['spacing_mean_ms'])}ms"
                    f"  spacing_stdev={_fmt(features['spacing_stdev_ms'])}ms"
                    f"  axis={features['dominant_axis']}"
                )
                tag = f"→ {physical}" if physical is not None else "→ rejected as noise"
                if position is not None:
                    tag += f"  position={position}"
                print(f"    {tag}")

                if physical is not None:
                    response = main._classify_menu_response(menu.active, physical)
                    now_ms = time.ticks_ms()  # stale after the blocking capture
                    if response == "wake":
                        menu.wake(now_ms)
                        print(f"    [WAKE] cursor: {menu.options[menu.cursor]}")
                    elif response == "select":
                        selected = menu.select()
                        print(f"    [SELECT] {selected}")
                    elif response == "scroll":
                        direction = main._scroll_direction(position)
                        menu.scroll(now_ms, direction)
                        arrow = "+" if direction > 0 else "-"
                        print(f"    [SCROLL {arrow}] cursor: {menu.options[menu.cursor]}")
                print()

            if menu.is_expired(now_ms):
                menu.exit()
                print("  [TIMEOUT] gesture mode exited\n")

            time.sleep_ms(TRIGGER_INTERVAL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  gesture sandbox stopped")


def run_v1():
    """Exercises classify_valid_input + _TapCycleState — the minimal
    tap-or-noise, two-phase ACK/CONFIRM contract, gesture-envelope.md §11.
    Drives the real LED stick now too: ACK_FN renders live during the
    capture window, then WAKE gets the fuller confirm_jolt or CYCLE gets
    the simpler cycle_flash once the verdict is known. Still prints every
    transition — this stays the recognizer/state-machine regression check
    even with real rendering wired in."""
    i2c, addr = main._get_imu()
    if addr is None:
        print("  ✗ No LSM6DSV16X found — run imu_test.py first to debug wiring")
        return

    print("\n══ eki-bin gesture model sandbox (v1) ════════════════")
    print(f"  IMU confirmed at {hex(addr)}")
    print(f"  tap energy threshold: {main.TAP_ENERGY_THRESHOLD}")
    print(f"  trigger poll: {TRIGGER_INTERVAL_MS}ms")
    print("  tap anywhere — Ctrl+C to stop\n")

    state = main._TapCycleState()
    trigger_buffer = []
    last_heartbeat = time.ticks_ms()
    last_error_print = time.ticks_ms()
    last_success_ms = time.ticks_ms()
    sensor_error_start = None  # None = not currently in the error state

    try:
        while True:
            now_ms = time.ticks_ms()

            phase_change = state.advance(now_ms)
            if phase_change:
                print(f"  [{phase_change.upper()}]")

            if not state.accepts_input():
                # WAKING/SETTLING — deliberately not tracking a baseline
                # during the debounce window (gesture-envelope.md §11);
                # trigger_buffer naturally re-warms once input resumes.
                time.sleep_ms(TRIGGER_INTERVAL_MS)
                continue

            raw, last_error_print = _safe_read_accel(i2c, addr, now_ms, last_error_print)
            if raw is None:
                if now_ms - last_success_ms >= SENSOR_ERROR_TIMEOUT_MS:
                    if sensor_error_start is None:
                        sensor_error_start = now_ms
                        print(f"  [SENSOR ERROR] no successful IMU read in over {SENSOR_ERROR_TIMEOUT_MS}ms — check wiring")
                    mult = main.breathe(now_ms - sensor_error_start, main.ERROR_BREATHE_PERIOD_MS, floor=0.15)
                    _write_segment(0, main.NUM_LEDS, SENSOR_ERROR_COLOR, mult)
                    main.np.write()
                time.sleep_ms(TRIGGER_INTERVAL_MS)
                continue
            if sensor_error_start is not None:
                print("  [SENSOR RECOVERED]")
                sensor_error_start = None
                main.clear()
            last_success_ms = now_ms
            sample = (now_ms,) + raw
            mag = main._gesture_magnitude_mg(sample)

            triggered = False
            baseline = None
            if len(trigger_buffer) >= TRIGGER_BUFFER_LEN:
                baseline = main._gesture_median(trigger_buffer)
                triggered = abs(mag - baseline) >= main.TAP_TRIGGER_THRESHOLD_MG

            trigger_buffer.append(mag)
            if len(trigger_buffer) > TRIGGER_BUFFER_LEN:
                trigger_buffer.pop(0)

            if baseline is not None and now_ms - last_heartbeat >= 1000:
                print(f"  … mag={mag:.0f}mg  baseline={baseline:.0f}mg  dev={abs(mag - baseline):.0f}mg  [{state.phase}]")
                last_heartbeat = now_ms

            if triggered:
                state.acknowledge()
                dev = abs(mag - baseline)
                strength = _tap_strength(dev)
                peak_mult = ACK_PEAK_FLOOR + strength * (ACK_PEAK_CEIL - ACK_PEAK_FLOOR)
                shelf_mult = SHELF_FLOOR + strength * (SHELF_CEIL - SHELF_FLOOR)
                ack_ms = ACK_HOLD_MS
                print(f"  [ACK] felt contact (dev={dev:.0f}mg, strength={strength:.2f}) — capturing…")
                samples = _capture_window(
                    i2c, addr, now_ms,
                    ack_fn=lambda ph: ACK_FN(ph, peak_mult=peak_mult, shelf_mult=shelf_mult, ack_ms=ack_ms),
                    ack_ms=ack_ms,
                    shelf_mult=shelf_mult,
                )
                trigger_buffer = []
                features = main.extract_gesture_features(samples)
                valid = main.classify_valid_input(features)
                print(f"    energy={_fmt(features['energy'], 0)}  (threshold={main.TAP_ENERGY_THRESHOLD})")

                now_ms = time.ticks_ms()  # stale after the blocking capture
                response = state.resolve(now_ms, valid)
                if response == "wake":
                    print("  [CONFIRM → WAKE]\n")
                    _render_confirm_jolt(shelf_mult=shelf_mult)
                elif response == "cycle":
                    print("  [CONFIRM → CYCLE]\n")
                    _render_cycle_flash()
                else:
                    print("  [false start — noise]\n")
                    main.clear()  # hard cut from the shelf to black —
                    #                "decided: no," same reasoning as
                    #                confirm_jolt's decay-to-0 for a "yes"

            time.sleep_ms(TRIGGER_INTERVAL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  v1 gesture sandbox stopped")


if MODE == "v1":
    run_v1()
else:
    run_full()
