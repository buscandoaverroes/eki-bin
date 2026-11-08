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
    # aren't broken (design principle #12, "backward-compatible configuration").
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


# ── memory instrumentation — insights.md §11 ─────────────────────


def test_mem_checkpoint_is_noop_when_disabled(load_main):
    # Must cost nothing in production, and must not itself allocate the
    # thing it measures.
    m = load_main()
    assert m.MEM_DEBUG_ENABLED is False
    m._mem_marks.clear()
    m._mem_checkpoint("x")
    assert m._mem_marks == []


def test_mem_checkpoint_records_when_enabled(load_main):
    m = load_main(MEM_DEBUG_ENABLED=True)
    m._mem_marks.clear()
    m._mem_checkpoint("after import")
    m._mem_checkpoint("after schedule load")
    assert [label for label, _f, _a in m._mem_marks] == [
        "after import", "after schedule load"]
    assert all(isinstance(f, int) and isinstance(a, int)
               for _l, f, a in m._mem_marks)


def test_mem_report_survives_empty_and_prints_deltas(load_main, capsys):
    m = load_main(MEM_DEBUG_ENABLED=True)
    m._mem_marks.clear()
    m._mem_report()                      # nothing recorded — must not raise
    assert capsys.readouterr().out == ""

    # Deltas are free-vs-previous; a step that CONSUMES memory must read
    # negative, which is the direction that makes the table legible.
    m._mem_marks.extend([("after import", 400_000, 100_000),
                         ("after schedule load", 360_000, 140_000)])
    m._mem_report()
    out = capsys.readouterr().out
    assert "after import" in out and "after schedule load" in out
    assert "-40000" in out.replace(",", "")


# ── impulse_vertical_share: a knock through the surface vs. a touch ──────
# docs/imu-interaction-plan.md Phase 1: knocks on the table were the largest
# false-tap class; their impulse arrives along gravity. Measured against the
# gravity the capture settles to, so it must not care how the IMU is mounted.

def _capture(gravity, impulse, n=290, step=4, hit=(8, 11)):
    """(t, x, y, z) at `step` ms; `impulse` added to samples hit[0]..hit[1]."""
    out = []
    for i in range(n):
        v = list(gravity)
        if hit[0] <= i < hit[1]:
            v = [g + d for g, d in zip(v, impulse)]
        out.append((i * step, v[0], v[1], v[2]))
    return out


def test_a_sideways_push_is_mostly_not_vertical(load_main):
    m = load_main()
    assert m.impulse_vertical_share(_capture((0, 0, 16384), (5000, 0, 0))) < 0.05


def test_a_knock_from_below_is_mostly_vertical(load_main):
    m = load_main()
    assert m.impulse_vertical_share(_capture((0, 0, 16384), (0, 0, 3000))) > 0.95


def test_it_does_not_depend_on_which_axis_is_up(load_main):
    m = load_main()
    # IMU mounted on its side: gravity along x. The same physical knock from
    # below is now an x impulse — and must still read as vertical.
    assert m.impulse_vertical_share(_capture((16384, 0, 0), (3000, 0, 0))) > 0.95
    assert m.impulse_vertical_share(_capture((16384, 0, 0), (0, 0, 5000))) < 0.05


def test_no_settled_tail_means_no_evidence_not_rejection(load_main):
    m = load_main(TAP_ENERGY_THRESHOLD=138000, TAP_VERTICAL_SHARE_MAX=0.5)
    short = _capture((0, 0, 16384), (0, 0, 3000), n=50)          # 200 ms only
    assert m.impulse_vertical_share(short) is None
    assert m.classify_valid_input({"energy": 10, "vert_share": None}) is True


def test_the_vertical_check_rejects_and_can_be_disabled(load_main):
    m = load_main(TAP_ENERGY_THRESHOLD=138000, TAP_VERTICAL_SHARE_MAX=0.5)
    assert m.classify_valid_input({"energy": 10, "vert_share": 0.9}) is False
    assert m.classify_valid_input({"energy": 10, "vert_share": 0.1}) is True
    m = load_main(TAP_ENERGY_THRESHOLD=138000, TAP_VERTICAL_SHARE_MAX=None)
    assert m.classify_valid_input({"energy": 10, "vert_share": 0.9}) is True


# ── GyroBias + gyro_mid_dps: "still turning after the impact" ────────────

def test_gyro_bias_learns_the_resting_offset_with_a_time_constant(load_main):
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0)
    b.update((0, 0, 0), 0)                       # first sample seeds
    for _ in range(1000):                        # 10 s (5 tau) of rest at a constant offset
        b.update((-9, 1, 6), 10)
    assert abs(b.bias[0] + 9) < 1 and abs(b.bias[2] - 6) < 1
    # the same 10 s at a different rate learns the same amount
    b2 = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0)
    b2.update((0, 0, 0), 0)
    for _ in range(100):
        b2.update((-9, 1, 6), 100)
    assert abs(b2.bias[0] - b.bias[0]) < 0.5


def test_gyro_bias_ignores_motion_but_reseeds_if_stuck(load_main):
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0)
    b.update((0, 0, 0), 0)
    for _ in range(50):                          # 0.5 s of 70 dps rotation: not learned
        b.update((2000, 0, 0), 10)
    assert b.bias[0] == 0.0
    for _ in range(1100):                        # 11 s gated out: the seed was wrong
        b.update((2000, 0, 0), 10)
    assert b.bias[0] == 2000.0


def test_gyro_mid_dps_measures_only_its_window_against_the_bias(load_main):
    m = load_main()
    rows = [(t, 100 if 150 <= t < 400 else 9999, 0, 0) for t in range(0, 450, 5)]
    assert abs(m.gyro_mid_dps(rows, [0, 0, 0], 35.0) - 3.5) < 1e-9   # 100 LSB = 3.5 dps
    assert m.gyro_mid_dps(rows, [100, 0, 0], 35.0) == 0.0
    assert m.gyro_mid_dps(rows, None, 35.0) is None
    assert m.gyro_mid_dps([(10, 1, 1, 1)], [0, 0, 0], 35.0) is None


def test_the_gyro_check_rejects_rotation_and_none_is_no_evidence(load_main):
    m = load_main(TAP_ENERGY_THRESHOLD=1_000_000, TAP_VERTICAL_SHARE_MAX=0.5,
                  TAP_GYRO_MID_MAX_DPS=1.15)
    assert m.classify_valid_input({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": 0.4})
    assert not m.classify_valid_input({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": 3.0})
    assert m.classify_valid_input({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": None})
    m = load_main(TAP_ENERGY_THRESHOLD=1_000_000, TAP_GYRO_MID_MAX_DPS=None)
    assert not m.gyro_check_enabled()
    assert m.classify_valid_input({"energy": 10, "gyro_mid_dps": 3.0})


# ── the warm-up guard: "once, asleep, it could not be woken" ─────────────
# 35 mdps/LSB, so 1 dps = 28.6 LSB. The tap check rejects above 1.15 dps.

def _rest_window(bias_lsb):
    """A tap's 150-400 ms window with the bottle perfectly still at the
    TRUE resting offset (0,0,0): any rotation it reads is pure bias error."""
    return [(t, 0, 0, 0) for t in range(0, 450, 5)]


def test_the_unwakeable_case_is_reproduced_and_now_abstains(load_main):
    """THE watch item. The baseline seeds from the first sample it sees; if
    that sample was taken mid-handling it starts wrong. Seeded at 20 dps of
    rotation — beyond the 5 dps gate — every at-rest sample afterwards is
    gated out, so it cannot learn its way back, and only re-seeds after
    10 s. Before the guard, every tap in that window read as ~20 dps of
    rotation and was rejected: nothing could wake it."""
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    b.update((572, 0, 0), 0)                     # seeded mid-handling: 20 dps
    for _ in range(500):                         # 5 s perfectly still afterwards
        b.update((0, 0, 0), 10)

    # the old path: trust the bias as soon as it exists
    wrong = m.gyro_mid_dps(_rest_window(0), b.bias, 35.0)
    assert wrong > 15, "the bug: a still bottle reads as ~20 dps of rotation"
    # the guarded path: no evidence, so the tap is judged on the other checks
    assert b.estimate() is None
    assert m.gyro_mid_dps(_rest_window(0), b.estimate(), 35.0) is None


def test_two_seconds_would_not_have_been_enough(load_main):
    """Why the warm-up is 3 tau and not the ~2 s first suggested. A seed
    inside the gate CAN be learned from, but per-axis 5 dps is up to
    sqrt(3) x 5 = 8.7 dps of magnitude, and after one tau of rest that is
    still 3.2 dps — above the 1.15 dps threshold. A 2 s guard would have
    released a baseline that still rejected every tap."""
    m = load_main()
    off = 142                                    # just inside the 5 dps gate on every
    #   axis: 5 dps is 142.86 LSB, so 143 would be gated out and never learn
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    b.update((off, off, off), 0)
    for _ in range(200):                         # 2 s at the true rest
        b.update((0, 0, 0), 10)
    assert m.gyro_mid_dps(_rest_window(0), b.bias, 35.0) > 1.15
    assert b.estimate() is None                  # and the guard is still holding

    for _ in range(400):                         # to 6 s = 3 tau
        b.update((0, 0, 0), 10)
    assert b.estimate() is not None
    assert m.gyro_mid_dps(_rest_window(0), b.estimate(), 35.0) < 0.5


def test_being_picked_up_does_not_restart_the_warm_up(load_main):
    """A good baseline that sees the bottle handled is still a good
    baseline. Only a re-seed — a new, unproven value — starts again;
    otherwise every grab would switch the gyro check off for 6 s."""
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    b.update((0, 0, 0), 0)
    for _ in range(700):                         # 7 s learned at rest
        b.update((0, 0, 0), 10)
    assert b.estimate() is not None
    for _ in range(100):                         # 1 s of handling: gated out
        b.update((2000, 0, 0), 10)
    assert b.estimate() is not None


def test_a_reseed_is_unproven_again(load_main):
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    b.update((0, 0, 0), 0)
    for _ in range(700):
        b.update((0, 0, 0), 10)
    assert b.estimate() is not None
    for _ in range(1100):                        # 11 s gated: re-seeds
        b.update((2000, 0, 0), 10)
    assert b.bias[0] == 2000.0
    assert b.estimate() is None


def test_one_sample_after_a_long_gap_is_not_seconds_of_learning(load_main):
    """The loop blocks for whole seconds during a ceremony or a tap's
    capture, so dt can be large. One sample is one sample — clamped like
    the alpha, or a single reading after the goodnight sunset would
    certify the baseline on its own."""
    m = load_main()
    b = m.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    b.update((0, 0, 0), 0)
    b.update((0, 0, 0), 8000)
    assert b.estimate() is None


def test_the_default_warm_up_is_three_time_constants(load_main):
    m = load_main()
    import importlib
    st = importlib.import_module("settings")
    assert st.GYRO_BIAS_WARMUP_MS == 3 * st.GYRO_BIAS_TAU_MS


def test_energy_default_is_now_a_coarse_guard(load_main):
    m = load_main()
    assert m.TAP_ENERGY_THRESHOLD == 1_000_000


# ── the wake state machine across the ticks_ms wrap ──────────────────

def _g(load_main, **kw):
    import importlib
    load_main(**kw)
    return importlib.import_module("gestures")


def test_a_wake_in_progress_at_the_wrap_still_completes(load_main):
    """THE latent bug. Plain subtraction left `now - started` near -2**30,
    so the phase never left "waking", accepts_input() stayed False, and
    taps and tilt — one shared gate — stopped until power was cycled."""
    g = _g(load_main, WAKE_JOLT_MS=500, WAKE_SETTLE_MS=1500)
    period = g.ticks_since.__globals__["TICKS_PERIOD"]
    st = g._TapCycleState()
    st.wake(period - 200)                 # woken 200 ms before the wrap
    assert not st.accepts_input()
    st.advance(400)                       # 600 ms later, after the wrap
    assert st.phase == "settling"
    st.advance(2000)
    assert st.phase == "awake" and st.accepts_input()


def test_the_awake_deadline_is_reached_across_the_wrap(load_main):
    """The mirror bug: the deadline was never reached, so it stayed lit."""
    g = _g(load_main)
    period = g.ticks_since.__globals__["TICKS_PERIOD"]
    st = g._TapCycleState()
    st.phase, st.awake = "awake", True
    st.awake_until = period + 5_000       # 5 s past the wrap, unmasked
    assert st.advance(1_000) is None      # 4 s still to go
    assert st.advance(6_000) == "asleep"


def test_a_status_message_expires_across_the_wrap(load_main):
    g = _g(load_main)
    period = g.ticks_since.__globals__["TICKS_PERIOD"]
    m = g._StatusMessage()
    m.show(period - 1_000, (1, 2, 3), 2_000)
    assert m.active(500)                  # 1.5 s in, after the wrap
    assert not m.active(1_500)            # 2.5 s in


# ── reasons, counts and the console line ─────────────────────────────

def test_reject_reason_names_the_check_and_agrees_with_classify(load_main):
    g = _g(load_main, TAP_ENERGY_THRESHOLD=1_000_000,
           TAP_VERTICAL_SHARE_MAX=0.5, TAP_GYRO_MID_MAX_DPS=1.15)
    cases = [
        ({"energy": 2_000_000}, "energy"),
        ({"energy": 10, "vert_share": 0.8}, "vertical"),
        ({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": 3.0}, "gyro"),
        ({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": None}, None),
        ({"energy": 10, "vert_share": 0.1, "gyro_mid_dps": 0.4}, None),
    ]
    for feats, why in cases:
        assert g.reject_reason(feats) == why, feats
        assert g.classify_valid_input(feats) == (why is None), feats


def test_tap_stats_line_reports_then_resets(load_main):
    g = _g(load_main)
    g.TAP_STATS.update(triggers=3, accepted=1, gyro=2)
    assert g.tap_stats_line() == "taps 3 → 1 ok (gyro 2)"
    assert g.tap_stats_line() == "taps 0 → 0 ok"


def test_gyro_bias_status_says_which_state_it_is_in(load_main):
    g = _g(load_main)
    b = g.GyroBias(tau_ms=2000, gate_dps=5.0, mdps=35.0, warmup_ms=6000)
    assert b.status() == "no data"
    b.update((0, 0, 0), 0)
    for _ in range(300):
        b.update((0, 0, 0), 10)
    assert b.status().startswith("warming 3.0/6.0s")
    for _ in range(300):
        b.update((0, 0, 0), 10)
    assert b.status() == "ready"


def test_the_imu_status_line_tells_the_four_failures_apart(load_main):
    """The point of the line. Taps and tilt share one gate, so one fault
    stops both, and before this the console said nothing about the IMU —
    four different failures looked the same. Each must read differently."""
    m = load_main()

    class _St:
        phase = "waking"

    counts = {"ok": 0, "failed": 0, "gated": 1800, "booting": 0}
    gate_shut = m._imu_status_line(_St(), None, counts)
    assert "imu: waking" in gate_shut and "reads 0 ok, 0 failed, 1800 gated" in gate_shut
    assert counts["gated"] == 0, "counts reset every block"

    _St.phase = "asleep"
    counts.update(ok=0, failed=1700)
    assert "1700 failed" in m._imu_status_line(_St(), None, counts)

    m._gestures.TAP_STATS.update(triggers=4, accepted=0, gyro=4)
    counts.update(ok=1800)
    line = m._imu_status_line(_St(), None, counts)
    assert "taps 4 → 0 ok (gyro 4)" in line
    assert "tilt off" in line


# ── the IMU resetting itself while the board keeps running ────────────
# Found 2026-10-22/25 on bottle-01: CTRL1 = CTRL2 = 0, STATUS 0, outputs
# (0,0,0), WHO_AM_I still 0x70 — the sensor had reset and the firmware,
# which configured it once at boot, read zeros forever. Writing CTRL1 by
# hand brought back (-715, 483, 16276) = 0.99 g within 100 ms.

class _FakeImuBus:
    """Registers as a dict; can fail on demand."""
    def __init__(self, regs=None, fail=False):
        self.regs = dict(regs or {})
        self.writes = []
        self.fail = fail

    def writeto_mem(self, addr, reg, data):
        if self.fail:
            raise OSError(5)
        self.writes.append((reg, bytes(data)))
        self.regs[reg] = data[0]

    def readfrom_mem(self, addr, reg, n):
        if self.fail:
            raise OSError(5)
        return bytes([self.regs.get(reg, 0)]) * n


def test_configure_writes_what_boot_always_wrote(load_main):
    g = _g(load_main, TAP_GYRO_MID_MAX_DPS=1.15)
    bus = _FakeImuBus()
    g.imu_configure(bus, 0x6B)
    assert bus.regs[0x10] == 0x07 and bus.regs[0x11] == 0x07   # accel + gyro on
    g2 = _g(load_main, TAP_GYRO_MID_MAX_DPS=None)
    bus2 = _FakeImuBus()
    g2.imu_configure(bus2, 0x6B)
    assert bus2.regs == {0x10: 0x07}, "the gyro stays off when nothing reads it"


def test_config_lost_reads_the_state_found_on_the_bench(load_main):
    g = _g(load_main, TAP_GYRO_MID_MAX_DPS=1.15)
    assert g.imu_config_lost(_FakeImuBus({0x10: 0x00, 0x11: 0x00}), 0x6B)   # the bench
    assert not g.imu_config_lost(_FakeImuBus({0x10: 0x07, 0x11: 0x07}), 0x6B)
    assert g.imu_config_lost(_FakeImuBus({0x10: 0x07, 0x11: 0x00}), 0x6B)   # gyro alone
    # a failed read is a bus problem, already counted, not a reset
    assert not g.imu_config_lost(_FakeImuBus(fail=True), 0x6B)


def test_recover_restores_settings_and_forgets_the_dead_gyro_baseline(load_main):
    """While dead, every gyro read was (0,0,0) and the baseline learned it
    as a bottle at rest. It has to start over, warm-up and all."""
    g = _g(load_main, TAP_GYRO_MID_MAX_DPS=1.15)
    g.GYRO_BIAS.update((0, 0, 0), 0)
    for _ in range(700):
        g.GYRO_BIAS.update((0, 0, 0), 10)
    assert g.GYRO_BIAS.estimate() is not None
    bus = _FakeImuBus({0x10: 0x00, 0x11: 0x00})
    assert g.imu_recover(bus, 0x6B) is True
    assert not g.imu_config_lost(bus, 0x6B)
    assert g.GYRO_BIAS.estimate() is None
    assert g.imu_recover(_FakeImuBus(fail=True), 0x6B) is False


def test_the_watch_fires_on_zeros_and_not_on_a_real_reading(load_main):
    g = _g(load_main)
    w = g.ImuWatch(zero_run=30, min_gap_ms=5000)
    assert not w.dead((-715, 483, 16276))
    for i in range(29):
        assert w.dead((0, 0, 0))
        assert not w.due(i * 7)
    assert w.dead((0, 0, 0))
    assert w.due(210), "30 zeros in a row: that cannot be a measurement"


def test_one_real_sample_resets_the_count(load_main):
    """Zeros on all three axes cannot be measured noise — but one real
    reading in between means it was not dead, so the run starts again."""
    g = _g(load_main)
    w = g.ImuWatch(zero_run=30)
    for _ in range(29):
        w.dead((0, 0, 0))
    w.dead((3, -2, 16380))
    w.dead((0, 0, 0))
    assert not w.due(1000)


def test_a_sensor_that_will_not_come_back_is_a_count_not_a_hot_loop(load_main):
    g = _g(load_main)
    w = g.ImuWatch(zero_run=30, min_gap_ms=5000)
    for _ in range(30):
        w.dead((0, 0, 0))
    assert w.due(0)
    w.recovered(0)
    for _ in range(30):
        w.dead((0, 0, 0))
    assert not w.due(2000), "rate-limited"
    assert w.due(5000)
    assert w.recoveries == 1


def test_the_status_line_shows_zeros_and_recoveries(load_main):
    m = load_main()

    class _St:
        phase = "asleep"

    w = m._gestures.ImuWatch()
    w.recoveries = 2
    counts = {"ok": 4342, "failed": 0, "gated": 0, "booting": 0, "zero": 4342}
    line = m._imu_status_line(_St(), None, counts, w)
    assert "4342 ZERO" in line and "recovered 2 since boot" in line
