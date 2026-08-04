# micropython/gesture_sandbox.py — eki-bin live gesture model sandbox
# `import main` pulls in main.py's REAL HAL + recognizer + scrollwheel
# primitives (_imu_read_accel_raw, extract_gesture_features,
# classify_tap_or_flick, classify_position, _GestureMenu, ...) without
# starting the real loop — same pattern led_sandbox.py already established
# for the LED side ("import main resolves against whatever main.py is
# CURRENTLY ON THE DEVICE, not your local repo copy — see that file's
# header for the full caveat, it applies here identically").
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
    # "FLICK_MAGNITUDE_THRESHOLD_MG": 250,
    # "FLICK_SPACING_STDEV_THRESHOLD_MS": 20,
}
for _name, _value in THRESHOLD_OVERRIDES.items():
    setattr(main, _name, _value)


def _capture_window(i2c, addr, start_ms):
    """Local, tunable capture loop — deliberately NOT main._capture_gesture_
    window, so its timing can be experimented with independently. Still
    calls main._imu_read_accel_raw (the real HAL), never re-derives the
    I2C register logic itself."""
    samples = []
    while True:
        now = time.ticks_ms()
        elapsed = now - start_ms
        samples.append((elapsed,) + main._imu_read_accel_raw(i2c, addr))
        if elapsed >= main._GESTURE_WINDOW_MS:
            break
        time.sleep_ms(TRIGGER_INTERVAL_MS)
    return samples


def _fmt(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def run():
    i2c, addr = main._get_imu()
    if addr is None:
        print("  ✗ No LSM6DSV16X found — run imu_test.py first to debug wiring")
        return

    print("\n══ eki-bin gesture model sandbox ═════════════════════")
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


run()
