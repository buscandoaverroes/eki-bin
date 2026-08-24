# main.py — eki-bin, V1
# MicroPython on Raspberry Pi Pico 2W
# Reads schedule from schedule.json on device filesystem.
# See docs/contracts/schedule-json.md, config.md, display-contract.md
#
# Display architecture (Step 2):
#   time → LeaveSignal (abstract snapshot) → DisplayContract (renderer) → LEDs
# "What's the urgency?" is computed once per tick and is independent of "how do
# we show it?" — swap visual strategies by changing CONTRACT in config.py.

import gc
import json
import math
import time

# No radio imports here, deliberately. `network`/`ntptime` DO NOT EXIST on
# a radio-less board, and they used to sit unconditionally at line 17 — so
# main.py died with ImportError BEFORE config was read, and TIME_SOURCE
# could not rescue it. They now live in net.py, imported LAZILY inside the
# TIME_SOURCE == "wifi" branch of run_startup_sequence(). A XIAO RP2350
# never reaches that line. See docs/v1.6-refactor.md and insights.md §13.
from machine import I2C, Pin
from neopixel import NeoPixel

# ─────────────────────────────────────────────────────────────
# Settings — extracted to settings.py (V1.6, docs/v1.6-refactor.md)
# ─────────────────────────────────────────────────────────────
# TRANSITIONAL star-import: the test suite reaches into `main.X`, so
# re-exporting keeps all 265 tests passing unmodified while the split
# proceeds. That is what makes a green suite evidence the move was
# faithful. Replaced with explicit imports in V1.6's final step.
from clock import (ClockUnavailable, _check_ds3231_at_boot, current_period,
    fmt_time, local_time)
from contracts import (ACTIVE_CONTRACT, ApproachContract,
    geometry_problems)
from diag import (_mem_checkpoint, _mem_report)
from gestures import (_GESTURE_TRIGGER_BUFFER_LEN, _StatusMessage,
    _TapCycleState, _gesture_magnitude_mg, _gesture_median, _get_imu,
    _handle_tap, _run_gesture_debug_loop, _safe_read_accel)
from leds import (_heartbeat_pin, _write_frame, clear)
from schedule import (is_quiet, load_schedule, schedule_lines)
from settings import (AWAKE_MINUTES, CLOCK_ERROR_COLOR, COLOR_SCHEME,
    CONFIG_ERROR_COLOR, DISPLAY_DIRECTION, DISPLAY_DIRECTION_B,
    ERROR_COLOR, FRAME_MS, GESTURE_DEBUG_ENABLED, GESTURE_POLL_MS,
    HEARTBEAT_PIN, LED_PIN, LOOP_INTERVAL_SECS, NUM_LEDS, N_TRAINS,
    QUIET_TAP_COLOR, QUIET_TAP_DURATION_MS, SCHEDULE_ERROR_COLOR,
    SCHEDULE_FILE, STATUS_LED_INDEX, TAP_TRIGGER_THRESHOLD_MG, TIME_SOURCE,
    WAKE_INTERACTION_ENABLED)
from signals import (LeaveSignal, leave_signal, next_departures)
from status import (_play_startup_burst, _run_startup_failure_forever)

# ─────────────────────────────────────────────────────────────
# Signals, LED output, display contracts — extracted (V1.6)
# ─────────────────────────────────────────────────────────────
# Transitional star-imports; see docs/v1.6-refactor.md. Import ORDER is not
# arbitrary: contracts depends on leds, leds on primitives, all on settings.
# `import *` skips underscores, and the tests reach into main._x.














# ─────────────────────────────────────────────────────────────
# Memory instrumentation — extracted to diag.py (V1.6)
# ─────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────
# Animation primitives — extracted to primitives.py (V1.6)
# ─────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────
# Schedule + clock — extracted (V1.6)
# ─────────────────────────────────────────────────────────────
# `import *` skips underscores. run_startup_sequence() calls this, and
# no host test reaches the ds3231 boot path — so a green suite would
# have shipped a NameError straight to the hardware.
def _local_time_or_die():
    """local_time(), but a clock we can't trust ends the run.

    ⚠ NEVER RETURNS if the RTC is unreadable — it enters the terminal
    failure display, same as a WiFi failure at boot. This device's whole job
    is telling you when to leave, so showing a plausible-looking wrong time
    is the worst thing it can do: you miss the train while believing you
    won't. Dark-and-obviously-broken beats confidently-wrong.

    Lives here rather than in clock.py because it is a POLICY decision about
    what to display, and clock.py only reads clocks. Keeping it there made
    clock depend on the startup sequence, which already depends on clock.

    """
    try:
        return local_time()
    except ClockUnavailable as e:
        print("  ✗ Clock unavailable: %s" % e)
        print("    Refusing to show departures from a clock we can't trust.")
        _run_startup_failure_forever(CLOCK_ERROR_COLOR)  # never returns
# ─────────────────────────────────────────────────────────────
# Status displays + gesture envelope — extracted (V1.6)
# ─────────────────────────────────────────────────────────────
# `import *` skips underscore names. ALL of them are re-exported here
# during the transition because the tests reach into main._x — see
# docs/v1.6-refactor.md. Narrowed in V1.6's final step.
def run_startup_sequence():
    """The whole boot ceremony. On success: connecting spin, then the
    success burst, then returns — the main loop takes over immediately
    after. On WiFi failure: _run_startup_failure_forever(), which NEVER
    RETURNS (see its docstring) — this function correspondingly never
    returns either, in that case.

    TIME_SOURCE="rtc" skips WiFi and NTP entirely and trusts whatever the
    board's RTC already holds (set it at provisioning time with
    `make set-time`). Added because the ESP32-C3 genuinely cannot fit
    esp_wifi alongside a MicroPython app this size — see docs/insights.md
    §11 — so on that board this is the difference between a working unit
    and no unit. It also happens to be the direction V2 is going anyway
    (DS3231 RTC, no WiFi in normal operation), so this is a step toward
    the planned architecture rather than a detour around a bug."""
    if TIME_SOURCE == "ds3231":
        # Terminal on failure, like WiFi. The DS3231 IS the clock on a
        # radio-less unit — there is nothing to fall back to, and falling
        # back to the board's volatile RTC would silently substitute a
        # clock that resets to its epoch on every power cycle.
        if not _check_ds3231_at_boot():
            _run_startup_failure_forever(CLOCK_ERROR_COLOR)
        _play_startup_burst()
        return
    if TIME_SOURCE == "rtc":
        print("  TIME_SOURCE='rtc' — skipping WiFi/NTP, trusting the board clock.")
        print("  (Set it with `make set-time`; it survives soft reset, NOT power loss.)")
        _play_startup_burst()
        return
    # LAZY IMPORT — the whole point of V1.6. net.py is not uploaded to a
    # radio-less board, so importing it at module level would resurrect the
    # exact ImportError that made main.py unrunnable on the XIAO RP2350.
    # Reached only when TIME_SOURCE == "wifi", which such a board never sets.
    from net import connect_wifi, sync_ntp
    if not connect_wifi():
        print("  ✗ WiFi failed — check config.py. Reset to retry.")
        _run_startup_failure_forever(ERROR_COLOR)
    if not sync_ntp():
        print("  Warning: time may be wrong.")
    _play_startup_burst()


# ─────────────────────────────────────────────────────────────
# Gesture envelope (IMU HAL) — docs/contracts/gesture-envelope.md §2
# The only code below that touches i2c.readfrom_mem/writeto_mem — same
# seam the LED side already has (_paint/clear are the only code touching
# np[i]). Register facts verified against ST's own driver source, same as
# imu_test.py/vibration_sandbox.py — see those files' headers for the
# reference. NOT host-testable (real I/O), same category
# _imu_tap_detected() below already is. Lazily constructed, not built at
# import time like `np` — this is opt-in hardware, unlike the LED strip
# which every deployment has.
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────
def _apply_line_color(contract, line):
    """Point the contract at this line's colour, when both sides support it.

    Same capability-probe pattern _render_dispatch uses for render_dual: a
    contract that has no concept of a per-line colour (every arc/urgency
    contract — their palette means URGENCY, not identity) is simply left
    alone, as is a line that declares no colour. So this is a no-op for
    every pre-existing config rather than something they must opt out of."""
    color = line.get("color")
    if color and hasattr(contract, "set_line_color"):
        contract.set_line_color(tuple(color))


def _render_dispatch(contract, signal, signal_b):
    """Pick render() vs render_dual() based on whether signal_b is given AND
    the contract actually implements render_dual — phase-2 bidirectional
    support (ApproachContract only, see DISPLAY_DIRECTION_B). Every other
    contract, and phase-1 ApproachContract configs (DISPLAY_DIRECTION_B
    unset, signal_b is None), fall through to the ordinary single-signal path
    unaffected. Pulled out as its own pure function — no clock involved — so
    this decision is host-testable in isolation from render_for_interval's
    real-time frame loop below, which isn't (it uses actual time.ticks_ms())."""
    if signal_b is not None and hasattr(contract, "render_dual"):
        return lambda phase_ms: contract.render_dual(signal, signal_b, phase_ms)
    return lambda phase_ms: contract.render(signal, phase_ms)


def render_for_interval(contract, signal, seconds, signal_b=None):
    """Hand the signal(s) to the contract for ~`seconds`. Static contracts draw
    once and return immediately (the caller sleeps). Animated contracts get a
    frame loop, fed the **absolute** ms clock so their phase is continuous
    across intervals — no snap-back to the floor every LOOP_INTERVAL_SECS. The
    signal(s) are fixed for the interval; only the clock advances (update/
    render split).

    Safe with the huge absolute value because the envelopes do `(clock % period)`
    — the modulo runs in integer space before the divide, so no float precision is
    lost. `ticks_ms()` wraps ~every 12 days → one harmless single-frame hitch."""
    render = _render_dispatch(contract, signal, signal_b)
    if contract.frame_ms is None:
        render(0)
        return  # caller sleeps the interval
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
        render(time.ticks_ms())
        time.sleep_ms(contract.frame_ms)


def _run_classic_loop(schedule_data, led):
    """The original main loop, unchanged: schedule refresh once every
    LOOP_INTERVAL_SECS, contract renders for the interval via
    render_for_interval(). Used whenever WAKE_INTERACTION_ENABLED is False
    (the default) — every deployment without an IMU wired (e.g.
    config_friend1.py) keeps behaving exactly as it always has, byte for
    byte. See _run_interactive_loop for the wake/sleep + status-message
    version."""
    heartbeat = False
    DIVIDER = "─" * 50
    loop_count = 0

    while True:
        heartbeat = not heartbeat
        if led:
            led.value(heartbeat)
        loop_count += 1
        hb = "●" if heartbeat else "○"

        now, weekday = _local_time_or_die()
        period = current_period(weekday)
        # Line 0 always: this loop has no gestures, so there is nothing to
        # cycle with. A multi-line schedule still works, it just shows the
        # first line — better than showing nothing, which is what reading
        # the top level gave once departures moved inside lines[].
        line = schedule_lines(schedule_data)[0]
        _apply_line_color(ACTIVE_CONTRACT, line)
        directions = line.get(period, {})

        print(DIVIDER)
        print(
            f"  {hb}  {fmt_time(now)} JST   {period}   {schedule_data['station']}   #{loop_count}"
        )
        print(DIVIDER)

        if not directions:
            print(
                f"  No schedule for {period!r} — run: make schedule && make upload"
            )
        else:
            for direction, departures in directions.items():
                upcoming = next_departures(departures, now)
                marker = "  ← ring" if direction == DISPLAY_DIRECTION else ""
                print(f"\n  {direction}{marker}")
                if not upcoming:
                    print("    —  no more trains today")
                    continue
                for i, until in enumerate(upcoming):
                    arrow = "→" if i == 0 else " "
                    print(
                        f"    {arrow}  {fmt_time(now + until)}   in {until:2d} min"
                    )

        # ── Drive the LED ring ───────────────────────────────────
        # One ring → one direction (no magnetometer in V1) — or two, for
        # phase-2 bidirectional ApproachContract (DISPLAY_DIRECTION_B).
        # Build the abstract signal(s), then let whichever contract is
        # active interpret them.
        signal = leave_signal(directions.get(DISPLAY_DIRECTION, []), now)
        if signal.ttls:
            leaves = ", ".join("{:.1f}".format(t) for t in signal.ttls)
            print(f"\n  ring: leave in [{leaves}] min  →  {signal.urgency.name}")
        else:
            print(f"\n  ring: {signal.urgency.name}  (no catchable trains)")

        signal_b = None
        if DISPLAY_DIRECTION_B is not None:
            signal_b = leave_signal(directions.get(DISPLAY_DIRECTION_B, []), now)
            if signal_b.ttls:
                leaves_b = ", ".join("{:.1f}".format(t) for t in signal_b.ttls)
                print(f"  ring B: leave in [{leaves_b}] min  →  {signal_b.urgency.name}")
            else:
                print(f"  ring B: {signal_b.urgency.name}  (no catchable trains)")

        # Night → dark + sleep. Otherwise the contract renders for the interval
        # (static returns at once → we sleep; animated runs its own frame loop).
        if is_quiet(now):
            print("  (quiet hours — display off)")
            clear()
            time.sleep(LOOP_INTERVAL_SECS)
        else:
            render_for_interval(ACTIVE_CONTRACT, signal, LOOP_INTERVAL_SECS, signal_b)
            if ACTIVE_CONTRACT.frame_ms is None:
                time.sleep(LOOP_INTERVAL_SECS)


def _run_interactive_loop(schedule_data, led):
    """Tap interaction + LED status messages — active when GESTURE_ENABLED
    (or the legacy WAKE_INTERACTION_ENABLED) is True. See
    docs/contracts/gesture-envelope.md §11 for the shipped contract and
    docs/contracts/led-status-messages.md for the acknowledgments.

    Structurally different from _run_classic_loop: ONE fast tick drives
    everything — schedule refresh, gesture trigger, and rendering — as
    elapsed-time-gated tasks, rather than one iteration per
    LOOP_INTERVAL_SECS. The cooperative "super-loop" the wake-interaction
    doc's concurrency section settled on: no RTOS, no threads.

    ⚠ The tick is GESTURE_POLL_MS (4ms), NOT FRAME_MS (16ms), and the
    render is a time-gated task on top of it. That asymmetry is load
    bearing: every validated recognizer number was measured at 4ms/240Hz,
    and polling the trigger at FRAME_MS is a documented cause of missed
    taps (gesture_sandbox.py's header). Rendering still happens at
    FRAME_MS — animations don't need 250fps and the strip write isn't free.

    Formerly drove _TapClassifier/_WakeState against a stubbed
    _imu_tap_detected(), which meant it had never once worked on hardware.
    It now drives the real recognizer end to end."""
    heartbeat = False
    DIVIDER = "─" * 50
    loop_count = 0

    tap_state = _TapCycleState()
    tap_state.awake = True  # boot = the first wake trigger, same rule
    tap_state.phase = "awake"  # _WakeState's constructor used to do this
    tap_state.awake_until = time.ticks_ms() + AWAKE_MINUTES * 60_000
    status_message = _StatusMessage()

    # Gestures degrade gracefully: no IMU found = the display still runs,
    # it just never receives a tap. Better than refusing to boot over a
    # peripheral, and it keeps this loop usable on an IMU-less unit.
    i2c, imu_addr = _get_imu()
    if imu_addr is None:
        print("  ⚠ No IMU found — display runs, taps won't register.")
    trigger_buffer = []
    last_error_print = time.ticks_ms()
    last_render = None

    # Which line is on show. CYCLE advances it (gesture-envelope.md §11) —
    # the station is fixed (the bin lives in one room), so the line is what
    # varies. Kept as a plain index, wrapped at use, so a schedule reload
    # with fewer lines can't leave it dangling.
    lines = schedule_lines(schedule_data)
    line_index = 0
    _apply_line_color(ACTIVE_CONTRACT, lines[0])
    if len(lines) > 1:
        print(f"  Lines: {', '.join(l.get('name', '?') for l in lines)}  (tap to cycle)")

    last_refresh = None
    now = 0
    signal = LeaveSignal([])
    signal_b = None

    while True:
        tick_now = time.ticks_ms()

        # ── slow task: schedule refresh, ~LOOP_INTERVAL_SECS ──────────
        if last_refresh is None or time.ticks_diff(tick_now, last_refresh) >= LOOP_INTERVAL_SECS * 1000:
            last_refresh = tick_now
            heartbeat = not heartbeat
            if led:
                led.value(heartbeat)
            loop_count += 1
            hb = "●" if heartbeat else "○"

            now, weekday = _local_time_or_die()
            period = current_period(weekday)
            line = lines[line_index % len(lines)]
            directions = line.get(period, {})

            print(DIVIDER)
            print(
                f"  {hb}  {fmt_time(now)} JST   {period}   "
                f"{schedule_data['station']}/{line.get('name', '?')}   #{loop_count}"
            )
            print(DIVIDER)

            if not directions:
                print(
                    f"  No schedule for {period!r} — run: make schedule && make upload"
                )
            else:
                for direction, departures in directions.items():
                    upcoming = next_departures(departures, now)
                    marker = "  ← ring" if direction == DISPLAY_DIRECTION else ""
                    print(f"\n  {direction}{marker}")
                    if not upcoming:
                        print("    —  no more trains today")
                        continue
                    for i, until in enumerate(upcoming):
                        arrow = "→" if i == 0 else " "
                        print(
                            f"    {arrow}  {fmt_time(now + until)}   in {until:2d} min"
                        )

            signal = leave_signal(directions.get(DISPLAY_DIRECTION, []), now)
            if signal.ttls:
                leaves = ", ".join("{:.1f}".format(t) for t in signal.ttls)
                print(f"\n  ring: leave in [{leaves}] min  →  {signal.urgency.name}")
            else:
                print(f"\n  ring: {signal.urgency.name}  (no catchable trains)")

            signal_b = None
            if DISPLAY_DIRECTION_B is not None:
                signal_b = leave_signal(directions.get(DISPLAY_DIRECTION_B, []), now)
                if signal_b.ttls:
                    leaves_b = ", ".join("{:.1f}".format(t) for t in signal_b.ttls)
                    print(f"  ring B: leave in [{leaves_b}] min  →  {signal_b.urgency.name}")
                else:
                    print(f"  ring B: {signal_b.urgency.name}  (no catchable trains)")

        # ── fast task: gesture trigger, polled at GESTURE_POLL_MS ─────
        # This is why the loop ticks faster than it renders: the
        # recognizer's validated accuracy was measured at 4ms/240Hz, and
        # polling at FRAME_MS was documented as a real cause of missed
        # taps (gesture_sandbox.py's header). Render is time-gated below.
        quiet_now = is_quiet(now)

        phase_change = tap_state.advance(tick_now)
        if phase_change == "asleep":
            print("  [SLEEP] awake window expired")

        if imu_addr is not None and tap_state.accepts_input():
            raw, last_error_print = _safe_read_accel(
                i2c, imu_addr, tick_now, last_error_print
            )
            if raw is not None:
                mag = _gesture_magnitude_mg((tick_now,) + raw)
                baseline = None
                if len(trigger_buffer) >= _GESTURE_TRIGGER_BUFFER_LEN:
                    baseline = _gesture_median(trigger_buffer)
                trigger_buffer.append(mag)
                if len(trigger_buffer) > _GESTURE_TRIGGER_BUFFER_LEN:
                    trigger_buffer.pop(0)

                if baseline is not None and abs(mag - baseline) >= TAP_TRIGGER_THRESHOLD_MG:
                    dev = abs(mag - baseline)
                    # Quiet hours short-circuits BEFORE the ~1.2s capture —
                    # led-status-messages.md says quiet hours is checked
                    # first, and honouring that here also means quiet-hours
                    # taps cost nothing instead of stalling the loop.
                    if quiet_now:
                        status_message.show(
                            tick_now, QUIET_TAP_COLOR, QUIET_TAP_DURATION_MS
                        )
                        trigger_buffer = []
                    else:
                        response = _handle_tap(
                            i2c, imu_addr, tick_now, dev, tap_state,
                            signal, signal_b, status_message,
                        )
                        if response == "cycle" and len(lines) > 1:
                            line_index = (line_index + 1) % len(lines)
                            # Recompute NOW rather than waiting up to
                            # LOOP_INTERVAL_SECS for the slow task: a tap
                            # whose effect appears half a minute later reads
                            # as a broken tap, not a slow one.
                            last_refresh = None
                            _apply_line_color(ACTIVE_CONTRACT, lines[line_index])
                            print(f"  [LINE] {lines[line_index].get('name', '?')}")
                        trigger_buffer = []  # the window covered this stretch
                        last_render = None  # force a repaint after the jolt

        # ── render, time-gated to FRAME_MS ──────────────────────────
        if last_render is not None and time.ticks_diff(tick_now, last_render) < FRAME_MS:
            time.sleep_ms(GESTURE_POLL_MS)
            continue
        last_render = tick_now

        if status_message.active(tick_now):
            frame = [None] * NUM_LEDS
            frame[STATUS_LED_INDEX] = (status_message.color, 1.0, "static")
            _write_frame(frame)
        elif quiet_now or not tap_state.awake:
            clear()
        else:
            _render_dispatch(ACTIVE_CONTRACT, signal, signal_b)(tick_now)

        time.sleep_ms(GESTURE_POLL_MS)


def _run_startup_and_mark():
    """run_startup_sequence() + a checkpoint. Wrapped because that function
    NEVER RETURNS on WiFi failure (persistent breathe), so a checkpoint
    written after the call site would silently not happen on the very path
    where memory is most likely to be the culprit."""
    run_startup_sequence()
    _mem_checkpoint("after time source")


def main():
    print("\n══ eki-bin ═══════════════════════════════════════")
    # Baseline: everything main.py's import already cost — bytecode,
    # module globals, the NeoPixel buffer, _residual. Every later delta is
    # relative to this.
    _mem_checkpoint("after import")

    if GESTURE_DEBUG_ENABLED:
        # No WiFi/schedule/boot-ceremony needed — this validates the
        # gesture envelope in isolation, same "standalone, no dependency
        # beyond the IMU" property the sandbox tools already have. Early
        # return, deliberately bypassing everything below rather than
        # threading a flag through the existing schedule/WiFi/boot flow.
        try:
            _run_gesture_debug_loop()
        except KeyboardInterrupt:
            pass
        return

    # Config-value errors get an LED cue too. _heartbeat_pin is the known
    # offender (HEARTBEAT_PIN="LED" is a Pico-2W-only alias; on any other
    # board Pin("LED") raises ValueError) but this guards the whole class:
    # a bad config value used to crash here, BEFORE run_startup_sequence()
    # below ever runs, so nothing lit up at all. On USB you'd see the
    # traceback; on a wall adapter the unit just looked dead.
    #
    # ⚠ Not everything is catchable here: LED_PIN/NUM_LEDS are consumed at
    # IMPORT time to build `np`, so getting those wrong fails before main()
    # is entered and no LED feedback is possible by construction. Those two
    # stay a serial-console diagnosis.
    # Only ApproachContract consumes the anchor/arm geometry, so only it can
    # be broken by a mismatch — failing on it for an arc contract that never
    # reads those values would be a false alarm.
    if isinstance(ACTIVE_CONTRACT, ApproachContract):
        _geo = geometry_problems()
        if _geo:
            print("  ✗ ApproachContract geometry doesn't fit NUM_LEDS=%d:"
                  % NUM_LEDS)
            for _problem in _geo:
                print("      %s" % _problem)
            print("    Previously this only appeared as `IndexError: list index")
            print("    out of range` inside the render loop, several calls deep")
            print("    and long after a clean boot — pointing nowhere near config.")
            _run_startup_failure_forever(CONFIG_ERROR_COLOR)  # never returns

    try:
        led = _heartbeat_pin(HEARTBEAT_PIN)  # None on boards with no onboard-LED alias
    except (ValueError, TypeError) as e:
        print(f"  ✗ Bad config value: HEARTBEAT_PIN={HEARTBEAT_PIN!r} ({e})")
        print("    Pico 2W accepts \"LED\"; every other board needs a GPIO number")
        print("    or bare None. See pinouts/<board>.md.")
        _run_startup_failure_forever(CONFIG_ERROR_COLOR)  # never returns

    try:
        # ⚠ ORDERING IS MEMORY-DRIVEN, NOT ARBITRARY — do not move WiFi back
        # below load_schedule(). On the ESP32-C3, esp_wifi_init() needs
        # ~40KB, and ~26KB of that must come from ONE specific SRAM region
        # (measured: it drains regions 2 and 4 to 4 and 32 bytes free while
        # leaving 111KB untouched in region 3, which can't satisfy its
        # DMA/internal capability requirements). At a bare boot that region
        # has just 26,448 bytes free against WiFi's 26,416 — **32 bytes of
        # margin**. Anything allocated before WiFi comes up competes for it.
        #
        # Parsing schedule.json first cost ~5.5KB of exactly that region and
        # made connect_wifi() raise `OSError: Wifi Out of Memory`. Bringing
        # the radio up first lets MicroPython's heap grow into whatever's
        # left over instead of the other way round.
        #
        # This buys margin; it does not create headroom. See
        # docs/insights.md §11 for the real fix (stop compiling a 115KB
        # module on-device) — this reorder is the cheap half.
        _run_startup_and_mark()  # boot ceremony + WiFi/NTP — never returns on
        #   WiFi failure (persistent red breathe instead), so everything
        #   below only ever runs after a successful connect + burst.

        try:
            schedule_data = load_schedule(SCHEDULE_FILE)
            # The parked multi-line question in concrete terms: this delta
            # IS the schedule's real cost, object graph included, rather
            # than the estimate dev-status.md currently records.
            _mem_checkpoint("after schedule load")
        except (OSError, ValueError):
            # Different failure CAUSE, different colour — see
            # docs/contracts/led-status-messages.md. A missing/corrupt
            # schedule.json used to crash here with a console print and no
            # LED indication at all; now gets the same persistent-failure
            # treatment WiFi/NTP failure already had, just its own colour.
            print("  ✗ Schedule failed to load. Reset to retry.")
            _run_startup_failure_forever(SCHEDULE_ERROR_COLOR)  # never returns

        print(
            f"  Station: {schedule_data['station']}   Ring: {DISPLAY_DIRECTION!r}\n"
            f"  Contract: {type(ACTIVE_CONTRACT).__name__}   Scheme: {COLOR_SCHEME!r}   "

            f"  N trains: {N_TRAINS} "
            f"LEDs: {NUM_LEDS} on GPIO{LED_PIN}"
        )
        print(f"  Loop interval: {LOOP_INTERVAL_SECS}s  |  Ctrl+C to stop\n")

        _mem_checkpoint("entering loop")
        _mem_report()

        if WAKE_INTERACTION_ENABLED:
            _run_interactive_loop(schedule_data, led)
        else:
            _run_classic_loop(schedule_data, led)
    except KeyboardInterrupt:
        pass
    finally:
        clear()  # leave the strip dark on exit, like led_test.py
        print("\n  cleared — bye")


# `mpremote run main.py` and the device boot both execute this as __main__, so
# the loop still starts normally. But `import main` in the REPL does NOT — which
# lets you poke a contract live while iterating, no WiFi needed:
#     import main
#     sig = main.LeaveSignal([3.0])              # a 3-min-to-leave snapshot
#     main.ACTIVE_CONTRACT.render(sig, 0)        # draw it
#     main.clear()
if __name__ == "__main__":
    main()
