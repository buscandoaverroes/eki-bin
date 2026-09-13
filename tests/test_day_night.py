"""Day/night brightness profile — insights.md §14.

Sibling of test_quiet_hours.py, and the separation is the point: quiet
hours decides WHETHER the strip lights up, this decides HOW BRIGHT. They
are tested apart because they are answerable apart.
"""


# ── daylight_period: pure time classification ────────────────────


def test_default_window_is_day_at_noon(load_main):
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17)
    assert m.daylight_period(12 * 60) == "day"


def test_window_boundaries(load_main):
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17)
    assert m.daylight_period(6 * 60 + 59) == "night"  # just before
    assert m.daylight_period(7 * 60) == "day"          # 07:00 — inclusive
    assert m.daylight_period(16 * 60 + 59) == "day"    # still day
    assert m.daylight_period(17 * 60) == "night"       # 17:00 — exclusive


def test_equal_hours_is_always_night(load_main):
    """The 'off' escape, mirroring QUIET_START_HOUR=24."""
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=7)
    assert all(m.daylight_period(t) == "night" for t in range(0, 24 * 60))


def test_zero_to_24_is_always_day(load_main):
    m = load_main(DAY_START_HOUR=0, DAY_END_HOUR=24)
    assert all(m.daylight_period(t) == "day" for t in range(0, 24 * 60))


def test_window_may_wrap_past_midnight(load_main):
    """Not a real configuration, but the arithmetic must not silently
    invert — is_quiet() wraps, so its sibling has to as well."""
    m = load_main(DAY_START_HOUR=20, DAY_END_HOUR=6)
    assert m.daylight_period(22 * 60) == "day"
    assert m.daylight_period(2 * 60) == "day"
    assert m.daylight_period(12 * 60) == "night"


# ── _apply_daylight: the edge-triggered mutation ─────────────────


def test_first_call_applies_unconditionally(load_main):
    """last_period=None is boot: there is no edge yet, but brightness must
    still be correct before the first frame renders."""
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    assert m._apply_daylight(12 * 60, None) == "day"
    assert m.settings.BRIGHTNESS == 0.4


def test_night_gets_the_night_value(load_main):
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    assert m._apply_daylight(22 * 60, None) == "night"
    assert m.settings.BRIGHTNESS == 0.1


def test_transition_switches_brightness(load_main):
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    period = m._apply_daylight(12 * 60, None)
    assert m.settings.BRIGHTNESS == 0.4
    period = m._apply_daylight(18 * 60, period)
    assert period == "night"
    assert m.settings.BRIGHTNESS == 0.1


def test_no_edge_leaves_a_manual_override_alone(load_main):
    """THE contract, not an optimisation: within a period, an externally
    set BRIGHTNESS survives. Stamping it every tick would make manual
    adjustment impossible — see _apply_daylight's docstring."""
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    period = m._apply_daylight(12 * 60, None)
    m.settings.BRIGHTNESS = 0.9          # a manual cycle, mid-afternoon
    period = m._apply_daylight(15 * 60, period)
    assert period == "day"
    assert m.settings.BRIGHTNESS == 0.9  # untouched


def test_the_next_boundary_wins_over_an_override(load_main):
    """...and the override does NOT survive forever. Same contract as an
    OS's automatic dark mode."""
    m = load_main(DAY_START_HOUR=7, DAY_END_HOUR=17,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    period = m._apply_daylight(12 * 60, None)
    m.settings.BRIGHTNESS = 0.9
    period = m._apply_daylight(18 * 60, period)
    assert m.settings.BRIGHTNESS == 0.1


def test_disabled_never_touches_brightness(load_main):
    m = load_main(DAY_NIGHT_ENABLED=False, BRIGHTNESS=0.22,
                  DAY_BRIGHTNESS=0.4, NIGHT_BRIGHTNESS=0.1)
    assert m._apply_daylight(12 * 60, None) is None
    assert m.settings.BRIGHTNESS == 0.22


def test_defaults_are_neutral(load_main):
    """design-principle #9: an existing device upgrading to this firmware
    behaves exactly as before until DAY_BRIGHTNESS is actually set."""
    m = load_main(BRIGHTNESS=0.18)
    assert m.DAY_BRIGHTNESS == 0.18
    assert m.NIGHT_BRIGHTNESS == 0.18
    m._apply_daylight(12 * 60, None)
    assert m.settings.BRIGHTNESS == 0.18
    m._apply_daylight(22 * 60, "day")
    assert m.settings.BRIGHTNESS == 0.18
