# micropython/clock.py — eki-bin
# What time is it. All three TIME_SOURCE paths converge on local_time(),
# which returns (minutes_since_midnight, weekday) and nothing else — the
# rest of the firmware never learns where the time came from.
#
# Extracted from main.py by the V1.6 split (docs/v1.6-refactor.md).
#
# ⚠ THIS MODULE READS CLOCKS; IT DOES NOT DECIDE WHAT TO DISPLAY.
# _ds3231_local_time() RAISES ClockUnavailable rather than driving the
# failure display itself. The policy — that an untrustworthy clock goes dark
# instead of showing a plausible wrong time — is unchanged, but it now lives
# with the caller (_local_time_or_die in main.py). Extraction forced this:
# calling the failure display from here made clock depend on the startup
# sequence, which already depends on _check_ds3231_at_boot(). Circular.
#
# Reading a clock and deciding what to show are different jobs. The module
# boundary made that obvious in a way one big file never did.

import time

from machine import I2C, Pin

from settings import (DAY_END, DAY_START, RTC_I2C_ID, RTC_SCL_PIN,
    RTC_SDA_PIN, TIME_SOURCE, _UTC_OFFSET_APPLIED)

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

    ⚠ RAISES ClockUnavailable rather than guessing. The policy is
    unchanged — a plausible-looking wrong time is the worst output this
    device can produce, because it makes you miss the train while believing
    you won't — but the DECISION to go dark now belongs to the caller
    (_local_time_or_die in main.py), not here.

    That split was forced by the V1.6 extraction and is a genuine
    improvement: calling the failure display from here made clock.py depend
    on the startup sequence, while run_startup_sequence() already depends on
    _check_ds3231_at_boot() below — a circular import. Reading a clock and
    deciding what to show are different jobs, and the module boundary made
    that obvious in a way the single file never did.

    The offset arithmetic mirrors the WiFi path exactly, even though
    _UTC_OFFSET_APPLIED is 0 here, so that switching the chip to UTC storage
    later is a one-constant change rather than a rewrite."""
    year, month, day, hour, minute, _second = ds3231_now()
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


def daylight_period(minutes):
    """PURE: 'day' or 'night' for a minutes-since-midnight value.

    Sibling of current_period() above — both answer "which named span of
    time is this?", which is why they live together rather than one of
    them sitting next to is_quiet() over in schedule.py.

    The window is [DAY_START, DAY_END) and MAY wrap past midnight, tested
    the same way is_quiet() tests its own wrap. Two degenerate cases fall
    out of the arithmetic rather than needing to be special-cased, which
    is what makes the feature switchable from config alone:

        DAY_START_HOUR == DAY_END_HOUR  → empty window → always 'night'
        DAY_START_HOUR 0, DAY_END_HOUR 24 → always 'day'

    (QUIET_START_HOUR = 24 is the same trick, already used as the
    quiet-hours escape hatch during testing.)
    """
    if DAY_START == DAY_END:
        return "night"
    if DAY_START < DAY_END:
        return "day" if DAY_START <= minutes < DAY_END else "night"
    # Wrapped window (e.g. a 20:00-06:00 "day"): the gap is the complement,
    # so test with OR, not a range — same shape as is_quiet().
    return "day" if (minutes >= DAY_START or minutes < DAY_END) else "night"


def fmt_time(minutes):
    """Format minutes-since-midnight as HH:MM."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


