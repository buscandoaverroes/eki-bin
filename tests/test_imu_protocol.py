"""Guided trials (scripts/imu_protocol.py): the cue is the label, so the
records it writes ARE the dataset's ground truth. These pin what a session
file will contain for each thing a person might do — including messing up."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import imu_protocol as p  # noqa: E402


def _guide(order="TGH", rest=4.0, start_at=1):
    trials = [(k, "body" if k == "T" else None) for k in order]
    g = p.Guide(trials, rest_s=rest, start_at=start_at)
    g.begin(0.0)
    return g


def test_the_session_plan_is_the_one_published_on_2026_10_25():
    plan = p.plan("tap-vs-grab")
    kinds = "".join(k for k, _ in plan)
    assert len(plan) == 68 and kinds.startswith("HGTHDTTTDT") and kinds.endswith("DTTDTGTG")
    assert kinds.count("T") == 30 and kinds.count("G") + kinds.count("H") == 30


def test_tap_locations_rotate_and_only_trials_that_tap_get_one():
    plan = p.plan("tap-vs-grab")
    taps = [w for k, w in plan if k in "TD"]
    assert taps[:3] == ["body", "top", "base"]
    assert all(w is None for k, w in plan if k in "GH")
    assert max(taps.count(w) for w in p.WHERE) - min(taps.count(w) for w in p.WHERE) <= 1


def test_every_instruction_is_written_out_and_names_the_place():
    for kind in p.KINDS:
        title, how = p.describe(kind, "top")
        assert title and "{" not in how
    assert "top" in p.describe("T", "top")[1]


def test_countdown_then_go_then_space_keeps_it():
    g = _guide()
    assert g.phase == "rest" and g.countdown(0.0) == 4 and g.countdown(3.5) == 1
    assert g.tick(3.9) == []
    go = g.tick(4.0)
    assert go[0]["edge"] == "go" and go[0]["trial"] == 1 and go[0]["type"] == "T"
    assert go[0]["where"] == "body" and go[0]["attempt"] == 1
    recs, handled = g.key(" ", 6.0)
    assert handled and recs[0]["status"] == "ok" and g.current == 2 and g.phase == "rest"


def test_r_during_a_trial_keeps_the_attempt_and_repeats_it():
    g = _guide()
    g.tick(4.0)
    recs, _ = g.key("r", 5.0)
    assert recs[0]["status"] == "redo"
    assert g.current == 1                       # the same trial again…
    g.tick(9.0)
    assert g.attempts[1] == 2                   # …as attempt 2


def test_r_in_the_next_countdown_rejudges_the_one_just_done():
    g = _guide()
    g.tick(4.0)
    g.key(" ", 6.0)                             # kept…
    recs, _ = g.key("r", 7.0)                   # …then "no, I messed that up"
    assert recs[0] == {"k": "l", "h": 7.0, "trial": 1, "attempt": 1,
                       "edge": "verdict", "status": "redo"}
    assert g.current == 1 and g.queue[0] == 2   # redo 1, then carry on with 2
    assert 1 not in g.kept


def test_r_twice_does_not_queue_the_trial_twice():
    g = _guide()
    g.tick(4.0)
    g.key(" ", 6.0)
    g.key("r", 7.0)
    recs, handled = g.key("r", 7.5)
    assert handled and recs == [] and g.queue.count(1) == 0 and g.current == 1


def test_space_during_a_countdown_is_swallowed_not_a_label():
    g = _guide()
    assert g.key(" ", 1.0) == ([], True) and g.phase == "rest"


def test_other_keys_fall_through_to_the_ordinary_labels():
    g = _guide()
    g.tick(4.0)
    assert g.key("h", 5.0) == ([], False)


def test_a_stall_voids_a_running_trial_and_the_resume_repeats_it():
    g = _guide()
    g.tick(4.0)
    recs = g.stall(5.0)
    assert recs[0]["status"] == "stalled" and g.phase == "paused"
    g.resume(20.0)
    assert g.phase == "rest" and g.current == 1


def test_a_stall_in_a_countdown_loses_nothing():
    g = _guide()
    assert g.stall(1.0) == [] and g.phase == "paused"
    g.resume(5.0)
    assert g.current == 1 and g.attempts == {}


def test_the_last_trial_finishes_the_session():
    g = _guide("T")
    g.tick(4.0)
    g.key(" ", 5.0)
    assert g.phase == "finished"
    assert g.summary() == ({"T": 1}, 0)


def test_start_at_resumes_part_way():
    g = _guide("TGH", start_at=3)
    assert g.current == 3 and g.queue == []


def test_quitting_mid_trial_closes_it():
    g = _guide()
    g.tick(4.0)
    assert g.abandon(5.0)[0]["status"] == "abandoned"
    assert _guide().abandon(1.0) == []          # nothing running: nothing to close


def test_trials_reads_back_one_row_per_attempt_with_verdicts_applied():
    g = _guide()
    recs = []
    recs += g.tick(4.0)
    recs += g.key(" ", 6.0)[0]
    recs += g.key("r", 7.0)[0]                  # trial 1 re-judged
    recs += g.tick(11.0)
    recs += g.key(" ", 13.0)[0]                 # trial 1, attempt 2, kept
    recs += g.tick(17.0)                        # trial 2 cut off
    rows = p.trials(recs + [{"k": "b"}, {"k": "l", "label": "mark", "h": 5.0}])
    assert [(r["trial"], r["attempt"], r["status"]) for r in rows] == [
        (1, 1, "redo"), (1, 2, "ok"), (2, 1, None)]
    assert rows[1]["go"] == 11.0 and rows[1]["done"] == 13.0 and rows[0]["where"] == "body"


def test_the_announcement_says_what_comes_next():
    g = _guide()
    text = g.announce()
    assert "1/3" in text and "TAP" in text and "body" in text and "then: grab and tilt" in text


def test_a_double_pressed_space_cannot_end_the_next_trial():
    g = _guide()
    g.tick(4.0)
    assert g.key(" ", 4.1) == ([], True) and g.phase == "go"
    assert g.key(" ", 4.0 + p.MIN_TRIAL_S)[0][0]["status"] == "ok"
