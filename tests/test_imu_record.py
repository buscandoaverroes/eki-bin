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


# ── compact batch codec ───────────────────────────────────────────────────
def test_packed_rows_are_15_bytes_and_roundtrip():
    rows = [(0, 1, -2, 3, 4, -5, 6, 3), (4166, -32768, 32767, 0, 100, -100, 7, 255)]
    assert len(interlog.pack_rows(rows)) == 2 * interlog.ROW_BYTES == 30
    line = interlog.fmt_batch_b64(777, rows)
    assert interlog.decode_batch_b64(
        host.parse_line.__globals__["json"].loads(line[len(interlog.TAG):])["b"], 2) \
        == [list(r) for r in rows]


def test_the_host_expands_a_compact_batch_into_the_readable_form():
    rows = [(0, 1, 2, 3, 4, 5, 6, 3), (4000, 7, 8, 9, 10, 11, 12, 3)]
    out = host.parse_line(interlog.fmt_batch_b64(123, rows), now=4.5)
    assert out == {"k": "b", "h": 4.5, "t0": 123, "d": [list(r) for r in rows]}


def test_an_undecodable_batch_is_kept_not_fatal():
    bad = interlog.TAG + '{"k":"B","t0":1,"n":3,"b":"AAAA"}'
    out = host.parse_line(bad, 1.0)
    assert out["k"] == "x" and out["bad"] is True


def test_compact_is_meaningfully_smaller_than_text():
    # realistic magnitudes: gyro near zero, accel near 1 g
    rows = [(i * 4166, -62, 3, 40, -250, 20, 16000, 3) for i in range(20)]
    ratio = len(interlog.fmt_batch_b64(0, rows)) / len(interlog.fmt_batch(0, rows))
    assert ratio < 0.7, ratio


def test_time_is_stored_as_deltas_and_restored_as_offsets_from_batch_start():
    rows = [(0, 1, 1, 1, 1, 1, 1, 3), (4166, 2, 2, 2, 2, 2, 2, 3), (8400, 3, 3, 3, 3, 3, 3, 3)]
    out = host.parse_line(interlog.fmt_batch_b64(0, rows), 0)
    assert [r[0] for r in out["d"]] == [0, 4166, 8400]


def test_a_gap_too_big_for_a_uint16_delta_is_refused_not_wrapped():
    with pytest.raises(ValueError):
        interlog.pack_rows([(0, 0, 0, 0, 0, 0, 0, 3), (70000, 0, 0, 0, 0, 0, 0, 3)])


# ── ending states, and stopping cleanly ───────────────────────────────────
def test_end_current_closes_whatever_is_open_and_is_a_noop_otherwise():
    assert rec.end_current(5.0, 9, None) is None
    r = rec.end_current(5.0, 9, "rest_lean")
    assert (r["state"], r["edge"], r["id"]) == ("rest_lean", "end", 9)
    assert rec.segments([_stream(("m", 1.0))[0], r], end_h=99.0) == [("rest_lean", 1.0, 5.0)]


def test_end_key_does_not_collide():
    assert rec.END_STATE_KEY not in rec.POINTS and rec.END_STATE_KEY not in rec.STATES
    assert rec.END_STATE_KEY not in host.UNDO_KEYS and rec.END_STATE_KEY != "q"


def test_stop_child_stops_a_cooperative_process_without_a_traceback():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    host.stop_child(p, patience=(2, 1, 1))
    assert p.poll() is not None


def test_stop_child_escalates_past_a_process_that_ignores_sigint():
    import subprocess
    code = "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)"
    p = subprocess.Popen([sys.executable, "-c", code])
    import time as _t
    _t.sleep(0.3)                                      # let it install the handler
    host.stop_child(p, patience=(0.3, 2, 1))
    assert p.poll() is not None


def test_gyro_full_scale_codes_are_ordered_and_default_is_wide():
    codes = interlog.GYRO_FS_CODES
    assert [codes[k] for k in sorted(codes)] == sorted(codes.values())   # monotonic
    assert interlog.STREAM_GYRO_FS in codes and interlog.STREAM_GYRO_FS >= 500


def test_hot_path_functions_do_not_import():
    """Per-call imports cost a serial round trip each under `mpremote mount`
    (a same-named .py is searched for on the mounted path first) and halved
    the stream rate on 2026-10-04. Applies to anything called per batch."""
    import ast
    tree = ast.parse((ROOT / "micropython" / "interlog.py").read_text())
    hot = {"pack_rows", "fmt_batch_b64", "fmt_stat", "fmt_sample", "fmt_event"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in hot:
            imports = [n for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom))]
            assert not imports, f"{node.name} imports inside the function"


def test_corrections_void_relabel_and_add_without_mutating_the_recording():
    recs = [rec.point_record("p", 1.0, 1)]                       # recorded as "release"
    recs += _stream(("," , 10.0))                                # hand_hold start, id 1
    recs[1]["id"] = 2
    wrong = rec.state_toggle("m", 40.0, 3, "hand_hold")[0]       # meant to END hold
    recs.append(wrong)
    entry = {"void": [3], "relabel": {"release": "let_go"},
             "add": [{"k": "l", "h": 40.0, "id": "fix", "state": "hand_hold", "edge": "end"}]}
    before = [dict(r) for r in recs]
    fixed = rec.apply_corrections(recs, entry)
    assert recs == before                                         # input untouched
    assert [r.get("label") for r in fixed if "label" in r] == ["let_go"]
    assert rec.segments(fixed, end_h=99.0) == [("hand_hold", 10.0, 40.0)]


def test_no_entry_means_no_change():
    recs = [rec.point_record("7", 1.0, 1)]
    assert rec.apply_corrections(recs, None) is recs
