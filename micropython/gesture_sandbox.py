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


# ── LED rendering — see led_sandbox.py for the design/comparison work ──
# Same _write_segment as led_sandbox.py (bypasses the arc abstraction,
# still goes through the real gamma/dither/_physical pipeline). mult can
# exceed 1.0 here (the CONFIRM jolt peaks at WAKE_JOLT_BRIGHTNESS_MULT) —
# see led_sandbox.py's _write_segment for why the clamping matters.
LED_RENDER_INTERVAL_MS = 16  # throttle LED writes independent of the 4ms
#                              sample rate — matches main.py's FRAME_MS,
#                              no reason to write() faster than a frame


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
            main.np[phys] = tuple(main._clamp255(color[ch] * level) for ch in range(3))


def ack_flash(phase_ms, ack_ms=main.ACK_FLASH_MS):
    """Candidate A: a bare on/off flash. See led_sandbox.py for the A/B."""
    return 1.0 if phase_ms < ack_ms else 0.0


def ack_flick(phase_ms, ack_ms=main.ACK_FLASH_MS * 3):
    """Candidate B (current default, ACK_FN below): a quick rise-then-dip —
    distinct in shape from the CONFIRM jolt even at a glance."""
    half = ack_ms / 2
    if phase_ms < half:
        return phase_ms / half
    if phase_ms < ack_ms:
        return 1.0 - (phase_ms - half) / half
    return 0.0


def confirm_jolt(phase_ms, total_ms=main.WAKE_JOLT_MS, peak_mult=main.WAKE_JOLT_BRIGHTNESS_MULT):
    """WAKE's response: same linear rise/decay shape as _play_startup_burst,
    scaled to WAKE_JOLT_MS's 500ms budget and peaking above 1.0 so it reads
    brighter than steady-state. See led_sandbox.py's confirm_jolt for the
    full rationale."""
    rise_ms = total_ms * (main.STARTUP_BURST_MS / (main.STARTUP_BURST_MS + main.STARTUP_FADE_MS))
    decay_ms = total_ms - rise_ms
    if phase_ms < rise_ms:
        return (phase_ms / rise_ms) * peak_mult
    decay_elapsed = phase_ms - rise_ms
    if decay_elapsed >= decay_ms:
        return 0.0
    return peak_mult * (1.0 - decay_elapsed / decay_ms)


def cycle_flash(phase_ms, total_ms=main.CYCLE_TRANSITION_MS):
    """CYCLE's response: a quick flash + hard cut, not WAKE's fuller jolt —
    deliberately simpler, gesture-envelope.md §11's AWAKE→CYCLE decision
    (no crossfade, same reasoning as CHASE's transition redesign)."""
    return 1.0 if phase_ms < total_ms else 0.0


ACK_FN = ack_flick  # swap to ack_flash to compare live, no re-upload needed


def _render_confirm_jolt():
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
        _write_segment(0, main.NUM_LEDS, main.STARTUP_COLOR, confirm_jolt(elapsed))
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


def _capture_window(i2c, addr, start_ms, ack_fn=None):
    """Local, tunable capture loop — deliberately NOT main._capture_gesture_
    window, so its timing can be experimented with independently. Still
    calls main._imu_read_accel_raw (the real HAL), never re-derives the
    I2C register logic itself.

    ack_fn, if given, renders live during the capture window instead of
    after it — the ACK has to happen here, this is the only code running
    while the real recognizer hasn't decided anything yet. Rendering is
    throttled to LED_RENDER_INTERVAL_MS, independent of the 4ms sample
    rate the recognizer's accuracy numbers were measured at."""
    samples = []
    last_render = start_ms
    while True:
        now = time.ticks_ms()
        elapsed = now - start_ms
        samples.append((elapsed,) + main._imu_read_accel_raw(i2c, addr))
        if ack_fn is not None and now - last_render >= LED_RENDER_INTERVAL_MS:
            _write_segment(0, main.NUM_LEDS, main.STARTUP_COLOR, ack_fn(elapsed))
            main.np.write()
            last_render = now
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

    try:
        while True:
            now_ms = time.ticks_ms()
            sample = (now_ms,) + main._imu_read_accel_raw(i2c, addr)
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

            sample = (now_ms,) + main._imu_read_accel_raw(i2c, addr)
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
                print("  [ACK] felt contact — capturing…")
                samples = _capture_window(i2c, addr, now_ms, ack_fn=ACK_FN)
                trigger_buffer = []
                features = main.extract_gesture_features(samples)
                valid = main.classify_valid_input(features)
                print(f"    energy={_fmt(features['energy'], 0)}  (threshold={main.TAP_ENERGY_THRESHOLD})")

                now_ms = time.ticks_ms()  # stale after the blocking capture
                response = state.resolve(now_ms, valid)
                if response == "wake":
                    print("  [CONFIRM → WAKE]\n")
                    _render_confirm_jolt()
                elif response == "cycle":
                    print("  [CONFIRM → CYCLE]\n")
                    _render_cycle_flash()
                else:
                    print("  [false start — noise]\n")
                    main.clear()  # ack_fn already faded to 0 well before the
                    #                capture window closed — this just makes
                    #                sure, no confirm jolt for a rejected tap

            time.sleep_ms(TRIGGER_INTERVAL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  v1 gesture sandbox stopped")


if MODE == "v1":
    run_v1()
else:
    run_full()
