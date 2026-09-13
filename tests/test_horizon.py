"""horizon.py — "there IS a train, just not near enough". insights.md §17.

The bug this fixes had no exception and no wrong number anywhere: every
component was individually correct and the composition was wrong. So
these tests are mostly about the SEAM — that stage 1 now asks stage 2 how
far it can see, and that the three states stay three.
"""

import importlib
import sys


def _load(load_main, **overrides):
    load_main(**overrides)
    for m in ("horizon", "signals"):
        sys.modules.pop(m, None)
    return importlib.import_module("horizon"), importlib.import_module("signals")


def _sig(signals_mod, ttls):
    """A LeaveSignal with these times-to-leave."""
    return signals_mod.LeaveSignal(list(ttls))


# ── the reach ────────────────────────────────────────────────────


def test_horizon_matches_the_renderer_not_a_parallel_estimate(load_main):
    """An arm of 10 LEDs at 2 min/LED reaches exactly 20 minutes, because
    _position_offset is ceil(ttl / POSITION_MINUTES_PER_LED) and
    _arm_target drops it past the arm. Any other derivation could drift
    from the renderer without either side being obviously wrong."""
    h, _s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                  POSITION_MINUTES_PER_LED=2)
    assert h.horizon_minutes() == 20


def test_arc_contracts_have_their_own_reach(load_main):
    h, _s = _load(load_main, CONTRACT="sandtimer", NUM_LEDS=21,
                  MINUTES_PER_LED=2)
    assert h.horizon_minutes() == 42


def test_asymmetric_arms_use_the_longer_one(load_main):
    """A train visible on either arm is visible."""
    h, _s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=4,
                  POSITION_MINUTES_PER_LED=2)
    assert h.horizon_minutes() == 20


# ── three states, kept three ─────────────────────────────────────


def test_the_live_case_from_the_field(load_main):
    """00:29, next train 305 minutes out, 20-minute horizon. The strip
    showed an anchor and markers and nothing else — correct, and
    indistinguishable from a broken jar."""
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.beyond_horizon(_sig(s, [305.5, 307.5, 329.5])) is True


def test_a_train_in_reach_is_not_beyond_it(load_main):
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.beyond_horizon(_sig(s, [8.0, 305.0])) is False


def test_no_trains_at_all_is_NOT_beyond_the_horizon(load_main):
    """THE distinction the module exists for. "Come back tomorrow" and
    "you missed the last train" are different facts, and collapsing them
    means the jar says the same thing at 00:30 and at 23:59 after the
    last service. HIDDEN keeps its own existing acknowledgment."""
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    empty = _sig(s, [])
    assert empty.urgency is s.HIDDEN
    assert h.beyond_horizon(empty) is False


def test_either_direction_being_in_reach_is_enough(load_main):
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.beyond_horizon(_sig(s, [305.0]), _sig(s, [6.0])) is False
    assert h.beyond_horizon(_sig(s, [305.0]), _sig(s, [280.0])) is True


# ── the morning schedule ─────────────────────────────────────────


def test_minutes_until_visible_is_the_whole_morning_feature(load_main):
    """Not what to draw — when to be awake. A 305-minute train with a
    20-minute horizon crosses in in 285 minutes."""
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.minutes_until_visible(_sig(s, [305.0])) == 285


def test_already_visible_means_nothing_to_wait_for(load_main):
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.minutes_until_visible(_sig(s, [8.0, 305.0])) is None


def test_no_trains_means_nothing_to_wait_for_either(load_main):
    """An empty schedule must not schedule a wake for a train that does
    not exist — the difference between a quiet night and a dead unit."""
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.minutes_until_visible(_sig(s, [])) is None


def test_the_soonest_train_across_both_arms_wins(load_main):
    h, s = _load(load_main, CONTRACT="approach", ARM_A_LEN=10, ARM_B_LEN=10,
                 POSITION_MINUTES_PER_LED=2)
    assert h.minutes_until_visible(_sig(s, [305.0]), _sig(s, [273.0])) == 253


# ── the state machine the ceremonies drive ───────────────────────


def test_sleep_goes_dark_immediately(load_main):
    """A wake that resolves to "nothing tonight" must not stay lit for the
    rest of AWAKE_MINUTES — that is the empty-promise render the ceremony
    replaces."""
    main = load_main()
    sys.modules.pop("gestures", None)
    g = importlib.import_module("gestures")
    st = g._TapCycleState()
    st.wake(0)
    assert st.awake
    st.sleep(1000)
    assert not st.awake and st.phase == "asleep"


def test_a_scheduled_wake_takes_the_same_path_as_a_tap(load_main):
    """wake() was split out of resolve() so the morning flower cannot
    drift from the tap path — a parallel implementation would."""
    main = load_main()
    sys.modules.pop("gestures", None)
    g = importlib.import_module("gestures")
    tapped, scheduled = g._TapCycleState(), g._TapCycleState()
    tapped.resolve(0, True)
    scheduled.wake(0)
    assert (tapped.awake, tapped.phase) == (scheduled.awake, scheduled.phase)
