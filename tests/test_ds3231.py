"""Host tests for fw.py's DS3231 integration.

Covers the pure parts: register decoding, the date→weekday computation, and
the plausibility gate. The I/O (`ds3231_now`, `ds3231_osc_stopped`) is
verified on the bench by `make rtc-test` and isn't reachable here.

Worth having because every failure in this layer produces output that LOOKS
FINE. Backwards BCD gives a clock that ticks and shows nonsense; an
off-by-one weekday silently serves the weekend timetable on a Monday. Neither
announces itself on hardware — you'd find them by missing a train.
"""

import datetime

import pytest


@pytest.fixture
def fw(load_main):
    """Fresh fw.py with default config — see tests/conftest.py."""
    return load_main()


def _regs(sec, minute, hour, dow, date, month, year_2digit, century=False):
    """Build a 7-byte register block the way the chip would."""
    def bcd(d):
        return ((d // 10) << 4) | (d % 10)
    return bytes([
        bcd(sec), bcd(minute), bcd(hour), bcd(dow), bcd(date),
        bcd(month) | (0x80 if century else 0), bcd(year_2digit),
    ])


class TestDecode:
    def test_round_trips_a_normal_timestamp(self, fw):
        assert fw.ds3231_decode(_regs(45, 2, 9, 1, 23, 8, 26)) == (
            2026, 8, 23, 9, 2, 45)

    def test_midnight_is_not_confused_with_noon(self, fw):
        assert fw.ds3231_decode(_regs(0, 0, 0, 1, 1, 1, 26))[3] == 0

    def test_century_bit_rolls_into_2100(self, fw):
        assert fw.ds3231_decode(
            _regs(0, 0, 0, 1, 1, 1, 5, century=True))[0] == 2105

    @pytest.mark.parametrize("hour_reg,expected", [
        (0x72, 12),  # 12-hour | PM | 12 -> noon stays 12
        (0x52, 0),   # 12-hour | AM | 12 -> midnight becomes 0
        (0x69, 21),  # 12-hour | PM | 09 -> 21:00
        (0x21, 21),  # 24-hour, plain BCD (bit5 is the twenties digit here)
    ])
    def test_twelve_hour_mode_handled_on_read(self, fw, hour_reg, expected):
        raw = bytearray(_regs(0, 0, 0, 1, 1, 1, 26))
        raw[2] = hour_reg
        assert fw.ds3231_decode(bytes(raw))[3] == expected

    def test_rejects_a_short_read(self, fw):
        with pytest.raises(ValueError):
            fw.ds3231_decode(b"\x00" * 6)


class TestDayOfWeek:
    """Computed from the date rather than read from register 0x03, whose
    1-7 value has no defined meaning. These pin the convention: 0=Monday."""

    @pytest.mark.parametrize("y,m,d", [
        (2026, 8, 23), (2026, 1, 1), (2024, 2, 29),   # leap day
        (2026, 12, 31), (2027, 3, 1), (2100, 3, 1),   # 2100 is NOT a leap year
    ])
    def test_matches_the_standard_library(self, fw, y, m, d):
        assert fw.day_of_week(y, m, d) == datetime.date(y, m, d).weekday()

    def test_the_reading_observed_on_hardware(self, fw):
        # rtc_test.py printed "2026-08-23 ... (weekday=6)" on the bench.
        assert fw.day_of_week(2026, 8, 23) == 6

    def test_weekend_boundary_is_where_current_period_expects_it(self, fw):
        # current_period() splits at >= 5, so Saturday must be 5.
        assert fw.day_of_week(2026, 8, 22) == 5
        assert fw.current_period(fw.day_of_week(2026, 8, 22)) == "weekend"
        assert fw.current_period(fw.day_of_week(2026, 8, 21)) == "weekday"


class TestPlausibility:
    def test_a_power_lost_chip_is_rejected(self, fw):
        # No working backup resets the chip to 2000-01-01 — a perfectly
        # valid-LOOKING timestamp, which is the whole point of this gate.
        assert not fw.ds3231_time_is_plausible((2000, 1, 1, 0, 0, 0))

    def test_a_normal_reading_passes(self, fw):
        assert fw.ds3231_time_is_plausible((2026, 8, 23, 9, 2, 45))

    @pytest.mark.parametrize("bad", [
        (2026, 13, 1, 0, 0, 0),   # month
        (2026, 0, 1, 0, 0, 0),
        (2026, 1, 32, 0, 0, 0),   # day
        (2026, 1, 1, 24, 0, 0),   # hour
        (2026, 1, 1, 0, 60, 0),   # minute
        (2100, 1, 1, 0, 0, 0),    # century-bit garble
    ])
    def test_garbled_fields_are_rejected(self, fw, bad):
        assert not fw.ds3231_time_is_plausible(bad)


class TestWiring:
    def test_ds3231_applies_no_utc_offset(self, load_main):
        """The chip stores LOCAL time (what rtc_test.py seeds), so the
        offset must be 0 — same as "rtc". Applying UTC_OFFSET_HOURS here
        would put the display 9 hours ahead of reality in Japan."""
        mod = load_main(TIME_SOURCE="ds3231", UTC_OFFSET_HOURS=9)
        assert mod._UTC_OFFSET_APPLIED == 0

    def test_wifi_still_applies_the_offset(self, load_main):
        """Guards the branch above from being over-applied: the WiFi path
        syncs NTP in UTC and genuinely needs the shift."""
        mod = load_main(TIME_SOURCE="wifi", UTC_OFFSET_HOURS=9)
        assert mod._UTC_OFFSET_APPLIED == 9

    def test_an_unknown_time_source_fails_loudly_at_import(self, load_main):
        """A typo previously fell through to the WiFi path, which on a
        radio-less board is an unrecoverable hang rather than an error."""
        with pytest.raises(ValueError):
            load_main(TIME_SOURCE="ds3232")

    def test_clock_error_colour_is_distinguishable_from_the_others(self, fw):
        """insights.md §12: through brown glass only near-opposite hues
        survive. A clock fault must not read as a WiFi fault to someone
        holding a jar with no laptop."""
        others = [fw.ERROR_COLOR, fw.SCHEDULE_ERROR_COLOR,
                  fw.CONFIG_ERROR_COLOR]
        clock = fw.CLOCK_ERROR_COLOR
        for other in others:
            # Dominant channel must differ — all three others peak on red.
            assert clock.index(max(clock)) != other.index(max(other))


class TestGeometryFits:
    """The anchor/arm geometry must fit NUM_LEDS.

    _arm_target() bounds offsets against each ARM length but never against
    the strip, so a config tuned for 21 LEDs run on 8 walks off the end of
    the frame. On hardware that appeared as a bare IndexError three calls
    deep in the render loop — after a clean boot, a correct clock and a
    correct timetable printout, none of which point at config.py.
    """

    def test_the_default_single_arm_geometry_fits(self, fw):
        assert fw.geometry_problems(num_leds=8, anchor=0, arm_a=7, arm_b=0) == []

    def test_the_21_led_config_on_an_8_led_strip_is_caught(self, fw):
        # The actual failing case observed on hardware.
        assert fw.geometry_problems(num_leds=8, anchor=10, arm_a=10, arm_b=10)

    def test_arm_a_running_past_the_end_is_caught(self, fw):
        problems = fw.geometry_problems(num_leds=8, anchor=0, arm_a=8, arm_b=0)
        assert len(problems) == 1 and "arm A" in problems[0]

    def test_arm_b_running_before_the_start_is_caught(self, fw):
        problems = fw.geometry_problems(num_leds=8, anchor=2, arm_a=5, arm_b=3)
        assert len(problems) == 1 and "arm B" in problems[0]

    def test_a_symmetric_bidirectional_geometry_fits(self, fw):
        assert fw.geometry_problems(num_leds=21, anchor=10, arm_a=10,
                                    arm_b=10) == []

    def test_an_off_strip_anchor_reports_once_not_three_times(self, fw):
        # Arm messages would all just restate the same root cause.
        assert len(fw.geometry_problems(num_leds=8, anchor=99,
                                        arm_a=3, arm_b=3)) == 1

    def test_the_message_names_the_value_to_change(self, fw):
        problems = fw.geometry_problems(num_leds=8, anchor=0, arm_a=12, arm_b=0)
        assert "ARM_A_LEN" in problems[0]
