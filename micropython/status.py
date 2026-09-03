# micropython/status.py — eki-bin
# What the strip does when it is NOT showing departures: the boot ceremony
# and the terminal failure displays. Extracted from main.py by the V1.6
# split (docs/v1.6-refactor.md).
#
# Contracts: docs/contracts/startup-sequence.md and led-status-messages.md.
#
# ⚠ These are DISPLAYS, not decisions. run_startup_sequence() deliberately
# stayed in main.py: it orchestrates clock + network + display, so moving it
# here would make status depend on both and recreate exactly the circular
# import that clock.py had to be rescued from. This module knows how to draw
# "connecting" and "broken"; something else decides when.
#
# _run_startup_failure_forever() NEVER RETURNS by design — a dead end, not a
# retry loop, so a broken unit is distinguishable at a glance and never
# pretends to work. Different failure CAUSES take different colours so
# someone holding a dark jar with no laptop can tell which one happened.

import time
from leds import (_write_frame, clear)
from primitives import (breathe, phase_sawtooth)
from machine import Pin
from neopixel import NeoPixel

from settings import (
    ERROR_BREATHE_PERIOD_MS, ERROR_COLOR, FRAME_MS, HEARTBEAT_PIN, NUM_LEDS,
    ONBOARD_LED_ACTIVE_LOW, ONBOARD_LED_MODE, STARTUP_BURST_MS,
    STARTUP_COLOR, STARTUP_FADE_MS, STARTUP_SPIN_HZ)



# ─────────────────────────────────────────────────────────────
# Startup sequence ("boot ceremony") — docs/contracts/startup-sequence.md
# Runs once at power-on, before the main loop; never recurs during normal
# operation. Not a DisplayContract — at boot there's no LeaveSignal yet (no
# WiFi, no NTP time, schedule not even loaded), so this is boot-time
# procedural code that observes LIVE connection state, not a pure render of
# an already-known value.
# ─────────────────────────────────────────────────────────────
def _startup_circle_index(elapsed_ms):
    """PURE: elapsed ms of the loading-circle spin → which LED is lit, at
    STARTUP_SPIN_HZ revolutions/sec. Host-testable in isolation from the real
    connect_wifi() poll loop below, which isn't (real time.ticks_ms())."""
    period_ms = 1000.0 / STARTUP_SPIN_HZ
    return int(phase_sawtooth(elapsed_ms, period_ms) * NUM_LEDS) % NUM_LEDS


def _draw_startup_circle(elapsed_ms):
    """One frame of the loading-circle spin: a single lit LED, everything
    else off. No dim intermediate value at all (fully on or fully off) —
    STATIC path (see _write_frame), no dithering needed."""
    frame = [None] * NUM_LEDS
    frame[_startup_circle_index(elapsed_ms)] = (STARTUP_COLOR, 1.0, "static")
    _write_frame(frame)


def _startup_burst_mult(elapsed_ms):
    """PURE: elapsed ms into the success burst → brightness mult (0..1).
    Rises linearly over STARTUP_BURST_MS, then decays linearly over
    STARTUP_FADE_MS. Host-testable; the real-time loop that calls this
    (_play_startup_burst) isn't — same split render_for_interval/
    _render_dispatch already established."""
    if STARTUP_BURST_MS > 0 and elapsed_ms < STARTUP_BURST_MS:
        return elapsed_ms / STARTUP_BURST_MS
    decay_elapsed = elapsed_ms - STARTUP_BURST_MS
    if STARTUP_FADE_MS <= 0 or decay_elapsed >= STARTUP_FADE_MS:
        return 0.0
    return 1.0 - (decay_elapsed / STARTUP_FADE_MS)


def _play_startup_burst():
    """The 'hanabi' success cue: all LEDs together (contract-agnostic — no
    CONTRACT is "current" yet), a quick bright rise then a slow decay. This
    genuinely changes every frame, unlike a settled/idle pixel, so the
    ANIMATED path (gamma + dither, via a 2-tuple frame entry) is the right
    one here — dithering only causes trouble on a value that ISN'T changing
    (see docs/contracts/approach-contract.md § Marker ticks); a decaying
    pulse has something to average against. Ends by clearing the strip —
    the main loop's first real frame follows immediately after."""
    start = time.ticks_ms()
    total_ms = STARTUP_BURST_MS + STARTUP_FADE_MS
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= total_ms:
            break
        mult = _startup_burst_mult(elapsed)
        _write_frame([(STARTUP_COLOR, mult)] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _startup_error_mult(elapsed_ms):
    """PURE: elapsed ms → brightness mult for the persistent failure breathe.
    Thin wrapper over the existing breathe() envelope, its own dedicated
    period (ERROR_BREATHE_PERIOD_MS, not BREATHE_PERIOD_MS)."""
    return breathe(elapsed_ms, ERROR_BREATHE_PERIOD_MS, floor=0.15)


def _run_startup_failure_forever(color=None):
    """Persistent breathe — a genuine DEAD END, not a retry loop, by design
    (see docs/contracts/startup-sequence.md § Failure recovery).
    Distinguishes "broken, needs help" from every other state at a glance,
    and doesn't pretend to work when it can't. Needs a physical reset/
    power-cycle to leave this state; never returns on its own.

    `color` defaults to ERROR_COLOR (WiFi/NTP connect failure) — pass
    SCHEDULE_ERROR_COLOR for a schedule-load failure instead. Different
    failure CAUSES get visually distinct colours on purpose, so whoever's
    looking at a dead jar with no laptop handy can tell which one happened
    — see docs/contracts/led-status-messages.md."""
    color = ERROR_COLOR if color is None else color
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _write_frame([(color, _startup_error_mult(elapsed))] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)




def quiet_onboard_leds():
    """Drive the MCU's own indicators dark. Called once at boot.

    Not the strip — these are the LEDs on the board itself, which are
    invisible on a bench and very visible inside a glass jar.

    Everything here is wrapped, because none of it exists on every board:
    the "LED" alias is absent on the XIAO ESP32-C3, and NEOPIXEL only
    exists on some. A missing indicator is not an error.

    ⚠ Two traps, both verified on hardware:
      • The NeoPixel is written BLACK BEFORE its power gate is closed. A
        WS2812-class device latches its last value, so gating power on a
        lit pixel leaves it primed to light again the moment power returns.
      • "LED" polarity is per-board (ONBOARD_LED_ACTIVE_LOW). On the XIAO
        RP2350 it is ACTIVE-LOW, so driving it HIGH is what turns it OFF.
        Guessing wrong lights the LED while trying to extinguish it.

    Skipped when HEARTBEAT_PIN is "LED" — on the Pico 2W that same alias IS
    the heartbeat, and quieting it here would fight the feature.
    """
    if ONBOARD_LED_MODE != "off":
        return
    try:
        gate = Pin("NEOPIXEL_POWER", Pin.OUT)
        gate.on()                       # gate is active-high
        onboard = NeoPixel(Pin("NEOPIXEL"), 1)
        onboard[0] = (0, 0, 0)
        onboard.write()                 # black FIRST, then cut power
        gate.off()
    except (AttributeError, ImportError, TypeError, ValueError):
        pass                            # no onboard NeoPixel on this board
    if HEARTBEAT_PIN != "LED":
        try:
            Pin("LED", Pin.OUT).value(1 if ONBOARD_LED_ACTIVE_LOW else 0)
        except (TypeError, ValueError):
            pass                        # no "LED" alias on this board
