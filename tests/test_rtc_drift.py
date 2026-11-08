"""Host tests for scripts/rtc_drift.py.

Covers the two pure parts: BCD register decoding and the drift arithmetic.
Deliberately does NOT touch mpremote or hardware -- collect() is I/O and is
verified on the bench, but a backwards BCD decoder or an inverted drift sign
would produce numbers that look entirely plausible while being wrong, which
is exactly the failure a host test can catch and a bench session can't.
"""

import struct

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


class TestScatterCheck:
    """The honesty check. A long elapsed time alone was enough for the tool
    to call a figure "meaningful" — which it did on 2026-08-23 over samples
    whose two segments disagreed by 17.5 ppm. Elapsed time says the signal
    COULD be big enough; only scatter says the data actually fits a line.
    """

    def test_a_clean_line_has_no_scatter(self):
        per_sec = 1.0 / 86400
        samples = [(i * 3600.0, i * 3600.0 * per_sec) for i in range(6)]
        assert rtc_drift.fit_rms_residual(samples) == pytest.approx(0.0, abs=1e-9)

    def test_a_moving_reference_shows_up_as_scatter(self):
        # Drift-free chip, host stepping +/-50ms between samples.
        steps = [0.0, 0.05, -0.05, 0.05, -0.05, 0.0]
        samples = [(i * 3600.0, steps[i]) for i in range(6)]
        rms = rtc_drift.fit_rms_residual(samples)
        assert rms > 0.03, "a 50ms reference step must be visible as scatter"

    def test_scatter_is_independent_of_the_slope(self):
        """Real drift must NOT register as scatter — otherwise the check
        would fire on exactly the chips it's meant to measure."""
        per_sec = 20.0 / 1e6  # a wildly out-of-spec 20 ppm, but constant
        samples = [(i * 3600.0, i * 3600.0 * per_sec) for i in range(6)]
        assert rtc_drift.fit_rms_residual(samples) == pytest.approx(0.0, abs=1e-9)

    def test_the_real_2026_08_23_data_is_flagged(self):
        """The observed samples: two segments at +11.94 and -5.54 ppm. No
        TCXO does that, and the tool must not report a slope as if it had."""
        samples = [(0.0, -1.6644), (8154.9, -1.567), (47275.1, -1.7836)]
        rms = rtc_drift.fit_rms_residual(samples)
        assert rms * 1000 > 5 * 4.0, "must exceed 5x the ~4ms jitter"

    def test_fit_line_returns_none_when_undefined(self):
        assert rtc_drift.fit_line([(1.0, 0.0)]) is None
        assert rtc_drift.fit_line([(5.0, 0.0), (5.0, 1.0)]) is None


class TestNtpOffset:
    """The NTP offset maths, tested against synthetic replies.

    Worth pinning because a sign error here would DOUBLE the error this is
    meant to remove, silently — the numbers would still look plausible. The
    socket work is separated out so this needs no network.
    """

    @staticmethod
    def _reply(server_recv, server_send):
        """A 48-byte NTP reply carrying the two server timestamps."""
        def stamp(unix_seconds):
            ntp = unix_seconds + 2208988800
            return struct.pack("!II", int(ntp), int((ntp % 1) * 2 ** 32))
        return b"\x00" * 32 + stamp(server_recv) + stamp(server_send)

    def test_a_perfectly_synced_host_reads_zero(self):
        # Host sends at 1000, server sees 1000.05 both ways, host gets it at
        # 1000.1 — symmetric 100ms round trip, no clock error.
        data = self._reply(1000.05, 1000.05)
        off = rtc_drift.ntp_offset_from_reply(data, t1=1000.0, t4=1000.1)
        assert off == pytest.approx(0.0, abs=1e-3)

    def test_a_host_running_SLOW_gets_a_POSITIVE_offset(self):
        """Sign check. A host 5s behind must be told to ADD 5s."""
        data = self._reply(1005.05, 1005.05)
        off = rtc_drift.ntp_offset_from_reply(data, t1=1000.0, t4=1000.1)
        assert off == pytest.approx(5.0, abs=1e-2)

    def test_a_host_running_FAST_gets_a_NEGATIVE_offset(self):
        data = self._reply(995.05, 995.05)
        off = rtc_drift.ntp_offset_from_reply(data, t1=1000.0, t4=1000.1)
        assert off == pytest.approx(-5.0, abs=1e-2)

    def test_round_trip_latency_cancels(self):
        """The whole point of the four-timestamp form: a slow link must not
        masquerade as clock error."""
        fast = rtc_drift.ntp_offset_from_reply(
            self._reply(1000.005, 1000.005), t1=1000.0, t4=1000.01)
        slow = rtc_drift.ntp_offset_from_reply(
            self._reply(1000.25, 1000.25), t1=1000.0, t4=1000.5)
        assert fast == pytest.approx(slow, abs=1e-2)

    def test_a_short_reply_is_rejected(self):
        with pytest.raises(OSError):
            rtc_drift.ntp_offset_from_reply(b"\x00" * 20, t1=0.0, t4=0.1)


class TestSummary:
    """The derived rollup. Pure, so the arithmetic AND the honesty flags are
    testable without hardware or a network."""

    @staticmethod
    def _s(ts, offset, ref="ntp", jitter=4.0, epoch=0):
        return {"event": "sample", "ts": ts, "offset_s": offset, "ref": ref,
                "jitter_ms": jitter, "epoch": epoch, "iso_host": "t%d" % ts}

    def test_empty_log_reports_nothing_rather_than_crashing(self):
        s = rtc_drift.build_summary([])
        assert s["current"] is None and s["history"] == []

    def test_two_samples_give_a_figure_but_NOT_trust(self):
        """The distinction that matters: a number can be inside the spec band
        and still be meaningless. Two points always fit a line perfectly, so
        zero scatter proves nothing."""
        s = rtc_drift.build_summary([self._s(0, 0.0), self._s(86400.0, -0.05)])
        c = s["current"]
        assert c["drift_ppm"] == pytest.approx(-0.579, abs=0.01)
        assert c["within_spec"] is True
        assert c["trustworthy"] is False
        assert "no scatter check" in c["why"]

    def test_three_consistent_samples_are_trusted(self):
        per_s = -0.6 / 1e6
        rows = [self._s(i * 86400.0, i * 86400.0 * per_s) for i in range(3)]
        c = rtc_drift.build_summary(rows)["current"]
        assert c["trustworthy"] is True
        assert c["drift_ppm"] == pytest.approx(-0.6, abs=0.01)

    def test_a_wandering_reference_is_flagged_untrustworthy(self):
        # Drift-free chip, reference stepping ±300ms — vastly above jitter.
        steps = [0.0, 0.3, -0.3, 0.3, -0.3]
        rows = [self._s(i * 86400.0, steps[i]) for i in range(5)]
        c = rtc_drift.build_summary(rows)["current"]
        assert c["trustworthy"] is False
        assert "scatter" in c["why"]

    def test_host_referenced_samples_are_excluded_and_counted(self):
        rows = [self._s(0, 5.0, ref="host"), self._s(100.0, 9.0, ref="host"),
                self._s(200.0, 0.0), self._s(86400.0, -0.05)]
        s = rtc_drift.build_summary(rows)
        assert s["excluded_host_referenced"] == 2
        assert s["current"]["samples"] == 2      # only the NTP pair
        assert s["log_samples_total"] == 4       # history keeps everything

    def test_history_carries_running_deltas(self):
        h = rtc_drift.build_summary(
            [self._s(0, -1.0), self._s(86400.0, -1.05)])["history"]
        assert h[0]["delta_s"] is None
        assert h[1]["delta_s"] == pytest.approx(-0.05)

    def test_out_of_spec_drift_is_reported_as_such(self):
        per_s = 12.0 / 1e6           # 12 ppm, like the early bad readings
        rows = [self._s(i * 86400.0, i * 86400.0 * per_s) for i in range(3)]
        c = rtc_drift.build_summary(rows)["current"]
        assert c["within_spec"] is False
        assert c["trustworthy"] is True   # consistent, just bad


# ── units, and corrections applied at read time ──────────────────────
# Added 2026-10-21. One unit-agnostic log let a sample from a second
# DS3231 (seeded 2026-09-13, never labelled) very probably land in
# bottle-01's history on 2026-09-29, making its drift appear to double.

def _s(ts, off, **kw):
    return dict({"ts": ts, "event": "sample", "ref": "ntp", "offset_s": off,
                 "jitter_ms": 3.0, "iso_host": "t%d" % ts}, **kw)


def _seed(ts, **kw):
    return dict({"ts": ts, "event": "seed", "iso_host": "seed%d" % ts}, **kw)


# The real epoch-1 history, as logged (stored epoch 1, no unit field).
_DAY = 86400.0
_SEP3, _SEP13 = 1788432862.35, 1788432862.35 + 10.06 * _DAY
_REAL = [
    _seed(_SEP3, epoch=1),
    _s(1788432872.75, -0.8517, epoch=1),          # Sep 3, just after seeding
    _s(1790686025.85, -2.0139, epoch=1),          # Sep 29
    _s(1792586000.00, -3.8680, epoch=1),          # Oct 21
]
_CORR = {
    "legacy_unit": "bottle-01",
    "add": [_seed(_SEP13, unit="bottle-01", confidence=0.7,
                  note="re-seeded the night the IMU was rebuilt")],
}


class TestUnitsAndCorrections:
    def test_legacy_entries_get_the_legacy_unit(self):
        view = rtc_drift.apply_corrections(_REAL, {"legacy_unit": "bottle-01"})
        assert {e["unit"] for e in view} == {"bottle-01"}

    def test_unitless_entries_belong_to_nobody(self):
        """Excluded rather than guessed — guessing is the bug."""
        assert rtc_drift.for_unit(_REAL, "bottle-01") == []

    def test_without_corrections_the_stored_epochs_are_reproduced(self):
        """Renumbering from seeds must not change an honest log."""
        log = [_s(1, 0.0, epoch=0), _s(2, 0.1, epoch=0), _seed(3, epoch=1),
               _s(4, 0.0, epoch=1)]
        view = rtc_drift.apply_corrections(log, {})
        assert [e["epoch"] for e in view] == [0, 0, 1, 1]

    def test_an_inferred_seed_regroups_the_samples_after_it(self):
        """THE case. The stored field still says epoch 1 for Sep 29 and
        Oct 21; deriving epochs from seeds moves them behind the Sep 13
        seed, which is what an after-the-fact seed has to mean."""
        view = rtc_drift.apply_corrections(_REAL, _CORR)
        samples = [e for e in view if e["event"] == "sample"]
        assert [e["epoch"] for e in samples] == [1, 2, 2]

    def test_removing_the_correction_restores_the_original_grouping(self):
        """The 30%: if the Sep 13 seed was another unit after all, deleting
        one entry from the corrections file must put everything back."""
        view = rtc_drift.apply_corrections(_REAL, {"legacy_unit": "bottle-01"})
        assert [e["epoch"] for e in view if e["event"] == "sample"] == [1, 1, 1]

    def test_the_log_itself_is_never_modified(self):
        before = [dict(e) for e in _REAL]
        rtc_drift.apply_corrections(_REAL, dict(_CORR, void=[_REAL[2]["ts"]]))
        assert _REAL == before

    def test_void_drops_a_sample(self):
        view = rtc_drift.apply_corrections(_REAL, dict(_CORR, void=[_REAL[3]["ts"]]))
        assert -3.868 not in [e["offset_s"] for e in view if e["event"] == "sample"]

    def test_one_units_seed_does_not_move_anothers_epoch(self):
        log = [_s(1, 0.0, unit="a"), _s(2, 0.0, unit="b"),
               _seed(3, unit="b"), _s(4, 0.0, unit="a"), _s(5, 0.0, unit="b")]
        view = rtc_drift.renumber_epochs(log)
        assert [e["epoch"] for e in view if e.get("unit") == "a"] == [0, 0]
        assert [e["epoch"] for e in view if e.get("unit") == "b"] == [0, 1, 1]

    def test_the_real_samples_under_both_readings(self):
        """Pins the 2026-10-21 analysis to the actual numbers. One history
        needs the rate to nearly double; with the inferred seed the two
        later samples sit on one rate — and are honestly UNtrusted, since
        two samples admit no scatter check."""
        h1 = rtc_drift.build_summary(rtc_drift.apply_corrections(
            _REAL, {"legacy_unit": "bottle-01"}))
        assert h1["current"]["samples"] == 3 and not h1["current"]["trustworthy"]
        assert "baseline_inferred" not in h1

        h2 = rtc_drift.build_summary(rtc_drift.apply_corrections(_REAL, _CORR))
        cur = h2["current"]
        assert cur["epoch"] == 2 and cur["samples"] == 2
        assert -1.0 < cur["drift_ppm"] < -0.95
        assert cur["trustworthy"] is False

    def test_an_inferred_baseline_is_flagged_in_the_summary(self):
        """A figure measured from an inferred seed is a different claim from
        one measured from an observed one, and the number alone cannot say
        which. The summary has to."""
        out = rtc_drift.build_summary(rtc_drift.apply_corrections(_REAL, _CORR))
        assert out["baseline_inferred"]["confidence"] == 0.7


class TestRefusesToWriteWithoutAUnit:
    def test_sampling_without_a_unit_writes_nothing(self, tmp_path):
        """Checked before NTP or the board are touched — this test would
        hang or fail on the network if it weren't."""
        log = tmp_path / "log.jsonl"
        with pytest.raises(SystemExit) as exc:
            rtc_drift.main(["--log", str(log), "--corrections",
                            str(tmp_path / "none.json")])
        assert "which unit" in str(exc.value)
        assert not log.exists()

    def test_a_seed_without_a_unit_writes_nothing(self, tmp_path):
        log = tmp_path / "log.jsonl"
        with pytest.raises(SystemExit):
            rtc_drift.main(["--mark-seed", "--log", str(log),
                            "--corrections", str(tmp_path / "none.json")])
        assert not log.exists()

    def test_a_seed_records_its_unit(self, tmp_path):
        log = tmp_path / "log.jsonl"
        rtc_drift.main(["--mark-seed", "--unit", "bottle-02", "--log", str(log),
                        "--corrections", str(tmp_path / "none.json")])
        entry = rtc_drift.load_log(log)[0]
        assert entry["event"] == "seed" and entry["unit"] == "bottle-02"
