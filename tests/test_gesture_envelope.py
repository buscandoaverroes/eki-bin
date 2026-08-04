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


def test_classify_hard_with_regular_or_no_spacing_is_rejected(load_main):
    """The core insights.md §9 finding: magnitude alone can't tell a flick
    from hard handling (setdown_firm is just as hard) — regularity can."""
    m = load_main(FLICK_MAGNITUDE_THRESHOLD_MG=140, FLICK_SPACING_STDEV_THRESHOLD_MS=5)
    hard_but_no_ring = _features(peak_deviation_mg=1500, spacing_stdev_ms=None)
    hard_but_regular = _features(peak_deviation_mg=1500, spacing_stdev_ms=1)
    assert m.classify_tap_or_flick(hard_but_no_ring) is None
    assert m.classify_tap_or_flick(hard_but_regular) is None


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
