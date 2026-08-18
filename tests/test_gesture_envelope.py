"""Gesture envelope — docs/contracts/gesture-envelope.md.

Only the PURE layers are host-testable here: feature extraction
(extract_gesture_features) and, once added, the recognizer and scrollwheel
state machine. The IMU HAL (_get_imu, _imu_read_accel_raw) is real I2C I/O,
not host-testable — same limitation _imu_tap_detected() already has.

Synthetic samples below fix y=z=0 and vary only x, so magnitude reduces to
plain |x| * 0.061 — deliberately simple, matching test_primitives.py's
style, not meant to resemble real captured data (which has a ~1g baseline
on whichever axis is "down"). scripts/prepare_tap_dataset.py's
engineer_features() is cross-checked against this function directly on
real capture files as part of implementing it — this file covers the
feature math's edge cases, not numerical parity (already confirmed).
"""


def _flat(n=10, x=0):
    return [(i * 20, x, 0, 0) for i in range(n)]


def _spike_at(index, n, spike_x, base_x=0, interval_ms=20):
    return [
        (i * interval_ms, spike_x if i == index else base_x, 0, 0) for i in range(n)
    ]


# ── extract_gesture_features ─────────────────────────────────────


def test_extract_features_flat_buffer_has_no_peak(load_main):
    m = load_main()
    samples = _flat(n=10, x=1000)  # constant — median baseline cancels it out
    f = m.extract_gesture_features(samples)
    assert abs(f["peak_deviation_mg"]) < 1e-6
    assert f["num_crossings"] == 0
    assert f["spacing_mean_ms"] is None
    assert f["spacing_stdev_ms"] is None


def test_extract_features_single_spike_one_crossing(load_main):
    m = load_main()
    samples = _spike_at(index=5, n=10, spike_x=10000, base_x=0)
    f = m.extract_gesture_features(samples)
    assert f["num_crossings"] == 1
    assert f["spacing_mean_ms"] is None  # only one crossing — no gap to average
    assert f["spacing_stdev_ms"] is None  # needs >= 2 gaps
    assert f["peak_deviation_mg"] > 0


def test_extract_features_two_spikes_gives_one_gap(load_main):
    m = load_main()
    samples = _flat(n=20, x=0)
    samples[3] = (60, 10000, 0, 0)
    samples[10] = (200, 10000, 0, 0)
    f = m.extract_gesture_features(samples)
    assert f["num_crossings"] == 2
    assert f["spacing_mean_ms"] == 200 - 60
    assert f["spacing_stdev_ms"] is None  # one gap isn't enough for a stdev


def test_extract_features_three_spikes_gives_stdev(load_main):
    m = load_main()
    samples = _flat(n=30, x=0)
    samples[2] = (40, 10000, 0, 0)
    samples[8] = (160, 10000, 0, 0)
    samples[20] = (400, 10000, 0, 0)
    f = m.extract_gesture_features(samples)
    assert f["num_crossings"] == 3
    # gaps: 120, 240 — irregular spacing should show up as a real stdev
    assert f["spacing_stdev_ms"] > 0


def test_extract_features_regular_spacing_low_stdev_irregular_high(load_main):
    """The actual signal this feature is FOR (insights.md §9): flick's
    secondary crossings are irregularly spaced, hard handling's are tight/
    regular or absent. Confirm the math produces a bigger stdev for
    irregular spacing than regular spacing, holding crossing COUNT equal."""
    m = load_main()
    regular = _flat(n=40, x=0)
    for i in (2, 12, 22, 32):  # evenly spaced (10 samples apart each)
        regular[i] = (i * 20, 10000, 0, 0)
    irregular = _flat(n=40, x=0)
    for i in (2, 4, 20, 35):  # irregular gaps
        irregular[i] = (i * 20, 10000, 0, 0)

    reg = m.extract_gesture_features(regular)
    irr = m.extract_gesture_features(irregular)
    assert reg["spacing_stdev_ms"] < irr["spacing_stdev_ms"]


def test_extract_features_dominant_axis(load_main):
    m = load_main()
    samples = _flat(n=5, x=0)
    samples[2] = (40, 100, 9000, 200)  # y clearly dominant at the peak sample
    f = m.extract_gesture_features(samples)
    assert f["dominant_axis"] == "y"


def test_extract_features_ring_down_within_buffer(load_main):
    m = load_main()
    # spike, then back to baseline for the rest of the buffer — ring-down
    # should be measurable (not None) since it settles before the buffer ends
    samples = [(0, 0, 0, 0), (20, 10000, 0, 0)] + [(40 + i * 20, 0, 0, 0) for i in range(10)]
    f = m.extract_gesture_features(samples)
    assert f["ring_down_ms"] is not None
    assert f["ring_down_ms"] >= 0


def test_extract_features_energy_scales_with_magnitude(load_main):
    m = load_main()
    small = _spike_at(index=3, n=10, spike_x=2000)
    big = _spike_at(index=3, n=10, spike_x=20000)
    f_small = m.extract_gesture_features(small)
    f_big = m.extract_gesture_features(big)
    assert f_big["energy"] > f_small["energy"]


# ── classify_tap_or_flick ─────────────────────────────────────────


def _features(**overrides):
    base = {
        "peak_deviation_mg": 0,
        "ring_down_ms": 10,
        "energy": 1000,
        "duration_ms": 1000,
        "dominant_axis": "y",
        "num_crossings": 1,
        "spacing_mean_ms": None,
        "spacing_stdev_ms": None,
    }
    base.update(overrides)
    return base


def test_classify_below_trigger_is_nothing(load_main):
    m = load_main(TAP_TRIGGER_THRESHOLD_MG=50)
    assert m.classify_tap_or_flick(_features(peak_deviation_mg=10)) is None


def test_classify_between_trigger_and_flick_is_tap(load_main):
    m = load_main(TAP_TRIGGER_THRESHOLD_MG=50, FLICK_MAGNITUDE_THRESHOLD_MG=140)
    assert m.classify_tap_or_flick(_features(peak_deviation_mg=100)) == "tap"


def test_classify_hard_with_irregular_spacing_is_flick(load_main):
    m = load_main(FLICK_MAGNITUDE_THRESHOLD_MG=140, FLICK_SPACING_STDEV_THRESHOLD_MS=5)
    f = _features(peak_deviation_mg=800, spacing_stdev_ms=50)
    assert m.classify_tap_or_flick(f) == "flick"


def test_classify_hard_with_regular_spacing_is_rejected(load_main):
    """When spacing IS computable, low/regular spacing means hard handling,
    not a flick (insights.md §9: setdown_firm is just as hard as a flick,
    only spacing tells them apart)."""
    m = load_main(FLICK_MAGNITUDE_THRESHOLD_MG=140, FLICK_SPACING_STDEV_THRESHOLD_MS=5)
    hard_but_regular = _features(peak_deviation_mg=1500, spacing_stdev_ms=1, num_crossings=3)
    assert m.classify_tap_or_flick(hard_but_regular) is None


def test_classify_hard_no_spacing_falls_back_to_crossing_count(load_main):
    """Real bug, found on real hardware: an earlier version treated
    "spacing_stdev unavailable" (< 3 crossings — the common case, true for
    ~70% of real flicks) as automatic rejection, which silently killed
    almost every real hard tap/flick (gesture-envelope.md §10). Fixed:
    when spacing can't be computed, fall back to num_crossings — 1 leans
    flick, 2+ leans hard-handling (the best available single feature in
    that regime, ~80%, confirmed a real ceiling not a "need more features"
    gap)."""
    m = load_main(FLICK_MAGNITUDE_THRESHOLD_MG=140)
    one_crossing = _features(peak_deviation_mg=1500, spacing_stdev_ms=None, num_crossings=1)
    two_crossings = _features(peak_deviation_mg=1500, spacing_stdev_ms=None, num_crossings=2)
    assert m.classify_tap_or_flick(one_crossing) == "flick"
    assert m.classify_tap_or_flick(two_crossings) is None


# ── classify_position ────────────────────────────────────────────


def test_classify_position_disabled_by_default(load_main):
    m = load_main()
    assert m.GESTURE_POSITION_ENABLED is False
    assert m.classify_position(_features(peak_deviation_mg=999)) is None


def test_classify_position_enabled_splits_on_threshold(load_main):
    m = load_main(GESTURE_POSITION_ENABLED=True, POSITION_THRESHOLD_MG=150)
    assert m.classify_position(_features(peak_deviation_mg=200)) == "shoulder"
    assert m.classify_position(_features(peak_deviation_mg=100)) == "base"


# ── classify_orientation ─────────────────────────────────────────


def test_classify_orientation_matches_map_entries(load_main):
    m = load_main(ORIENTATION_STABLE_MG=700)
    upright = (0, 0, 16000, 0)  # y positive, dominant, well above stable_mg
    horizontal = (0, 0, 0, -16000)  # z negative
    upside_down = (0, 0, -16000, 0)  # y negative
    assert m.classify_orientation(upright) == "upright"
    assert m.classify_orientation(horizontal) == "horizontal"
    assert m.classify_orientation(upside_down) == "upside_down"


def test_classify_orientation_unclear_when_unstable(load_main):
    m = load_main(ORIENTATION_STABLE_MG=700)
    mid_motion = (0, 500, 500, 500)  # nothing clears the stable threshold
    assert m.classify_orientation(mid_motion) == "unclear"


def test_classify_orientation_unclear_when_axis_unmapped(load_main):
    m = load_main(ORIENTATION_STABLE_MG=700)
    # x-dominant isn't in the default ORIENTATION_MAP at all
    x_dominant = (0, 16000, 0, 0)
    assert m.classify_orientation(x_dominant) == "unclear"


# ── classify_valid_input (v1 minimal contract, §11) ─────────────────


def test_classify_valid_input_low_energy_is_valid(load_main):
    m = load_main(TAP_ENERGY_THRESHOLD=138000)
    assert m.classify_valid_input(_features(energy=27000)) is True


def test_classify_valid_input_high_energy_is_noise(load_main):
    m = load_main(TAP_ENERGY_THRESHOLD=138000)
    assert m.classify_valid_input(_features(energy=2_300_000)) is False


def test_classify_valid_input_ignores_everything_but_energy(load_main):
    """Deliberately doesn't look at position/spacing/crossings — that's
    the whole point of the v1 specialization (gesture-envelope.md §11)."""
    m = load_main(TAP_ENERGY_THRESHOLD=138000)
    low_energy_odd_shape = _features(
        energy=50000, peak_deviation_mg=5000, num_crossings=9, spacing_stdev_ms=1
    )
    assert m.classify_valid_input(low_energy_odd_shape) is True


# ── _GestureMenu ──────────────────────────────────────────────────


def test_menu_starts_inactive(load_main):
    m = load_main()
    menu = m._GestureMenu(("A", "B", "C"))
    assert menu.active is False
    assert menu.scroll(0, 1) is None  # no-op, doesn't raise
    assert menu.select() is None


def test_menu_wake_enters_at_cursor_zero(load_main):
    m = load_main()
    menu = m._GestureMenu(("A", "B", "C"))
    menu.wake(1000)
    assert menu.active is True
    assert menu.cursor == 0


def test_menu_scroll_wraps_around(load_main):
    m = load_main()
    menu = m._GestureMenu(("A", "B", "C"))
    menu.wake(0)
    menu.scroll(100, 1)
    assert menu.cursor == 1
    menu.scroll(200, 1)
    assert menu.cursor == 2
    menu.scroll(300, 1)  # wraps past the end
    assert menu.cursor == 0
    menu.scroll(400, -1)  # wraps the other direction
    assert menu.cursor == 2


def test_menu_select_returns_option_and_exits(load_main):
    m = load_main()
    menu = m._GestureMenu(("A", "B", "C"))
    menu.wake(0)
    menu.scroll(100, 1)  # cursor -> 1, "B"
    assert menu.select() == "B"
    assert menu.active is False


def test_menu_wake_while_active_resets_cursor(load_main):
    m = load_main()
    menu = m._GestureMenu(("A", "B", "C"))
    menu.wake(0)
    menu.scroll(100, 1)
    menu.wake(500)  # re-wake — resets, doesn't error or accumulate
    assert menu.cursor == 0
    assert menu.entered_at == 500


def test_menu_scroll_refreshes_idle_timeout(load_main):
    """The behavior fixed after real-hardware testing surfaced it: scroll
    must refresh entered_at, or a long browsing session can time out
    mid-browse even while the user is actively scrolling — see
    gesture-envelope.md's Implemented mapping section for why this is
    deliberately different from _WakeState's non-refreshing WAKE_MINUTES."""
    m = load_main(GESTURE_MODE_TIMEOUT_MS=15_000)
    menu = m._GestureMenu(("A", "B", "C"))
    menu.wake(0)
    assert menu.is_expired(14_000) is False
    menu.scroll(14_000, 1)  # activity just before the original deadline
    assert menu.entered_at == 14_000
    assert menu.is_expired(15_000) is False  # would have expired without the refresh
    assert menu.is_expired(28_999) is False
    assert menu.is_expired(29_000) is True  # 15s after the LAST scroll, not the wake


def test_menu_is_expired_after_timeout(load_main):
    m = load_main(GESTURE_MODE_TIMEOUT_MS=15_000)
    menu = m._GestureMenu(("A", "B"))
    menu.wake(0)
    assert menu.is_expired(14_999) is False
    assert menu.is_expired(15_000) is True


def test_menu_not_expired_when_inactive(load_main):
    m = load_main(GESTURE_MODE_TIMEOUT_MS=15_000)
    menu = m._GestureMenu(("A", "B"))
    assert menu.is_expired(999_999) is False  # never woken — nothing to expire


# ── _classify_menu_response ──────────────────────────────────────


def test_menu_response_no_gesture_is_none(load_main):
    m = load_main()
    assert m._classify_menu_response(menu_active=False, physical_gesture=None) is None
    assert m._classify_menu_response(menu_active=True, physical_gesture=None) is None


def test_menu_response_inactive_tap_or_flick_wakes(load_main):
    m = load_main()
    assert m._classify_menu_response(menu_active=False, physical_gesture="tap") == "wake"
    assert m._classify_menu_response(menu_active=False, physical_gesture="flick") == "wake"


def test_menu_response_active_flick_selects_tap_scrolls(load_main):
    """The core "gesture A doesn't always mean X" principle
    (gesture-envelope.md §1/§6) — the same physical flick means WAKE when
    inactive, SELECT when active."""
    m = load_main()
    assert m._classify_menu_response(menu_active=True, physical_gesture="flick") == "select"
    assert m._classify_menu_response(menu_active=True, physical_gesture="tap") == "scroll"


# ── _scroll_direction ────────────────────────────────────────────


def test_scroll_direction_position_aware(load_main):
    m = load_main()
    assert m._scroll_direction("shoulder") == 1
    assert m._scroll_direction("base") == -1


def test_scroll_direction_defaults_forward_when_unknown(load_main):
    m = load_main()
    assert m._scroll_direction(None) == 1


# ── _TapCycleState (v1 minimal contract, §11) ────────────────────────


def _state(load_main, **overrides):
    defaults = dict(WAKE_JOLT_MS=500, WAKE_SETTLE_MS=1500, AWAKE_MINUTES=15)
    defaults.update(overrides)
    return load_main(**defaults)._TapCycleState()


def test_tap_cycle_starts_asleep(load_main):
    state = _state(load_main)
    assert state.awake is False
    assert state.phase == "asleep"
    assert state.accepts_input() is True


def test_tap_cycle_valid_input_while_asleep_wakes(load_main):
    state = _state(load_main)
    assert state.resolve(1000, valid=True) == "wake"
    assert state.awake is True
    assert state.phase == "waking"
    assert state.phase_started_at == 1000


def test_tap_cycle_noise_while_asleep_does_nothing(load_main):
    state = _state(load_main)
    assert state.resolve(1000, valid=False) is None
    assert state.awake is False
    assert state.phase == "asleep"


def test_tap_cycle_no_input_accepted_during_waking_or_settling(load_main):
    state = _state(load_main, WAKE_JOLT_MS=500, WAKE_SETTLE_MS=1500)
    state.resolve(0, valid=True)  # -> waking
    assert state.accepts_input() is False
    assert state.resolve(100, valid=True) is None  # a trigger landing here is ignored

    state.advance(500)  # -> settling
    assert state.phase == "settling"
    assert state.accepts_input() is False
    assert state.resolve(600, valid=True) is None


def test_tap_cycle_advances_waking_to_settling_to_awake(load_main):
    state = _state(load_main, WAKE_JOLT_MS=500, WAKE_SETTLE_MS=1500, AWAKE_MINUTES=15)
    state.resolve(0, valid=True)  # -> waking, phase_started_at=0

    assert state.advance(499) is None  # not yet
    assert state.advance(500) == "settling"
    assert state.phase == "settling"
    assert state.phase_started_at == 500

    assert state.advance(1999) is None  # not yet (500 + 1500 - 1)
    assert state.advance(2000) == "awake"
    assert state.phase == "awake"
    assert state.awake_until == 2000 + 15 * 60_000


def test_tap_cycle_valid_input_while_awake_cycles(load_main):
    state = _state(load_main)
    state.resolve(0, valid=True)
    state.advance(500)
    state.advance(2000)
    assert state.phase == "awake"

    assert state.resolve(3000, valid=True) == "cycle"
    assert state.phase == "awake"  # cycling doesn't change phase
    assert state.awake is True


def test_tap_cycle_noise_while_awake_does_nothing(load_main):
    state = _state(load_main)
    state.resolve(0, valid=True)
    state.advance(500)
    state.advance(2000)

    assert state.resolve(3000, valid=False) is None
    assert state.phase == "awake"


def test_tap_cycle_times_out_back_to_asleep(load_main):
    state = _state(load_main, AWAKE_MINUTES=15)
    state.resolve(0, valid=True)
    state.advance(500)
    state.advance(2000)
    awake_until = state.awake_until

    assert state.advance(awake_until - 1) is None
    assert state.advance(awake_until) == "asleep"
    assert state.awake is False
    assert state.phase == "asleep"
    assert state.awake_until is None


def test_tap_cycle_acknowledge_sets_pending_flag(load_main):
    state = _state(load_main)
    assert state.ack_pending is False
    state.acknowledge()
    assert state.ack_pending is True
    state.resolve(0, valid=True)
    assert state.ack_pending is False


# ── jolt render math, ported from gesture_sandbox into main ──────


def test_tap_strength_clamps_and_is_monotonic(load_main):
    m = load_main()
    assert m._tap_strength(m.STRENGTH_MIN_DEV_MG - 100) == 0.0
    assert m._tap_strength(m.STRENGTH_MAX_DEV_MG + 999) == 1.0
    devs = [0, 60, 150, 300, 460, 900]
    strengths = [m._tap_strength(d) for d in devs]
    assert strengths == sorted(strengths)


def test_ack_flick_settles_exactly_on_the_shelf(load_main):
    # The "continental shelf": ACK must land ON shelf_mult, not near it and
    # not at 0 — a hand-off discontinuity into the static shelf write is
    # what the real-hardware "dive to black" bug looked like.
    m = load_main()
    assert m._ack_flick(0, 1.0, 0.2, 400) == 0.0
    assert m._ack_flick(200, 1.0, 0.2, 400) == 1.0  # peak at the midpoint
    assert abs(m._ack_flick(400, 1.0, 0.2, 400) - 0.2) < 1e-9
    assert abs(m._ack_flick(9999, 1.0, 0.2, 400) - 0.2) < 1e-9  # holds


def test_confirm_jolt_starts_from_the_shelf_and_decays_to_black(load_main):
    # Rises FROM the shelf rather than from 0 (that continuity is the whole
    # point), and must reach exactly 0 so "decided, done" reads as done.
    m = load_main()
    assert m._confirm_jolt_mult(0, 0.2) == 0.2
    assert m._confirm_jolt_mult(m.WAKE_JOLT_MS, 0.2) == 0.0
    peak = max(m._confirm_jolt_mult(t, 0.2) for t in range(0, m.WAKE_JOLT_MS, 5))
    assert abs(peak - m.WAKE_JOLT_BRIGHTNESS_MULT) < 0.05


def test_ack_peak_ceiling_does_not_saturate(load_main):
    # Same invariant tests/test_gesture_sandbox.py guards for the sandbox —
    # asserted here too now that main.py owns these constants for real.
    m = load_main(BRIGHTNESS=0.15)
    assert max(m.STARTUP_COLOR) * m.BRIGHTNESS * m.ACK_PEAK_CEIL < 255


def test_shelf_stays_below_the_ack_peak_floor(load_main):
    m = load_main()
    assert m.SHELF_CEIL < m.ACK_PEAK_FLOOR


def test_gesture_poll_is_faster_than_the_render_frame(load_main):
    # The recognizer's 95-98% numbers were measured at 4ms. Polling at
    # FRAME_MS (16ms) was documented as a real cause of missed taps, so the
    # interactive loop ticks at GESTURE_POLL_MS and time-gates its render.
    m = load_main()
    assert m.GESTURE_POLL_MS < m.FRAME_MS


def test_gesture_enabled_accepts_either_config_name(load_main):
    # GESTURE_ENABLED is the name that matches the shipped contract;
    # WAKE_INTERACTION_ENABLED still works so existing config.py files
    # aren't broken (design principle #9).
    assert load_main(GESTURE_ENABLED=True).WAKE_INTERACTION_ENABLED is True
    assert load_main(WAKE_INTERACTION_ENABLED=True).WAKE_INTERACTION_ENABLED is True
    assert load_main().WAKE_INTERACTION_ENABLED is False


def test_gesture_enabled_new_name_wins(load_main):
    m = load_main(GESTURE_ENABLED=False, WAKE_INTERACTION_ENABLED=True)
    assert m.WAKE_INTERACTION_ENABLED is False


# ── multi-line schedules — schedule-json.md § Multiple lines ─────


def test_schedule_lines_wraps_a_single_line_file(load_main):
    # No `lines` key = the document IS the line. This is the shape every
    # schedule predating multi-line support has, and it must keep working.
    m = load_main()
    data = {"station": "mystation",
            "weekday": {"a": [300], "b": [310]},
            "weekend": {"a": [400]}}
    lines = m.schedule_lines(data)
    assert len(lines) == 1
    assert lines[0]["name"] == "mystation"
    assert lines[0]["weekday"]["a"] == [300]
    assert lines[0]["weekend"]["a"] == [400]


def test_schedule_lines_passes_multi_line_through(load_main):
    m = load_main()
    data = {"station": "s", "lines": [
        {"name": "green", "color": [0, 255, 0], "weekday": {"a": [300]}},
        {"name": "red", "color": [255, 0, 0], "weekday": {"a": [310]}},
    ]}
    lines = m.schedule_lines(data)
    assert [l["name"] for l in lines] == ["green", "red"]
    assert lines[1]["color"] == [255, 0, 0]


def test_schedule_lines_always_returns_at_least_one(load_main):
    # Guarantees `lines[i % len(lines)]` can never ZeroDivisionError, which
    # is what the cycling index relies on.
    m = load_main()
    for data in ({}, {"station": "s"}, {"station": "s", "lines": []}):
        assert len(m.schedule_lines(data)) >= 1


def test_schedule_lines_missing_period_is_absent_not_empty(load_main):
    # A station with no weekend service should not gain an empty weekend
    # key — current_period() looks the period up and "absent" is the honest
    # answer, distinct from "runs, but no trains".
    m = load_main()
    lines = m.schedule_lines({"station": "s", "weekday": {"a": [300]}})
    assert "weekend" not in lines[0]
