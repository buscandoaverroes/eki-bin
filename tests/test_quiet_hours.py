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
