"""Regression tests for the night gate — the bug that ate a whole evening of
testing because the strip was correctly dark after 23:00."""


def test_2324_is_quiet(load_main):
    """The actual case: 23:24 with default quiet hours → strip dark by design."""
    m = load_main(QUIET_START_HOUR=23, QUIET_END_HOUR=6)
    assert m.is_quiet(23 * 60 + 24) is True


def test_quiet_window_boundaries(load_main):
    m = load_main(QUIET_START_HOUR=23, QUIET_END_HOUR=6)
    assert m.is_quiet(22 * 60 + 59) is False  # just before — awake
    assert m.is_quiet(23 * 60) is True         # 23:00 — quiet starts
    assert m.is_quiet(5 * 60 + 59) is True      # still night
    assert m.is_quiet(6 * 60) is False          # 06:00 — wakes (end exclusive)


def test_quiet_can_be_disabled(load_main):
    """QUIET_START_HOUR=24 / QUIET_END_HOUR=0 → never quiet (the testing escape)."""
    m = load_main(QUIET_START_HOUR=24, QUIET_END_HOUR=0)
    assert not any(m.is_quiet(t) for t in range(0, 24 * 60))


# ── Window shapes: wrapping, same-day, disabled, empty, full ───────────────
# Same [start, end) rules as clock.py's day/night window (test_day_night.py).

MINUTES_PER_DAY = 24 * 60


def _quiet_minutes(m):
    """Every minute of the day at which the strip is dark."""
    return [t for t in range(MINUTES_PER_DAY) if m.is_quiet(t)]


def test_default_window_wraps_midnight(load_main):
    m = load_main(QUIET_START_HOUR=23, QUIET_END_HOUR=6)
    assert m.is_quiet(MINUTES_PER_DAY - 1) is True  # 23:59
    assert m.is_quiet(0) is True                    # 00:00 — still night


def test_default_window_covers_exactly_seven_hours(load_main):
    """23:00 → 06:00 wraps: 60 min before midnight + 360 after."""
    m = load_main(QUIET_START_HOUR=23, QUIET_END_HOUR=6)
    assert len(_quiet_minutes(m)) == 7 * 60


def test_non_wrapping_window(load_main):
    """01:00 → 05:00 doesn't wrap. The old OR form returned True at 10:00
    (`600 >= 60`) — the jar would have been dark all day."""
    m = load_main(QUIET_START_HOUR=1, QUIET_END_HOUR=5)
    assert m.is_quiet(10 * 60) is False         # the bug
    assert m.is_quiet(23 * 60) is False
    assert m.is_quiet(0) is False               # midnight — before the window
    assert m.is_quiet(60 - 1) is False          # 00:59 — just before
    assert m.is_quiet(60) is True               # 01:00 — quiet starts
    assert m.is_quiet(5 * 60 - 1) is True       # 04:59 — still quiet
    assert m.is_quiet(5 * 60) is False          # 05:00 — wakes (end exclusive)
    assert _quiet_minutes(m) == list(range(60, 5 * 60))


def test_disabled_is_never_quiet_any_minute(load_main):
    m = load_main(QUIET_START_HOUR=24, QUIET_END_HOUR=0)
    assert _quiet_minutes(m) == []


def test_equal_start_end_is_never_quiet(load_main):
    """start == end is an empty window, not a full day — a typo shouldn't
    leave the jar dark around the clock."""
    for hour in (0, 6, 23, 24):
        m = load_main(QUIET_START_HOUR=hour, QUIET_END_HOUR=hour)
        assert _quiet_minutes(m) == [], f"{hour} → {hour} should never be quiet"


def test_zero_to_24_is_always_quiet(load_main):
    """The explicit always-dark spelling, for symmetry with 24 → 0."""
    m = load_main(QUIET_START_HOUR=0, QUIET_END_HOUR=24)
    assert len(_quiet_minutes(m)) == MINUTES_PER_DAY
