"""interlog.py + scripts/interaction_log.py — Phase 0 of docs/imu-interaction-plan.md.

The recorder is only worth having if the records are trustworthy, so this
pins the wire format (host parsing what the device prints), the adaptive rate
(an idle bottle must not produce a gigabyte a day, and the lead-in to an event
must not be thinned), and that the capture-window rows stay aligned with the
gyro rows. What it cannot test: whether the gyro register/units are right on
real silicon — that is the first bench check, and the raw LSB are logged so
the conversion can be corrected on the host without re-recording.
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "micropython"))
sys.path.insert(0, str(ROOT / "scripts"))

import interaction_log as host  # noqa: E402
import interlog  # noqa: E402


# ── wire format: what the device prints is what the host parses ───────────
def test_sample_roundtrips_through_the_host_parser():
    line = interlog.fmt_sample(1234, (1, -2, 3), (4, -5, 6))
    rec = host.parse_line(line, now=99.5)
    assert rec == {"k": "s", "t": 1234, "a": [1, -2, 3], "g": [4, -5, 6], "h": 99.5}


def test_sample_with_failed_gyro_read_is_null_not_dropped():
    rec = host.parse_line(interlog.fmt_sample(1, (0, 0, 0), None), 0)
    assert rec["g"] is None


def test_event_fields_are_typed_and_sorted():
    line = interlog.fmt_event(50, "trigger", dev=812.4567, quiet=False, who=None)
    rec = host.parse_line(line, 1.0)
    assert rec["e"] == "trigger" and rec["quiet"] is False and rec["who"] is None
    assert rec["dev"] == pytest.approx(812.457)


def test_event_string_values_are_escaped():
    rec = host.parse_line(interlog.fmt_event(1, "n", text='a "b" \\ c'), 0)
    assert rec["text"] == 'a "b" \\ c'


def test_capture_chunks_reassemble_to_the_original_rows():
    rows = [(i * 4, i, -i, 2 * i, 10 + i, 20 + i, 30 + i) for i in range(47)]
    lines = interlog.fmt_capture_chunks(9000, rows)
    assert len(lines) == 3                      # 20 + 20 + 7
    got = []
    for ln in lines:
        rec = host.parse_line(ln, 0)
        assert rec["k"] == "c" and rec["t0"] == 9000
        assert rec["i"] == len(got)
        got.extend(tuple(r) for r in rec["rows"])
    assert got == rows


def test_untagged_console_output_is_kept_as_text():
    rec = host.parse_line("  [LINE] Yamanote\n", 3.0)
    assert rec == {"k": "x", "h": 3.0, "text": "  [LINE] Yamanote"}


def test_truncated_tagged_line_is_kept_not_fatal():
    rec = host.parse_line(interlog.TAG + '{"k":"s","t":12', 1.0)
    assert rec["k"] == "x" and rec["bad"] is True


def test_blank_lines_are_ignored():
    assert host.parse_line("\r\n", 0) is None


def test_meta_snapshot_skips_absent_knobs():
    class S:
        TAP_ENERGY_THRESHOLD = 100000
        TILT_ENABLED = True
    meta = interlog.snapshot(S)
    assert meta == {"TAP_ENERGY_THRESHOLD": 100000, "TILT_ENABLED": True}
    rec = host.parse_line(interlog.fmt_meta(0, meta), 0)
    assert rec["TILT_ENABLED"] is True


# ── labels and the header ─────────────────────────────────────────────────
def test_every_documented_key_makes_a_label_and_others_do_not():
    for key, name in host.LABELS.items():
        assert host.label_record(key, 5.0) == {"k": "l", "h": 5.0, "label": name}
    assert host.label_record("z", 5.0) is None


def test_header_names_the_unit_and_mount():
    h = host.header_record("bottle-01", "base", None, "abc123", 0)
    assert h["unit"] == "bottle-01" and h["mount"] == "base" and h["note"] == ""


def test_output_filename_carries_the_unit():
    p = host.out_path("data", "bottle-01", 0)
    assert p.name.startswith("interaction-bottle-01-") and p.suffix == ".jsonl"


# ── adaptive rate ─────────────────────────────────────────────────────────
STILL = (0, 0, -16384)


def _run(seq):
    d = interlog.Decimator()
    return [d.keep(t, a, g) for t, a, g in seq]


def test_idle_is_thinned_to_idle_hz():
    # one sample per 4 ms for 10 s of a bottle sitting still
    kept = sum(_run((t, STILL, (0, 0, 0)) for t in range(0, 10_000, 4)))
    assert kept <= 10 * interlog.IDLE_HZ + 2
    assert kept >= 10 * interlog.IDLE_HZ - 2


def test_motion_switches_to_active_rate_and_holds():
    seq = [(t, STILL, (0, 0, 0)) for t in range(0, 4000, 4)]
    # a shove at t=4000: accel jumps
    seq += [(4000 + i * 4, (0, 900, -16384), (0, 0, 0)) for i in range(50)]
    # then stillness again — must stay ACTIVE for HOLD_MS
    seq += [(4200 + i * 4, STILL, (0, 0, 0)) for i in range(1000)]
    d = interlog.Decimator()
    kept_t = [t for t, a, g in seq if d.keep(t, a, g)]
    during_hold = [t for t in kept_t if 4200 <= t < 4200 + interlog.HOLD_MS]
    expected = interlog.HOLD_MS // (1000 // interlog.ACTIVE_HZ)
    assert len(during_hold) >= expected - 3, "the lead-out must not be thinned"
    after = [t for t in kept_t if t >= 4200 + interlog.HOLD_MS + 500]
    gaps = [b - a for a, b in zip(after, after[1:])]
    assert all(g >= 1000 // interlog.IDLE_HZ - 4 for g in gaps), "back to idle rate"


def test_gyro_alone_counts_as_motion():
    d = interlog.Decimator()
    d.keep(0, STILL, (0, 0, 0))
    d.keep(300, STILL, (0, 0, 0))                     # idle
    assert d.keep(320, STILL, (900, 0, 0)) is True    # rotation, accel unchanged
    assert d.keep(340, STILL, (0, 0, 0)) is True      # held at ACTIVE_HZ


# ── the Stream, against a fake I2C ─────────────────────────────────────────
class FakeI2C:
    def __init__(self, gyro=(0, 0, 0), fail=False):
        self.gyro, self.fail, self.written = gyro, fail, []

    def writeto_mem(self, addr, reg, data):
        self.written.append((reg, bytes(data)))

    def readfrom_mem(self, addr, reg, n):
        if self.fail:
            raise OSError(5)
        assert reg == 0x22 and n == 6
        out = b""
        for v in self.gyro:
            out += (v & 0xFFFF).to_bytes(2, "little")
        return out


def test_read_gyro_raw_is_signed():
    assert interlog.read_gyro_raw(FakeI2C((-2, 300, -32768)), 0x6A) == (-2, 300, -32768)


def test_stream_powers_the_gyro_on_construction():
    i2c = FakeI2C()
    interlog.Stream(i2c, 0x6A)
    assert i2c.written == [(0x11, bytes([0x07]))]


def test_capture_rows_stay_aligned_when_gyro_read_fails(capsys, monkeypatch):
    monkeypatch.setattr(time, "ticks_ms", lambda: 0, raising=False)
    i2c = FakeI2C((7, 8, 9))
    s = interlog.Stream(i2c, 0x6A)
    samples = [(0, 1, 2, 3), (4, 4, 5, 6), (8, 7, 8, 9)]
    s.cap_sample(i2c, 0x6A, 0)
    i2c.fail = True                                  # one bad gyro read
    s.cap_sample(i2c, 0x6A, 4)
    i2c.fail = False
    s.cap_sample(i2c, 0x6A, 8)
    s.cap_done(1000, samples, {"energy": 12.5}, True)
    recs = [host.parse_line(l, 0) for l in capsys.readouterr().out.splitlines()]
    rows = [r for rec in recs if rec["k"] == "c" for r in rec["rows"]]
    assert rows == [[0, 1, 2, 3, 7, 8, 9], [4, 4, 5, 6, 0, 0, 0], [8, 7, 8, 9, 7, 8, 9]]
    end = [r for r in recs if r["k"] == "e"][0]
    assert end["e"] == "capture_end" and end["valid"] is True and end["rows"] == 3


def test_tilt_events_only_on_change(capsys):
    class Ctl:
        engaged, deg, rejected = False, 0.0, 0

    s = interlog.Stream(FakeI2C(), 0x6A)
    ctl = Ctl()
    for _ in range(50):
        s.tilt(1, "idle", ctl)                       # 50 identical reports
    ctl.engaged = True
    s.tilt(2, "up", ctl)
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 2
