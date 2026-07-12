"""Stage 1 — time → abstract signal. Pure logic, no LEDs."""


def test_drops_uncatchable_trains(load_main):
    m = load_main(WALK_TO_STATION_MINS=2.5)
    assert m.time_to_leave(2) is None      # 2 min away, 2.5 walk → can't make it
    assert m.time_to_leave(10) == 7.5      # catchable
    assert m.time_to_leave(None) is None


def test_classify_bands(load_main):
    m = load_main(URGENCY_THRESHOLDS=(2, 5))
    assert m.classify(None) is m.HIDDEN
    assert m.classify(1.9) is m.LEVEL_1
    assert m.classify(2) is m.LEVEL_2       # band edge is exclusive below
    assert m.classify(4.9) is m.LEVEL_2
    assert m.classify(5) is m.LEVEL_3
    assert m.classify(99) is m.LEVEL_3


def test_classify_follows_config_thresholds(load_main):
    m = load_main(URGENCY_THRESHOLDS=(3, 8))
    assert m.classify(2.9) is m.LEVEL_1
    assert m.classify(3) is m.LEVEL_2
    assert m.classify(8) is m.LEVEL_3


def test_leave_signal_end_to_end(load_main):
    m = load_main(WALK_TO_STATION_MINS=2.5)
    # trains at minutes-of-day 4, 9, 14 with now=0 → minutes-until = 4, 9, 14
    sig = m.leave_signal([4, 9, 14], 0)
    assert sig.ttls == [1.5, 6.5, 11.5]
    assert sig.primary == 1.5
    assert sig.urgency is m.LEVEL_1


def test_leave_signal_empty_when_none_catchable(load_main):
    m = load_main()
    sig = m.leave_signal([], 0)
    assert sig.ttls == []
    assert sig.primary is None
    assert sig.urgency is m.HIDDEN
