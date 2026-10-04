"""The raw-sensor sandbox (micropython/imu_stream.py + scripts/imu_record.py).

Pure parts only: the batch wire format, the intent label map, and segment
reconstruction with undo. The streamer itself talks to I2C and is verified on
the bench by its own once-a-second `stat` record (achieved Hz, worst gap).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "micropython"))
sys.path.insert(0, str(ROOT / "scripts"))

import imu_record as rec  # noqa: E402
import interaction_log as host  # noqa: E402
import interlog  # noqa: E402


# ── wire format ───────────────────────────────────────────────────────────
def test_batch_roundtrips_through_the_host_parser():
    rows = [(0, 1, -2, 3, 4, -5, 6, 3), (4166, -7, 8, 9, 10, 11, -12, 3)]
    out = host.parse_line(interlog.fmt_batch(123456, rows), now=9.0)
    assert out["k"] == "b" and out["t0"] == 123456 and out["h"] == 9.0
    assert out["d"] == [list(r) for r in rows]


def test_stat_roundtrips():
    out = host.parse_line(interlog.fmt_stat(2_000_000, 480, 239.8, 5200, 0), 1.0)
    assert out["k"] == "t" and out["n"] == 480 and out["hz"] == pytest.approx(239.8)
    assert out["max_gap_us"] == 5200 and out["err"] == 0


def test_odr_codes_match_the_two_confirmed_values():
    assert interlog.ODR_CODES[60] == 0x05        # imu_test.py
    assert interlog.ODR_CODES[240] == 0x07       # gestures.py
    assert interlog.ODR_CODES[480] == interlog.ODR_CODES[240] + 1   # doubling series
    assert set(rec.ODRS) == set(interlog.ODR_CODES)


# ── the intent labels ─────────────────────────────────────────────────────
def test_keys_are_unique_right_hand_and_do_not_collide_with_undo_or_quit():
    keys = list(rec.POINTS) + list(rec.STATES)
    assert len(keys) == len(set(keys))
    assert "q" not in keys
    assert not set(host.UNDO_KEYS) & set(keys)


def test_labels_describe_what_the_human_did_not_what_the_bottle_did():
    names = set(rec.POINTS.values()) | set(rec.STATES.values())
    assert not {n for n in names if n.startswith(("true_", "false_", "missed_"))}
    for needed in ("tap_top", "tap_body", "tap_base", "knock_table", "lift",
                   "set_down", "grab", "rest_lean", "tilting"):
        assert needed in names


def test_point_record_has_an_id_and_unknown_keys_are_ignored():
    assert rec.point_record("u", 5.0, 3) == {"k": "l", "h": 5.0, "id": 3, "label": "knock_table"}
    assert rec.point_record("z", 5.0, 3) is None


# ── states and segments ───────────────────────────────────────────────────
def test_pressing_a_state_key_twice_starts_then_ends_it():
    r1, cur = rec.state_toggle("m", 1.0, 1, None)
    assert (r1["state"], r1["edge"], cur) == ("rest_lean", "start", "rest_lean")
    r2, cur = rec.state_toggle("m", 9.0, 2, cur)
    assert (r2["edge"], cur) == ("end", None)


def _stream(*steps):
    cur, out = None, []
    for i, (key, t) in enumerate(steps, 1):
        r, cur = rec.state_toggle(key, t, i, cur)
        out.append(r)
    return out


def test_segments_cover_the_interval_and_switching_closes_the_previous():
    recs = _stream(("n", 10.0), ("m", 40.0), ("m", 100.0))
    assert rec.segments(recs, end_h=200.0) == [
        ("rest_flat", 10.0, 40.0), ("rest_lean", 40.0, 100.0)]


def test_an_open_state_closes_at_the_end_of_the_recording():
    assert rec.segments(_stream((".", 5.0)), end_h=60.0) == [("tilting", 5.0, 60.0)]


def test_undo_voids_a_state_edge_without_deleting_it():
    recs = _stream(("m", 10.0), ("m", 70.0))
    recs.append({"k": "l", "h": 71.0, "undo": 2})          # undo the END
    assert rec.segments(recs, end_h=90.0) == [("rest_lean", 10.0, 90.0)]
    assert len(recs) == 3


def test_effective_drops_undone_points():
    recs = [rec.point_record("7", 1.0, 1), rec.point_record("8", 2.0, 2),
            {"k": "l", "h": 3.0, "undo": 1}]
    assert [r["label"] for r in rec.effective(recs)] == ["tap_body"]
