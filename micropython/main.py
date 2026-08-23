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

# ⚠ `network`/`ntptime` DO NOT EXIST on a radio-less board. On the XIAO
# RP2350 (no WiFi silicon at all) this is not "WiFi unavailable at runtime"
# — it is an ImportError on THIS LINE that kills main.py before TIME_SOURCE
# is ever read, so setting TIME_SOURCE="rtc" cannot rescue it. Observed on
# hardware 2026-08-23.
#
# Note the shape of the bug: the comment below already reasons carefully
# about deferring WIFI_SSID so there's "an LED path to complain THROUGH" —
# and then the module died two lines above it, before any such path exists.
# Guarding the import is what actually lets that reasoning apply.
try:
    import network
    import ntptime
except ImportError:  # radio-less board — connect_wifi() explains it properly
    network = None
    ntptime = None
from machine import I2C, Pin
from neopixel import NeoPixel

# ─────────────────────────────────────────────────────────────
# Settings — extracted to settings.py (V1.6, docs/v1.6-refactor.md)
# ─────────────────────────────────────────────────────────────
# TRANSITIONAL star-import: the test suite reaches into `main.X`, so
# re-exporting keeps all 265 tests passing unmodified while the split
# proceeds. That is what makes a green suite evidence the move was
# faithful. Replaced with explicit imports in V1.6's final step.
from settings import *  # noqa: F401,F403
from settings import _UTC_OFFSET_APPLIED  # `import *` skips underscore names

# ─────────────────────────────────────────────────────────────
# Signals, LED output, display contracts — extracted (V1.6)
# ─────────────────────────────────────────────────────────────
# Transitional star-imports; see docs/v1.6-refactor.md. Import ORDER is not
# arbitrary: contracts depends on leds, leds on primitives, all on settings.
from signals import *  # noqa: F401,F403
from leds import *  # noqa: F401,F403
from contracts import *  # noqa: F401,F403
# `import *` skips underscores, and the tests reach into main._x.
from leds import (_clamp255, _heartbeat_pin, _layer_hue_shift, _layer_mult,
    _paint, _paint_layers, _physical, _quantize, _residual, _write_frame)
from contracts import (_TrainState, _advance_arm, _advance_train, _arc_len,
    _arm_target, _position_offset)






def clear():
    """All LEDs off."""
    for i in range(NUM_LEDS):
        np[i] = (0, 0, 0)
    np.write()








# ─────────────────────────────────────────────────────────────
# Memory instrumentation — extracted to diag.py (V1.6)
# ─────────────────────────────────────────────────────────────
from diag import *  # noqa: F401,F403  — transitional, see runbook
from diag import _mem_checkpoint, _mem_marks, _mem_report  # skipped by *



# ─────────────────────────────────────────────────────────────
# Animation primitives — extracted to primitives.py (V1.6)
# ─────────────────────────────────────────────────────────────
from primitives import *  # noqa: F401,F403  — transitional, see runbook
from primitives import _hsv_to_rgb, _rgb_to_hsv  # `import *` skips these



def is_quiet(now):
    """True during the configured quiet hours. The window can wrap past midnight
    (e.g. 23:00 → 06:00), so we test the gap with OR, not a simple range."""
    return now >= QUIET_START or now < QUIET_END


# ─────────────────────────────────────────────────────────────
# Schedule loading
# [→ Rust] build.rs reads schedule.json at compile time and emits
#          const arrays — zero runtime parsing cost on device.
# ─────────────────────────────────────────────────────────────
def load_schedule(filename):
    """
    Load schedule.json from device filesystem.
    Returns the full parsed dict (station, weekday, weekend).
    Raises (OSError: missing file; ValueError: malformed JSON) rather than
    halting itself — the caller decides what "failed to load" looks like on
    the LEDs (see main()'s call site and
    docs/contracts/led-status-messages.md's schedule-load-failure entry).
    """
    try:
        with open(filename) as f:
            return json.load(f)
    except OSError:
        print(f"✗ Schedule file not found: {filename}")
        print("  Upload it with: make upload")
        raise
    except ValueError:
        print(f"✗ Schedule file malformed (bad JSON): {filename}")
        print("  Regenerate it with: make schedule && make upload")
        raise


# ─────────────────────────────────────────────────────────────
# DS3231 RTC (TIME_SOURCE="ds3231") — docs/hardware.md § DS3231
#
# Why a separate TIME_SOURCE value rather than redefining "rtc": "rtc"
# already means the BOARD's own volatile clock, which is what makes the
# WiFi-free ESP32-C3 unit run at all (docs/insights.md §11). Overloading it
# would break that unit. They also differ in the way that matters most —
# the board clock does NOT survive power loss, and this chip's whole
# purpose is that it does.
#
# The chip is read EVERY tick rather than copied into the board's RTC at
# boot. Copying once would mean trusting the RP2350's crystal thereafter,
# which is an order of magnitude worse than the TCXO we bought; the DS3231
# stays the single source of truth. Reads are cached ~1s (see _rtc_cache)
# because the IMU shares this bus and the gesture loop ticks every 4ms,
# while the display is minute-granular.
#
# Time is stored LOCAL, not UTC — matching what rtc_test.py already seeds,
# so _UTC_OFFSET_APPLIED is 0 exactly as for "rtc". Japan has no DST, so
# UTC storage would buy nothing and would require migrating the seeding
# path. scripts/rtc_drift.py is deliberately indifferent to which is used.
#
# [→ Rust] read_rtc() reads DS3231 over I2C → (hours, minutes, weekday)
# ─────────────────────────────────────────────────────────────
_DS3231_ADDR = 0x68  # fixed in silicon — no address strap on this chip
_DS3231_REG_SECONDS = 0x00  # 7 regs from here: sec,min,hour,dow,date,mon,yr
_DS3231_REG_STATUS = 0x0F
_DS3231_OSF_BIT = 0x80  # status bit7: oscillator STOPPED since last cleared

_rtc_i2c = None
_rtc_cache = None  # (ticks_ms_when_read, decoded_tuple)
_RTC_CACHE_MS = 1000


class ClockUnavailable(Exception):
    """The DS3231 can't be read, or says its time is untrustworthy.

    Deliberately NOT caught-and-ignored anywhere: showing a wrong departure
    time is worse than showing none, because it makes you miss the train
    while believing you won't. See run_startup_sequence()."""


def _ds3231_bcd_to_dec(b):
    return (b >> 4) * 10 + (b & 0x0F)


def day_of_week(year, month, day):
    """Sakamoto's algorithm → 0=Monday … 6=Sunday (MicroPython convention).

    Computed from the DATE rather than read from the chip's day-of-week
    register (0x03). That register holds 1-7 with NO defined meaning — the
    mapping is whatever wrote it decided — so trusting it would couple the
    firmware to whichever tool last seeded the chip. The date is
    unambiguous, and this costs a few integer ops."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    y = year - 1 if month < 3 else year
    sunday_based = (y + y // 4 - y // 100 + y // 400 + t[month - 1] + day) % 7
    return (sunday_based - 1) % 7  # shift 0=Sunday → 0=Monday


def ds3231_decode(raw):
    """7 raw DS3231 registers → (year, month, day, hour, minute, second).

    Pure — no I/O — so tests/test_ds3231.py can cover it on the host.
    Backwards BCD produces a clock that looks alive while showing nonsense,
    which is exactly the failure a host test catches and a bench cannot."""
    if len(raw) != 7:
        raise ValueError("expected 7 registers, got %d" % len(raw))
    second = _ds3231_bcd_to_dec(raw[0] & 0x7F)
    minute = _ds3231_bcd_to_dec(raw[1] & 0x7F)
    hour_reg = raw[2]
    if hour_reg & 0x40:  # 12-hour mode: bit5 is AM/PM. We never WRITE this,
        #                  but a chip set by other tooling can be in it.
        hour = _ds3231_bcd_to_dec(hour_reg & 0x1F)
        if hour_reg & 0x20 and hour != 12:
            hour += 12
        elif not hour_reg & 0x20 and hour == 12:
            hour = 0
    else:
        hour = _ds3231_bcd_to_dec(hour_reg & 0x3F)
    day = _ds3231_bcd_to_dec(raw[4] & 0x3F)
    month = _ds3231_bcd_to_dec(raw[5] & 0x1F)
    century = 2100 if raw[5] & 0x80 else 2000
    return (century + _ds3231_bcd_to_dec(raw[6]), month, day,
            hour, minute, second)


def ds3231_time_is_plausible(decoded):
    """Sanity-gate a decoded reading before the display trusts it.

    A DS3231 that lost power with no working backup resets to 2000-01-01 —
    observed on hardware, and the anchor that says the CR1220 isn't doing
    its job. That reads as a perfectly valid timestamp, so OSF alone is not
    the only guard worth having."""
    year, month, day, hour, minute, second = decoded
    return (2024 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31
            and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59)


def _get_rtc_i2c():
    """Lazy singleton, mirroring _get_imu()'s construction guard."""
    global _rtc_i2c
    if _rtc_i2c is None:
        try:
            _rtc_i2c = I2C(RTC_I2C_ID, scl=Pin(RTC_SCL_PIN),
                           sda=Pin(RTC_SDA_PIN), freq=400000)
        except ValueError as e:
            # Rejected at construction on RP2 chips — see _get_imu() for the
            # full explanation of why no rewiring can fix this.
            raise ClockUnavailable(
                "RTC I2C rejected (%s): RTC_I2C_ID=%d with SDA=%d/SCL=%d is "
                "not a legal combination on this chip. Run `make i2c-scan`."
                % (e, RTC_I2C_ID, RTC_SDA_PIN, RTC_SCL_PIN))
    return _rtc_i2c


def ds3231_osc_stopped():
    """True if the oscillator has stopped since the flag was last cleared —
    i.e. the chip cannot vouch for its own time. This is the DS3231's own
    claim, which is why it beats eyeballing the clock: a chip that lost
    power at 3am and was re-powered still SHOWS a plausible time."""
    try:
        status = _get_rtc_i2c().readfrom_mem(_DS3231_ADDR,
                                             _DS3231_REG_STATUS, 1)[0]
    except OSError as e:
        raise ClockUnavailable("cannot read DS3231 status register: %s" % e)
    return bool(status & _DS3231_OSF_BIT)


def ds3231_now():
    """Read + decode the chip, cached ~1s. Raises ClockUnavailable.

    Retries a couple of times before giving up: this bus is shared with the
    IMU and a single NAK shouldn't take the display down, but a chip that
    is genuinely gone must not be papered over."""
    global _rtc_cache
    if _rtc_cache is not None:
        age = time.ticks_diff(time.ticks_ms(), _rtc_cache[0])
        if 0 <= age < _RTC_CACHE_MS:
            return _rtc_cache[1]
    last = None
    for _ in range(3):
        try:
            raw = _get_rtc_i2c().readfrom_mem(_DS3231_ADDR,
                                              _DS3231_REG_SECONDS, 7)
            decoded = ds3231_decode(bytes(raw))
            _rtc_cache = (time.ticks_ms(), decoded)
            return decoded
        except OSError as e:
            last = e
    raise ClockUnavailable("DS3231 unreadable after 3 attempts: %s" % last)


# ─────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────
def local_time():
    """
    Return (minutes_since_midnight, weekday) in local time.
    weekday: 0=Monday … 6=Sunday (MicroPython convention)

    NTP sets the RTC to UTC, so we add UTC_OFFSET_HOURS to get local time —
    and also account for the day boundary, so the correct weekday is used
    when UTC and local time are on different calendar days.
    (e.g. UTC 22:00 Thursday = JST 07:00 Friday)

    With TIME_SOURCE="rtc" the clock is ALREADY local (`mpremote rtc --set`
    writes host local time), so no offset is applied — see
    _UTC_OFFSET_APPLIED. Reading the raw clock as UTC in that case would
    put the display UTC_OFFSET_HOURS ahead of reality.
    """
    if TIME_SOURCE == "ds3231":
        return _ds3231_local_time()
    raw = time.localtime()  # (year, mon, mday, hour, min, sec, weekday, yearday)
    utc_minutes = raw[3] * 60 + raw[4]
    local_minutes_abs = utc_minutes + _UTC_OFFSET_APPLIED * 60

    day_overflow = local_minutes_abs // (24 * 60)  # 0 or 1
    local_minutes = local_minutes_abs % (24 * 60)
    local_weekday = (raw[6] + day_overflow) % 7

    return local_minutes, local_weekday


def _ds3231_local_time():
    """local_time() for TIME_SOURCE="ds3231".

    ⚠ MAY NEVER RETURN. If the clock can't be read it enters the terminal
    failure display instead of guessing — same pattern (and same warning)
    as run_startup_sequence() on WiFi failure. That is deliberate: this
    device's entire job is telling you when to leave, so a plausible-looking
    wrong time is the worst output it can produce. Dark-and-obviously-broken
    beats confidently-wrong.

    The offset arithmetic mirrors the WiFi path exactly, even though
    _UTC_OFFSET_APPLIED is 0 here, so that switching the chip to UTC storage
    later is a one-constant change rather than a rewrite."""
    try:
        year, month, day, hour, minute, _second = ds3231_now()
    except ClockUnavailable as e:
        print("  ✗ Clock unavailable: %s" % e)
        print("    Refusing to show departures from a clock we can't trust.")
        _run_startup_failure_forever(CLOCK_ERROR_COLOR)  # never returns
    minutes_abs = hour * 60 + minute + _UTC_OFFSET_APPLIED * 60
    day_overflow = minutes_abs // (24 * 60)
    weekday = (day_of_week(year, month, day) + day_overflow) % 7
    return minutes_abs % (24 * 60), weekday


def _check_ds3231_at_boot():
    """Validate the RTC before the display trusts it. True if usable.

    Three distinct checks, because they fail for different reasons and a
    single "clock bad" message would send you to the wrong place:
      1. readable at all  → wiring, or I2C_ID/pin mismatch
      2. OSF clear        → the CR1220 isn't doing its job
      3. plausible year   → a chip that lost power reads 2000-01-01, which
                            is a perfectly valid-looking timestamp that OSF
                            alone would not always catch
    """
    try:
        stopped = ds3231_osc_stopped()
        decoded = ds3231_now()
    except ClockUnavailable as e:
        print("  ✗ DS3231 not readable: %s" % e)
        print("    Check wiring and `make i2c-scan`. NOTE: a fitted battery")
        print("    HIDES a power fault — the chip disables I2C on VBAT, so a")
        print("    sagging VIN looks like an absent chip (insights.md §13).")
        return False
    if stopped:
        print("  ✗ DS3231 oscillator-stop flag is SET — it lost power and")
        print("    its time cannot be trusted. Check the CR1220 is seated")
        print("    and the right way up, then re-seed with `make rtc-test`.")
        return False
    if not ds3231_time_is_plausible(decoded):
        print("  ✗ DS3231 reads %04d-%02d-%02d %02d:%02d — implausible."
              % decoded[:5])
        print("    A chip that lost power with no backup resets to 2000-01-01.")
        print("    Re-seed with `make rtc-test`.")
        return False
    print("  TIME_SOURCE='ds3231' — RTC reads %04d-%02d-%02d %02d:%02d, "
          "oscillator OK." % decoded[:5])
    return True


def current_period(weekday):
    """Return 'weekday' or 'weekend' for the given weekday index."""
    return "weekend" if weekday >= 5 else "weekday"


def fmt_time(minutes):
    """Format minutes-since-midnight as HH:MM."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ─────────────────────────────────────────────────────────────
# Schedule logic
# [→ Rust] Iterator::filter().take(n) on a sorted &[u16]
# ─────────────────────────────────────────────────────────────
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
_IMU_WHO_AM_I_REG = 0x0F
_IMU_WHO_AM_I_EXPECTED = 0x70
_IMU_CTRL1_REG = 0x10
_IMU_CTRL1_240HZ_HIGH_PERF = 0x07
_IMU_CTRL1_POWER_DOWN = 0x00
_IMU_OUTX_L_A = 0x28
_IMU_CANDIDATE_ADDRS = (0x6A, 0x6B)

_imu_i2c = None  # lazy singleton — see _get_imu()
_imu_addr = None


def _imu_find_device(i2c):
    """Scan the bus, confirm WHO_AM_I. Returns the confirmed 7-bit address,
    or None — mirrors imu_test.py's _find_device exactly."""
    found = i2c.scan()
    for addr in _IMU_CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, _IMU_WHO_AM_I_REG, 1)[0]
        if who == _IMU_WHO_AM_I_EXPECTED:
            return addr
    return None


def _get_imu():
    """Lazily construct + confirm the IMU, caching the result. Returns
    (i2c, addr), or (None, None) if no sensor responds — callers must
    handle the "not found" case, not assume hardware is present."""
    global _imu_i2c, _imu_addr
    if _imu_i2c is None:
        try:
            i2c = I2C(IMU_I2C_ID, scl=Pin(IMU_SCL_PIN), sda=Pin(IMU_SDA_PIN),
                      freq=400000)
        except ValueError as e:
            # RP2040/RP2350 hard-wire each I2C peripheral to a fixed pin
            # table, so a pin/ID disagreement is rejected HERE, at
            # construction, before any bus activity — meaning no rewiring
            # can fix it. It surfaces as a bare `ValueError: bad SCL pin`
            # with no hint of which value is wrong.
            #
            # This has bitten four times now. imu_test.py and rtc_test.py
            # each grew an explainer; main.py had none, so it took the
            # whole display down mid-loop over an optional sensor. Treat a
            # misconfigured IMU exactly like an absent one: say what's
            # wrong, then let the clock keep running.
            print("  ✗ IMU I2C rejected: %s" % e)
            print("    IMU_I2C_ID=%d with SDA=%d/SCL=%d is not a legal"
                  % (IMU_I2C_ID, IMU_SDA_PIN, IMU_SCL_PIN))
            print("    combination on this chip. XIAO RP2350: GP6/GP7 are")
            print("    I2C **1**, not 0. Run `make i2c-scan` for the values.")
            print("    Continuing without gestures — display is unaffected.")
            return None, None
        addr = _imu_find_device(i2c)
        if addr is None:
            return None, None
        i2c.writeto_mem(addr, _IMU_CTRL1_REG, bytes([_IMU_CTRL1_240HZ_HIGH_PERF]))
        _imu_i2c, _imu_addr = i2c, addr
    return _imu_i2c, _imu_addr


def _imu_read_accel_raw(i2c, addr):
    """One burst read, signed int16 LSB counts — no unit conversion here
    (see _gesture_magnitude_mg in the feature-extraction layer below),
    matching vibration_sandbox.py's _read_accel_raw exactly."""
    data = i2c.readfrom_mem(addr, _IMU_OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    return tuple(v - 65536 if v > 32767 else v for v in (x, y, z))


# ─────────────────────────────────────────────────────────────
# Gesture envelope (feature extraction) — gesture-envelope.md §3
# PURE — a raw sample buffer in, an engineered-feature dict out. Same math
# as scripts/prepare_tap_dataset.py's engineer_features(), ported from host
# Python to MicroPython (no numpy/statistics module on either side — both
# avoid it already). Host-tested with synthetic sample lists, same
# "separate the decision logic from real-time I/O" split
# _render_dispatch/_classify_wake_response already established.
# samples: list of (t_ms, x, y, z) raw int16 LSB tuples — the HAL's
# _imu_read_accel_raw() output, not the dict shape the host scripts use
# (that shape only exists because JSON round-trips through dicts; on-device
# there's no reason to pay for it).
# ─────────────────────────────────────────────────────────────
_GESTURE_CROSSING_FRAC = 0.3  # matches prepare_tap_dataset.py's
#   CROSSING_THRESHOLD_FRAC exactly — see that file for why 0.3, not
#   analyze_taps.py's stricter 0.5 (this wants to see every excursion,
#   including rocking echoes, not just plausible "real" taps)
_GESTURE_SETTLE_FRAC = 0.1  # matches prepare_tap_dataset.py's SETTLE_FRAC


def _gesture_magnitude_mg(sample):
    """0.061 mg/LSB at power-on-default full-scale (±2g) — same
    approximation imu_test.py/vibration_sandbox.py already use."""
    _, x, y, z = sample
    return math.sqrt(x * x + y * y + z * z) * 0.061


def _gesture_median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def _gesture_mean(values):
    return sum(values) / len(values)


def _gesture_stdev(values):
    """Sample standard deviation. Caller's responsibility to only call this
    with len(values) >= 2 — same contract prepare_tap_dataset.py's
    statistics.stdev() usage already has."""
    m = _gesture_mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _gesture_dominant_axis(sample):
    _, x, y, z = sample
    axis, value = "x", x
    if abs(y) > abs(value):
        axis, value = "y", y
    if abs(z) > abs(value):
        axis, value = "z", z
    return axis


def extract_gesture_features(samples):
    """PURE: raw (t_ms, x, y, z) samples → the same feature set
    prepare_tap_dataset.py validated (docs/insights.md §8-9). `samples`
    must have at least 2 entries — the caller (the capture-window logic in
    the recognizer layer) guarantees this, same as the sandbox tools always
    captured at least one sample before returning."""
    mags = [_gesture_magnitude_mg(s) for s in samples]
    baseline = _gesture_median(mags)
    deviations = [m - baseline for m in mags]

    peak_dev = max(deviations)
    peak_idx = deviations.index(peak_dev)
    peak_t = samples[peak_idx][0]
    duration_ms = samples[-1][0]

    energy = sum(d * d for d in deviations if d > 0)

    ring_down_ms = None
    settle_dev = _GESTURE_SETTLE_FRAC * peak_dev
    for i in range(peak_idx, len(samples)):
        if deviations[i] < settle_dev:
            ring_down_ms = samples[i][0] - peak_t
            break

    # peak_dev <= 0 means no real excursion at all (a perfectly flat
    # buffer — never happens with real sensor noise, but a threshold of 0
    # would otherwise register every sample as "above" it). No crossings,
    # not a divide-by-zero, just nothing happened.
    threshold = _GESTURE_CROSSING_FRAC * peak_dev
    crossing_times = []
    above = False
    for i in range(len(samples) if peak_dev > 0 else 0):
        dev = deviations[i]
        if not above and dev >= threshold:
            above = True
            crossing_times.append(samples[i][0])
        elif above and dev < threshold:
            above = False
    gaps = [crossing_times[i + 1] - crossing_times[i] for i in range(len(crossing_times) - 1)]

    return {
        "peak_deviation_mg": peak_dev,
        "ring_down_ms": ring_down_ms,
        "energy": energy,
        "duration_ms": duration_ms,
        "dominant_axis": _gesture_dominant_axis(samples[peak_idx]),
        "num_crossings": len(crossing_times),
        "spacing_mean_ms": _gesture_mean(gaps) if gaps else None,
        "spacing_stdev_ms": _gesture_stdev(gaps) if len(gaps) > 1 else None,
    }


# ─────────────────────────────────────────────────────────────
# Gesture envelope (recognizer) — gesture-envelope.md §4
# PURE — classifies WHAT physically happened (tap/flick/position/
# orientation), agnostic of current interaction state. What that means
# (an abstract GestureEvent, state-dependent) is the scrollwheel layer's
# job below, same split _classify_wake_response already draws for the
# older tap-count design. Every threshold here is a bare module global,
# same pattern _TapClassifier.advance already uses for DOUBLE_TAP_WINDOW_MS
# — not passed as a parameter, read directly, and overridable per-test via
# load_main(...) config overrides.
# ─────────────────────────────────────────────────────────────
def classify_tap_or_flick(features):
    """"tap", "flick", or None (below the trigger floor). Real-hardware
    testing found a real bug in an earlier version: treating "spacing_stdev
    unavailable" (< 3 crossings — true for ~70% of real flicks and ~25% of
    hard handling events, see FLICK_SPACING_STDEV_THRESHOLD_MS's comment)
    as automatic REJECTION silently killed almost every hard tap/flick,
    which is why shoulder taps never registered as anything at all
    (gesture-envelope.md §10). Fixed: when spacing IS computable, it's
    still the primary discriminator, unchanged. When it ISN'T,
    num_crossings is the best available single feature in that regime
    (~80%, 1 crossing leans flick, 2+ leans hard-handling) — not great,
    but confirmed via a cross-validated classifier on every available
    feature to be a real ceiling here, not a "combine more features" gap
    (gesture-envelope.md §10 has the full analysis)."""
    peak = features["peak_deviation_mg"]
    if peak < TAP_TRIGGER_THRESHOLD_MG:
        return None
    if peak >= FLICK_MAGNITUDE_THRESHOLD_MG:
        spacing = features["spacing_stdev_ms"]
        if spacing is not None:
            return "flick" if spacing >= FLICK_SPACING_STDEV_THRESHOLD_MS else None
        return "flick" if features["num_crossings"] <= 1 else None
    return "tap"


def classify_position(features):
    """"shoulder" or "base" — only meaningful if GESTURE_POSITION_ENABLED
    (insights.md §9: ~78-81% pooled even on a bottle it's tuned for, an
    optional signal, not a reliable one on its own). Returns None when the
    capability is off, same "capability flag gates the whole path" pattern
    GESTURE_FLIP_ENABLED uses for classify_orientation below."""
    if not GESTURE_POSITION_ENABLED:
        return None
    return "shoulder" if features["peak_deviation_mg"] >= POSITION_THRESHOLD_MG else "base"


def classify_orientation(sample):
    """One of ORIENTATION_MAP's state names, or "unclear" (mid-motion, or
    an axis/sign combination not in the map). A single steady-state
    (t, x, y, z) reading, NOT a captured window — different code path from
    classify_tap_or_flick/classify_position on purpose (gesture-envelope.md
    §3: orientation is steady-state, not a transient to window/classify)."""
    _, x, y, z = sample
    values = {"x": x * 0.061, "y": y * 0.061, "z": z * 0.061}
    axis = max(values, key=lambda a: abs(values[a]))
    value = values[axis]
    if abs(value) < ORIENTATION_STABLE_MG:
        return "unclear"
    sign = 1 if value > 0 else -1
    for name, map_axis, map_sign in ORIENTATION_MAP:
        if map_axis == axis and map_sign == sign:
            return name
    return "unclear"


def classify_valid_input(features):
    """V1 minimal contract (gesture-envelope.md §11) — deliberate touch
    vs. ambient handling, the ONLY distinction this path needs. energy
    alone: 98.4% across pooled tap sessions vs. pooled handling-noise
    sessions (pickup/carry/setdown/bump) — not a single-session number, and
    a much bigger margin than anything classify_tap_or_flick/
    classify_position ever reached (median tap energy ~27K vs. median
    handling-noise energy ~2.3M, nearly two orders of magnitude apart, not
    a close call). Deliberately does NOT distinguish tap from flick or
    classify position — this is the specialization gesture-envelope.md §11
    describes, not a replacement for classify_tap_or_flick, which stays
    defined and tested for when GESTURE_FLICK_ENABLED/GESTURE_POSITION_
    ENABLED come back on."""
    return features["energy"] < TAP_ENERGY_THRESHOLD


# ─────────────────────────────────────────────────────────────
# Gesture envelope (scrollwheel) — gesture-envelope.md §7
# The interaction state machine — what an abstract event MEANS, not what
# physically happened (that's the recognizer above). Same split
# _classify_wake_response already draws for the old design: "gesture A
# doesn't always mean X" happens here, not in the recognizer.
# ─────────────────────────────────────────────────────────────
class _GestureMenu:
    """The scrollwheel's own state — separate from _WakeState's
    AWAKE/ASLEEP (this is a layer on top: GESTURE_MODE is a state you can
    only be in while the display is otherwise AWAKE, per gesture-
    envelope.md §7). Same class-based pure-state-mutation style
    _WakeState/_StatusMessage already use."""

    def __init__(self, options):
        self.options = options
        self.active = False
        self.cursor = 0
        self.entered_at = None

    def wake(self, now_ms):
        """Enter GESTURE_MODE at cursor 0. Idempotent — waking while
        already active resets the cursor and the timeout, same "wake()
        also handles re-entry" pattern _WakeState.wake() uses."""
        self.active = True
        self.cursor = 0
        self.entered_at = now_ms

    def scroll(self, now_ms, direction):
        """direction: +1 or -1. No-op if not active. Wraps around the
        option list rather than clamping — a scrollwheel, not a slider.
        Refreshes the idle timeout (now_ms) — deliberately different from
        _WakeState's WAKE_MINUTES countdown, which does NOT auto-refresh
        (that's a power-budget decision, extending it needs its own
        deliberate double-tap gesture). GESTURE_MODE_TIMEOUT_MS is an idle
        timeout on an active interaction, not a power budget — a
        scrollwheel that can time out mid-browse just because the session
        ran long has no upside, same as an ATM or screensaver idle timer
        resets on activity, not on a fixed session clock."""
        if not self.active:
            return
        self.cursor = (self.cursor + direction) % len(self.options)
        self.entered_at = now_ms

    def select(self):
        """Returns the selected option's label, or None if not active.
        Exits GESTURE_MODE — one-shot, not sticky, same spirit as the old
        SECONDARY_ACTION dispatch firing once per tap."""
        if not self.active:
            return None
        selected = self.options[self.cursor]
        self.exit()
        return selected

    def exit(self):
        self.active = False
        self.entered_at = None

    def is_expired(self, now_ms):
        # Plain subtraction, not time.ticks_diff — same choice _WakeState
        # and _TapClassifier already made for comparisons over this short
        # a window (see their is_expired()/advance()).
        return (
            self.active
            and self.entered_at is not None
            and now_ms - self.entered_at >= GESTURE_MODE_TIMEOUT_MS
        )


def _classify_menu_response(menu_active, physical_gesture):
    """PURE: given whether the menu is currently active and what the
    recognizer detected this tick, decide the abstract response —
    "wake"/"select"/"scroll"/None. Mirrors _classify_wake_response's role
    for the old design exactly. Caller applies the resulting mutation via
    menu.wake()/.scroll()/.select() — this function only decides, same
    split as before."""
    if physical_gesture is None:
        return None
    if not menu_active:
        if physical_gesture in ("tap", "flick"):
            return "wake"
        return None
    if physical_gesture == "flick":
        return "select"
    if physical_gesture == "tap":
        return "scroll"
    return None


def _scroll_direction(position):
    """tap-shoulder = up/back, tap-base = down/forward — gesture-
    envelope.md §6's SCROLL(direction). Defaults to always-forward (+1)
    when GESTURE_POSITION_ENABLED is off or position wasn't classified,
    matching the design doc's stated fallback ("otherwise SCROLL fires
    with no direction" — a scrollwheel that only goes one way is still a
    scrollwheel, just a slower one)."""
    if position == "base":
        return -1
    return 1


# ─────────────────────────────────────────────────────────────
# Gesture envelope (v1 minimal contract) — gesture-envelope.md §11
# The two-phase ACK/CONFIRM state machine. Separate class from
# _GestureMenu/_WakeState above — those drive the richer scrollwheel
# design; this is the narrower, actually-shipping v1 path, built
# alongside them, not replacing them.
# ─────────────────────────────────────────────────────────────
class _TapCycleState:
    """ASLEEP -> WAKING -> SETTLING -> AWAKE, with CYCLING as a brief
    same-phase action rather than its own state (a flash+cut, not
    somewhere you can get stuck). Two-phase because classify_valid_input
    needs the full ~1200ms capture window to decide anything, which fails
    the "instant" feel a wake gesture needs on its own (§11's latency
    finding). acknowledge() marks a trigger the INSTANT it fires, before
    any verdict exists; resolve() applies the verdict once the window's
    capture completes — same class-based pure-state-mutation style
    _WakeState/_GestureMenu already use."""

    def __init__(self):
        self.awake = False  # v1 starts ASLEEP — no lights until a real tap
        #   wakes it, unlike the classic loop (which starts AWAKE)
        self.phase = "asleep"  # "asleep" | "waking" | "settling" | "awake"
        self.phase_started_at = None
        self.awake_until = None
        self.ack_pending = False

    def accepts_input(self):
        """False during WAKING/SETTLING — the debounce gesture-envelope.md
        §11 calls for, so the same physical contact that triggered WAKE
        can't also register as an immediate CYCLE."""
        return self.phase in ("asleep", "awake")

    def acknowledge(self):
        """Call the instant a trigger fires (caller already checked
        accepts_input() first) — before the capture window or any verdict
        exists. Purely a bookkeeping flag; the caller's own immediate
        ACK-flash print/render doesn't depend on this."""
        self.ack_pending = True

    def resolve(self, now_ms, valid):
        """Call once classify_valid_input's verdict on the completed
        capture is known. Returns "wake", "cycle", or None (noise, or a
        trigger that landed while WAKING/SETTLING — re-checked here since
        the capture window can outlast a phase change)."""
        self.ack_pending = False
        if not valid or not self.accepts_input():
            return None
        if not self.awake:
            self.awake = True
            self.phase = "waking"
            self.phase_started_at = now_ms
            return "wake"
        return "cycle"

    def advance(self, now_ms):
        """Call every tick — advances WAKING->SETTLING->AWAKE on their own
        timers, and AWAKE->ASLEEP on AWAKE_MINUTES timeout. Returns the
        phase just entered, or None if nothing changed this tick. Plain
        subtraction, not time.ticks_diff — same choice _WakeState/
        _TapClassifier/_GestureMenu already made for windows this short."""
        if self.phase == "waking" and now_ms - self.phase_started_at >= WAKE_JOLT_MS:
            self.phase = "settling"
            self.phase_started_at = now_ms
            return "settling"
        if self.phase == "settling" and now_ms - self.phase_started_at >= WAKE_SETTLE_MS:
            self.phase = "awake"
            self.awake_until = now_ms + AWAKE_MINUTES * 60_000
            return "awake"
        if self.phase == "awake" and self.awake_until is not None and now_ms >= self.awake_until:
            self.awake = False
            self.phase = "asleep"
            self.awake_until = None
            return "asleep"
        return None


_GESTURE_TRIGGER_BUFFER_LEN = 8  # rolling context for the trigger's cheap
#   "local baseline" — small and cheap, NOT the same thing as
#   extract_gesture_features()'s own median-of-the-whole-capture baseline
_GESTURE_WINDOW_MS = 1200  # fixed capture duration once triggered — see
#   _capture_gesture_window's docstring for the honest simplification this is

GESTURE_POLL_MS = getattr(config, "GESTURE_POLL_MS", 4)
#   ⚠ The trigger MUST poll faster than FRAME_MS. Every validated recognizer
#   number (95-98%, insights.md §8-9) was measured at 4ms/240Hz, and
#   gesture_sandbox.py's header records that polling at FRAME_MS (16ms)
#   instead was "a real cause of missed taps, not a hardware limit."
#   _run_interactive_loop therefore ticks at THIS rate and time-gates its
#   render at FRAME_MS — one more elapsed-gated task in the same cooperative
#   super-loop, not a second loop.

I2C_ERROR_PRINT_INTERVAL_MS = 1000


def _safe_read_accel(i2c, addr, now_ms, last_error_print):
    """Returns (raw_xyz_or_None, updated last_error_print). A jostled
    connection — plausible in a device whose input method is being tapped —
    raises OSError mid-read; skip that one sample rather than taking the
    whole display down. Ported from gesture_sandbox.py, where this was
    found the hard way (insights.md §10). Diagnostic throttled so a truly
    dead sensor can't flood the console at the poll rate."""
    try:
        return _imu_read_accel_raw(i2c, addr), last_error_print
    except OSError as e:
        if time.ticks_diff(now_ms, last_error_print) >= I2C_ERROR_PRINT_INTERVAL_MS:
            print(f"  ⚠ IMU read failed ({e}) — skipping sample; check wiring if this repeats")
            last_error_print = now_ms
        return None, last_error_print


def _tap_strength(dev_mg):
    """0..1, how hard the triggering contact read AT THE MOMENT OF CONTACT.
    Deliberately uses `dev` (deviation from the rolling baseline) rather
    than `energy`: energy is the accurate signal but isn't known until the
    capture window closes ~1.2s later, and the ACK has to render NOW. See
    gesture-envelope.md §11."""
    span = STRENGTH_MAX_DEV_MG - STRENGTH_MIN_DEV_MG
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (dev_mg - STRENGTH_MIN_DEV_MG) / span))


def _ack_flick(phase_ms, peak_mult, shelf_mult, ack_ms):
    """Rise to peak, then settle onto the "continental shelf" — a dim but
    NON-ZERO hold, not black. Real-hardware finding: dropping to black made
    ACK and CONFIRM read as two disconnected blips with a stall between
    them instead of one continuous gesture (gesture-envelope.md §11)."""
    half = ack_ms / 2
    if phase_ms < half:
        return (phase_ms / half) * peak_mult
    if phase_ms < ack_ms:
        return peak_mult + (shelf_mult - peak_mult) * ((phase_ms - half) / half)
    return shelf_mult


def _confirm_jolt_mult(phase_ms, start_mult):
    """Rises FROM the shelf (not from black) to WAKE_JOLT_BRIGHTNESS_MULT,
    then decays all the way to 0 — the shelf meant "still deciding", so
    decaying past it means "decided, done". Same rise:decay ratio as the
    boot burst, scaled to WAKE_JOLT_MS."""
    rise_ms = WAKE_JOLT_MS * (STARTUP_BURST_MS / (STARTUP_BURST_MS + STARTUP_FADE_MS))
    decay_ms = WAKE_JOLT_MS - rise_ms
    if phase_ms < rise_ms:
        return start_mult + (phase_ms / rise_ms) * (WAKE_JOLT_BRIGHTNESS_MULT - start_mult)
    decay_elapsed = phase_ms - rise_ms
    if decay_elapsed >= decay_ms:
        return 0.0
    return WAKE_JOLT_BRIGHTNESS_MULT * (1.0 - decay_elapsed / decay_ms)


def _capture_gesture_window(i2c, addr, start_ms):
    """Real hardware I/O — NOT host-testable, same category
    _imu_read_accel_raw already is. Fixed-duration capture, not adaptive
    settling-detection like the sandbox tools' human-gated stop-on-Enter —
    a real simplification worth naming: every validated recognizer
    threshold (insights.md §8-9) was tuned against sandbox captures that
    could run longer when a gesture needed it. Revisit if recognizer
    accuracy here doesn't match the sandbox numbers."""
    samples = []
    while True:
        now = time.ticks_ms()
        elapsed = now - start_ms
        samples.append((elapsed,) + _imu_read_accel_raw(i2c, addr))
        if elapsed >= _GESTURE_WINDOW_MS:
            break
        time.sleep_ms(4)  # matches vibration_sandbox.py's SAMPLE_INTERVAL_MS
    return samples


def _run_gesture_debug_loop():
    """Terminal-only validation of the gesture envelope
    (docs/contracts/gesture-envelope.md §7) — prints state transitions
    instead of touching LEDs, so the scrollwheel mechanism can be exercised
    over `make screen` before any real LED wiring exists for it. Gated by
    GESTURE_DEBUG_ENABLED, not WAKE_INTERACTION_ENABLED — a different,
    newer subsystem, deliberately isolated from the existing tested loop.

    Trigger design, honestly simplified for this first draft: a rolling
    buffer of recent magnitudes gives a cheap "local baseline" to compare
    the newest sample against at FRAME_MS cadence. Real handling motion
    crosses this too (insights.md §9's handling_test.py findings) — that's
    expected, the recognizer layer above (not this trigger) is what
    actually tells a gesture from noise. On trigger, captures a fixed
    _GESTURE_WINDOW_MS window at the sandbox tools' proven 240Hz rate —
    this blocks the loop for ~1.2s, the same accepted-tradeoff category
    the boot burst already established (a rare, bounded stall)."""
    i2c, addr = _get_imu()
    if addr is None:
        print("  ✗ No LSM6DSV16X found — check wiring (see imu_test.py)")
        return

    print("\n══ eki-bin gesture debug ═════════════════════════")
    print(f"  IMU confirmed at {hex(addr)}")
    print(f"  menu: {GESTURE_MENU_OPTIONS}")
    print(
        f"  flip: {GESTURE_FLIP_ENABLED}   position: {GESTURE_POSITION_ENABLED}"
        f"   flick: {GESTURE_FLICK_ENABLED}"
    )
    print("  tap/flick to interact — Ctrl+C to stop\n")

    menu = _GestureMenu(GESTURE_MENU_OPTIONS)
    trigger_buffer = []
    last_orientation = None

    try:
        while True:
            now_ms = time.ticks_ms()
            sample = (now_ms,) + _imu_read_accel_raw(i2c, addr)

            if GESTURE_FLIP_ENABLED:
                orientation = classify_orientation(sample)
                if orientation != last_orientation and orientation != "unclear":
                    print(f"  [ORIENTATION] {orientation}")
                    last_orientation = orientation

            mag = _gesture_magnitude_mg(sample)
            triggered = False
            if len(trigger_buffer) >= _GESTURE_TRIGGER_BUFFER_LEN:
                baseline = _gesture_median(trigger_buffer)
                triggered = abs(mag - baseline) >= TAP_TRIGGER_THRESHOLD_MG

            trigger_buffer.append(mag)
            if len(trigger_buffer) > _GESTURE_TRIGGER_BUFFER_LEN:
                trigger_buffer.pop(0)

            if triggered:
                samples = _capture_gesture_window(i2c, addr, now_ms)
                trigger_buffer = []  # the window already covers this stretch
                features = extract_gesture_features(samples)
                physical = classify_tap_or_flick(features)
                if physical == "flick" and not GESTURE_FLICK_ENABLED:
                    physical = None  # capability off — treat as noise
                if physical is not None:
                    position = classify_position(features)
                    response = _classify_menu_response(menu.active, physical)
                    now_ms = time.ticks_ms()  # stale after the blocking capture
                    if response == "wake":
                        menu.wake(now_ms)
                        print(f"  [WAKE] gesture mode active — cursor: {menu.options[menu.cursor]}")
                    elif response == "select":
                        selected = menu.select()
                        print(f"  [SELECT] {selected}")
                    elif response == "scroll":
                        direction = _scroll_direction(position)
                        menu.scroll(now_ms, direction)
                        arrow = "+" if direction > 0 else "-"
                        print(f"  [SCROLL {arrow}] cursor: {menu.options[menu.cursor]}")

            if menu.is_expired(now_ms):
                menu.exit()
                print("  [TIMEOUT] gesture mode exited")

            time.sleep_ms(FRAME_MS)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  gesture debug stopped")


# ─────────────────────────────────────────────────────────────
# LED status messages — docs/contracts/led-status-messages.md
#
# What used to live here: _imu_tap_detected (an always-False STUB),
# _TapClassifier (single-vs-double-tap disambiguation) and _WakeState.
# All three are gone — superseded by the v1 gesture contract
# (docs/contracts/gesture-envelope.md §11), which ships ONE gesture, so
# there is nothing to disambiguate, and whose _TapCycleState adds the
# WAKING/SETTLING debounce phases _WakeState lacked. The stub in
# particular was actively harmful: it made WAKE_INTERACTION_ENABLED=True
# sleep the display permanently with no way to wake it.
#
# _StatusMessage and _all_signals_hidden below are NOT superseded — the
# quiet-hours and no-data acknowledgments work exactly as designed.
# ─────────────────────────────────────────────────────────────

class _StatusMessage:
    """A brief single-LED acknowledgment (see
    docs/contracts/led-status-messages.md) — non-blocking by design: set
    once via show(), then rendered by the normal fast-tick loop until it
    expires, rather than its own blocking sleep loop (which would stall tap
    classification and schedule refresh for its whole duration)."""

    def __init__(self):
        self.color = None
        self.expires_at = None

    def show(self, now_ms, color, duration_ms):
        self.color = color
        self.expires_at = now_ms + duration_ms

    def active(self, now_ms):
        return self.expires_at is not None and now_ms < self.expires_at


# NOTE: there is deliberately no _classify_tap_response() to mirror the old
# _classify_wake_response(). The v1 state machine absorbed that job:
# _TapCycleState.resolve() already returns "wake"/"cycle"/None from
# (valid, awake), and the quiet-hours precedence that used to live in the
# classifier now sits in _run_interactive_loop's trigger branch — earlier,
# where it can skip the ~1.2s capture entirely instead of paying for it and
# then discarding the result. Two functions both deciding would be worse
# than one. Precedence still matches docs/contracts/led-status-messages.md.


def _capture_with_ack(i2c, addr, start_ms, peak_mult, shelf_mult):
    """Capture the recognizer's window while rendering the ACK on top of it.
    Real hardware I/O — not host-testable.

    The ACK *must* render from inside this loop: it is the only code running
    between "felt something" and "know what it was", and acknowledging
    before the verdict exists is the entire point of the two-phase design
    (gesture-envelope.md §11). Blocking ~1.2s is accepted — the boot burst
    set that precedent — and it reads as no stall at all, because the stall
    IS the ACK animation.

    Rise/dip animates; the shelf is written ONCE and then left alone.
    Repainting a held value every frame is exactly the low-brightness
    flicker bug this codebase has now hit four times. Both legs use the
    STATIC path deliberately: gamma crushes this low range toward black
    before it reaches the shelf's linear value, which was the real "dive
    underground to 0, then back up to a plateau" bug."""
    samples = []
    last_paint = start_ms
    shelf_written = False
    while True:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, start_ms)
        try:
            samples.append((elapsed,) + _imu_read_accel_raw(i2c, addr))
        except OSError:
            pass  # one dropped sample of ~300 is negligible; see _safe_read_accel
        if elapsed < ACK_HOLD_MS:
            if time.ticks_diff(now, last_paint) >= FRAME_MS:
                mult = _ack_flick(elapsed, peak_mult, shelf_mult, ACK_HOLD_MS)
                _write_frame([(STARTUP_COLOR, mult, "static")] * NUM_LEDS)
                last_paint = now
        elif not shelf_written:
            _write_frame([(STARTUP_COLOR, shelf_mult, "static")] * NUM_LEDS)
            shelf_written = True
        if elapsed >= _GESTURE_WINDOW_MS:
            break
        time.sleep_ms(GESTURE_POLL_MS)
    return samples


def _play_confirm_jolt(shelf_mult):
    """WAKE's response: rises from the shelf the ACK left behind, decays to
    black. Blocking ~WAKE_JOLT_MS, and deliberately so — by the time it
    returns, wall-clock time matching the WAKING phase has elapsed, so the
    caller's next tap_state.advance() finds it already due. No second timer
    to keep in sync with the animation."""
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= WAKE_JOLT_MS:
            break
        _write_frame([(STARTUP_COLOR, _confirm_jolt_mult(elapsed, shelf_mult))] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _play_cycle_flash():
    """CYCLE's response: flash + hard cut, deliberately simpler than WAKE's
    jolt. No crossfade — the same call CHASE's transition redesign made."""
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < CYCLE_TRANSITION_MS:
        _write_frame([(STARTUP_COLOR, 1.0, "static")] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _handle_tap(i2c, addr, trigger_ms, dev_mg, tap_state, signal, signal_b,
                status_message):
    """Trigger → capture (with live ACK) → classify → CONFIRM. Returns the
    dispatched response, or None if the contact was rejected as noise.

    Quiet hours is NOT checked here — the caller short-circuits before this
    is ever reached, so a quiet-hours tap never pays the ~1.2s capture.

    Strength scales both the ACK peak and the shelf from `dev`, the only
    signal available at trigger time (`energy` isn't known until the window
    closes). §11 records the honest consequence: dev and energy correlate,
    so the brightest ACKs are slightly MORE likely to end in rejection."""
    strength = _tap_strength(dev_mg)
    peak_mult = ACK_PEAK_FLOOR + strength * (ACK_PEAK_CEIL - ACK_PEAK_FLOOR)
    shelf_mult = SHELF_FLOOR + strength * (SHELF_CEIL - SHELF_FLOOR)

    tap_state.acknowledge()
    samples = _capture_with_ack(i2c, addr, trigger_ms, peak_mult, shelf_mult)
    features = extract_gesture_features(samples)
    valid = classify_valid_input(features)
    samples = None
    gc.collect()  # ~300 tuples, roughly 8-10KB. Reclaimed at a KNOWN point
    #   rather than whenever the allocator notices: transient spikes are what
    #   grow MicroPython's split heap at the IDF heap's expense, and it never
    #   hands that back (insights.md §11).

    now_ms = time.ticks_ms()  # stale after a ~1.2s blocking capture
    resolved = tap_state.resolve(now_ms, valid)
    if resolved == "wake":
        _play_confirm_jolt(shelf_mult)
        if _all_signals_hidden(signal, signal_b):
            status_message.show(time.ticks_ms(), NO_DATA_COLOR, NO_DATA_DURATION_MS)
    elif resolved == "cycle":
        _play_cycle_flash()
    else:
        clear()  # rejected — hard cut off the shelf, "decided: no"
    return resolved


def schedule_lines(schedule_data):
    """PURE: normalize EITHER schedule shape to a list of line dicts, so no
    caller ever has to branch on which format it was handed.

    Contract: docs/contracts/schedule-json.md § Multiple lines at one
    station. A file with `lines` returns it directly. A file without one is
    a single-line station, and the document itself IS that line — that shape
    is not deprecated, and normalizing here rather than at every use site is
    what keeps every pre-existing schedule working untouched (principle #9).

    Returns at least one entry, so `lines[i % len(lines)]` is always safe.
    Each entry may carry an optional "color" — the line's NOMINAL colour,
    which is what makes a line identifiable at a glance rather than only at
    the moment you cycle to it (gesture-envelope.md §11)."""
    lines = schedule_data.get("lines")
    if lines:
        return lines
    single = {"name": schedule_data.get("station", "line")}
    for period in ("weekday", "weekend"):
        if period in schedule_data:
            single[period] = schedule_data[period]
    return [single]


def _all_signals_hidden(signal, signal_b):
    """True if every active direction's LeaveSignal is HIDDEN (no catchable
    trains) — the trigger for the wake-to-no-data acknowledgment."""
    if signal.urgency is not HIDDEN:
        return False
    if signal_b is not None and signal_b.urgency is not HIDDEN:
        return False
    return True


def _cycle_brightness():
    """Advance BRIGHTNESS to the next value in BRIGHTNESS_PRESETS, wrapping
    around — the default SECONDARY_ACTION (a single tap while AWAKE). The
    visible brightness change IS the confirmation; no separate flash needed
    (see wake-interaction.md). Mutates the module-level BRIGHTNESS global
    directly — every render path already reads it fresh each frame (it was
    never a frozen import-time constant in practice, just never mutated
    until now), so nothing else needs to change to pick this up."""
    global BRIGHTNESS
    try:
        next_index = (BRIGHTNESS_PRESETS.index(BRIGHTNESS) + 1) % len(BRIGHTNESS_PRESETS)
    except ValueError:
        next_index = 0  # current BRIGHTNESS isn't one of the presets — start over
    BRIGHTNESS = BRIGHTNESS_PRESETS[next_index]
    return BRIGHTNESS


def _run_secondary_action():
    """Dispatch whatever SECONDARY_ACTION is configured. Only
    "brightness_cycle" exists today; deliberately pluggable rather than
    hardcoded to one behaviour (see wake-interaction.md) — an unrecognised
    SECONDARY_ACTION is a silent no-op, matching this codebase's
    getattr-default tolerance elsewhere (e.g. _render_dispatch's hasattr
    guard for render_dual)."""
    if SECONDARY_ACTION == "brightness_cycle":
        _cycle_brightness()


# ─────────────────────────────────────────────────────────────
# WiFi + NTP
# [→ Rust] embassy_net + CYW43 driver / replaced entirely by DS3231 in V2
# ─────────────────────────────────────────────────────────────
def connect_wifi():
    """Connect to WiFi, animating the loading-circle spin (see
    _draw_startup_circle) while polling — replaced a blocking `sleep(1)`
    poll loop that drew nothing at all, the main piece of real engineering
    the boot ceremony needed (the animation math itself was nothing new)."""
    # Reclaim before bringing the radio up. esp_wifi allocates real buffers
    # at active(True) and raises `OSError: Wifi Out of Memory` if the heap
    # can't serve them — a failure seen for real on the XIAO ESP32-C3 once
    # main.py passed ~2300 lines. Cheap insurance at a genuine high-water
    # mark; costs nothing on the roomier Pico 2W.
    #
    # ⚠ This does NOT rescue `mpremote run main.py` (i.e. `make run`), which
    # ships the whole ~115KB source over stdin to be held in RAM AND compiled
    # there — that peak happens before this line is ever reached. Run a file
    # this size from flash instead: `make upload`, then `make screen` + Ctrl+D
    # to soft-reset. See docs/provisioning-runbook.md § 6.
    if network is None:
        # No radio on this board AT ALL — `network` failed to import. This
        # is categorically different from "association failed": no
        # credential or signal change can fix it, and retrying is pointless.
        # The only resolution is TIME_SOURCE="rtc" (or a different board).
        print("  ✗ This board has no radio — `network` is unavailable.")
        print("    Set TIME_SOURCE='rtc' in config.py, then `make set-time`.")
        return False
    if not WIFI_SSID:
        # Reachable only with TIME_SOURCE="wifi" and no credentials set —
        # a config mistake, not a runtime failure. Say so plainly rather
        # than handing esp_wifi a None to choke on.
        print("  ✗ TIME_SOURCE='wifi' but WIFI_SSID is unset in config.py.")
        print("    Set credentials, or use TIME_SOURCE='rtc' + `make set-time`.")
        return False
    gc.collect()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("  Connecting to WiFi", end="")
    start = time.ticks_ms()
    dots_printed = 0
    while time.ticks_diff(time.ticks_ms(), start) < 20000:  # same ~20s budget
        if wlan.isconnected():                              # the old 20x sleep(1) had
            break
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _draw_startup_circle(elapsed)
        whole_seconds = elapsed // 1000
        if whole_seconds > dots_printed:
            dots_printed = whole_seconds
            print(".", end="")
        time.sleep_ms(FRAME_MS)
    print()
    if wlan.isconnected():
        print(f"  ✓ Connected  IP: {wlan.ifconfig()[0]}")
        return True
    print("  ✗ WiFi failed — check config.py")
    return False


def sync_ntp():
    if ntptime is None:
        # Unreachable through run_startup_sequence() (connect_wifi() fails
        # first and never returns), but explicit beats an AttributeError
        # surfacing as a confusing "NTP failed" below.
        print("  ✗ No radio on this board — cannot NTP sync.")
        return False
    try:
        ntptime.settime()
        print("  ✓ NTP sync OK")
        return True
    except Exception as e:
        print(f"  ✗ NTP failed: {e}")
        return False


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

        now, weekday = local_time()
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

            now, weekday = local_time()
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
