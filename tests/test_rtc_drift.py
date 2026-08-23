"""Host tests for scripts/rtc_drift.py.

Covers the two pure parts: BCD register decoding and the drift arithmetic.
Deliberately does NOT touch mpremote or hardware -- collect() is I/O and is
verified on the bench, but a backwards BCD decoder or an inverted drift sign
would produce numbers that look entirely plausible while being wrong, which
is exactly the failure a host test can catch and a bench session can't.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "rtc_drift", Path(__file__).resolve().parent.parent / "scripts" / "rtc_drift.py"
)
rtc_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtc_drift)


def _regs(sec, minute, hour, dow, date, month, year_2digit, century=False):
    """Build a 7-byte DS3231 register block the way the chip would."""
    def bcd(d):
        return ((d // 10) << 4) | (d % 10)
    return bytes([
        bcd(sec), bcd(minute), bcd(hour), bcd(dow), bcd(date),
        bcd(month) | (0x80 if century else 0), bcd(year_2digit),
    ])


class TestDecode:
    def test_round_trips_a_normal_timestamp(self):
        raw = _regs(45, 2, 9, 6, 23, 8, 26)
        assert rtc_drift.decode_registers(raw) == datetime(2026, 8, 23, 9, 2, 45)

    def test_midnight_is_not_confused_with_noon(self):
        # The classic 12-hour bug: 00:00 and 12:00 both encode as "12".
        assert rtc_drift.decode_registers(_regs(0, 0, 0, 1, 1, 1, 26)).hour == 0

    def test_power_lost_chip_reads_as_year_2000(self):
        # A DS3231 with no working backup resets here -- observed on hardware,
        # and the anchor that tells you the battery isn't doing its job.
        assert rtc_drift.decode_registers(_regs(0, 0, 0, 1, 1, 1, 0)).year == 2000

    def test_century_bit_rolls_into_2100(self):
        assert rtc_drift.decode_registers(_regs(0, 0, 0, 1, 1, 1, 5, century=True)).year == 2105

    # Hour register 0x02: bit6 = 12-hour mode, and ONLY THEN is bit5 the
    # PM flag -- in 24-hour mode bit5 is the twenties digit. Setting bit5
    # without bit6 therefore encodes a completely different hour, which is
    # how the first draft of this test "failed" against a correct decoder.
    @pytest.mark.parametrize("hour_reg,expected", [
        (0x72, 12),  # 12-hour | PM | 12 -> noon stays 12
        (0x52, 0),   # 12-hour | AM | 12 -> midnight becomes 0
        (0x69, 21),  # 12-hour | PM | 09 -> 21:00
        (0x49, 9),   # 12-hour | AM | 09 -> 09:00
        (0x21, 21),  # 24-hour, plain BCD 21 -> 21:00 (bit5 = twenties)
    ])
    def test_twelve_hour_mode_is_handled_on_read(self, hour_reg, expected):
        # This script never WRITES the chip, so it can be handed one left in
        # 12-hour mode by other tooling.
        raw = bytearray(_regs(0, 0, 0, 1, 1, 1, 26))
        raw[2] = hour_reg
        assert rtc_drift.decode_registers(bytes(raw)).hour == expected

    def test_rejects_a_short_read(self):
        with pytest.raises(ValueError):
            rtc_drift.decode_registers(b"\x00" * 6)


class TestDriftMath:
    def test_a_chip_gaining_time_reads_positive(self):
        # +1s gained over one day = 1/86400 = ~11.57 ppm
        ppm = rtc_drift.drift_ppm(0.0, 0.0, 1.0, 86400.0)
        assert ppm == pytest.approx(11.574, abs=0.01)

    def test_sign_inverts_for_a_slow_chip(self):
        assert rtc_drift.drift_ppm(0.0, 0.0, -1.0, 86400.0) < 0

    def test_constant_timezone_bias_subtracts_away(self):
        """The whole reason this tool ignores UTC-vs-local: a chip holding
        UTC while the host is JST shows a constant -9h offset, and drift
        must be identical to the same chip holding local time."""
        tz = -9 * 3600
        local = rtc_drift.drift_ppm(0.0, 0.0, 1.0, 86400.0)
        utc = rtc_drift.drift_ppm(tz, 0.0, tz + 1.0, 86400.0)
        assert local == pytest.approx(utc)

    def test_spec_drift_is_a_sixth_of_a_second_per_day(self):
        # Anchors the number the whole design rests on: 2 ppm = 0.173 s/day.
        # If this ever fails, the units are wrong somewhere.
        assert 2.0 * 86400 / 1e6 == pytest.approx(0.1728, abs=1e-4)

    def test_zero_baseline_returns_none_not_infinity(self):
        # An immediate re-run must read as "not yet known" rather than
        # dividing by ~0 and reporting a spectacular fake drift.
        assert rtc_drift.drift_ppm(0.0, 100.0, 0.5, 100.0) is None


class TestLeastSquaresFit:
    """Preferred over two-point differencing once there are 3+ samples: the
    host clock is not a fixed reference (macOS slews it against NTP), and a
    two-point measurement folds any such step straight into the answer."""

    def test_a_clean_line_recovers_its_slope(self):
        # 1 s/day = 1/86400 = ~11.574 ppm
        per_sec = 1.0 / 86400
        samples = [(i * 3600.0, i * 3600.0 * per_sec) for i in range(6)]
        assert rtc_drift.drift_ppm_fit(samples) == pytest.approx(11.574, abs=0.01)

    def test_two_samples_agree_with_the_two_point_form(self):
        samples = [(0.0, 0.0), (86400.0, 1.0)]
        assert rtc_drift.drift_ppm_fit(samples) == pytest.approx(
            rtc_drift.drift_ppm(0.0, 0.0, 1.0, 86400.0))

    def test_a_step_at_the_END_is_only_partly_diluted(self):
        """⚠ The fit helps here but does NOT rescue you. The last sample
        carries the highest leverage in a least-squares slope, so a host
        correction landing at the end still moves the answer a long way:
        5.56 ppm two-point becomes 3.97 ppm fitted, not ~0.

        The real defence against this is a LONGER span, not a cleverer fit
        — accumulated drift has to outgrow the size of a plausible NTP
        correction."""
        stepped = [(i * 3600.0, 0.0) for i in range(6)]
        stepped[-1] = (stepped[-1][0], 0.1)  # host jumped 100ms at the end
        two_point = rtc_drift.drift_ppm(
            stepped[0][1], stepped[0][0], stepped[-1][1], stepped[-1][0])
        fitted = rtc_drift.drift_ppm_fit(stepped)
        assert abs(fitted) < abs(two_point)
        assert abs(fitted) == pytest.approx(3.97, abs=0.05)

    def test_a_step_in_the_MIDDLE_is_almost_entirely_rejected(self):
        """Where the fit genuinely earns its keep: an interior outlier is
        outvoted by the samples either side of it."""
        stepped = [(i * 3600.0, 0.0) for i in range(6)]
        stepped[2] = (stepped[2][0], 0.1)
        assert abs(rtc_drift.drift_ppm_fit(stepped)) < 1.0

    def test_constant_offset_is_zero_drift(self):
        # A chip keeping perfect time at any fixed offset (e.g. a timezone
        # difference) must read as no drift at all.
        assert rtc_drift.drift_ppm_fit(
            [(i * 3600.0, -9 * 3600.0) for i in range(5)]) == pytest.approx(0.0)

    def test_too_few_samples_returns_none(self):
        assert rtc_drift.drift_ppm_fit([(0.0, 0.0)]) is None
        assert rtc_drift.drift_ppm_fit([]) is None

    def test_samples_all_at_one_instant_return_none(self):
        assert rtc_drift.drift_ppm_fit([(5.0, 0.0), (5.0, 1.0)]) is None
