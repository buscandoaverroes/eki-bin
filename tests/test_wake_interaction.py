"""Wake/sleep interaction layer + LED status messages.

docs/contracts/wake-interaction.md, docs/contracts/led-status-messages.md.
Only the PURE decision logic is host-testable here — _TapClassifier,
_WakeState, _StatusMessage, _classify_wake_response, _all_signals_hidden,
_cycle_brightness/_run_secondary_action. The real-time loops that drive them
(_run_interactive_loop, _imu_tap_detected's eventual real sensor read) are
not, same limitation every other real-time piece in this codebase already
has. WAKE_INTERACTION_ENABLED defaults to False specifically so none of this
affects _run_classic_loop, which every existing deployment still uses.
"""


# ── _imu_tap_detected (stub) ─────────────────────────────────────


def test_imu_tap_detected_stub_always_false(load_main):
    # No IMU wired yet — must never fabricate a tap. See the function's own
    # docstring for why False (not raising) is the deliberate choice.
    m = load_main()
    assert m._imu_tap_detected() is False


# ── _TapClassifier ────────────────────────────────────────────────


def test_tap_classifier_no_taps_reports_nothing(load_main):
    m = load_main(DOUBLE_TAP_WINDOW_MS=400)
    c = m._TapClassifier()
    for t in range(0, 2000, 100):
        assert c.advance(t, False) is None


def test_tap_classifier_single_tap_resolves_after_window(load_main):
    m = load_main(DOUBLE_TAP_WINDOW_MS=400)
    c = m._TapClassifier()
    assert c.advance(0, True) is None       # first tap — pending
    assert c.advance(200, False) is None    # still inside the window
    assert c.advance(399, False) is None    # just under the window
    assert c.advance(400, False) == "single"  # window elapsed, no 2nd tap


def test_tap_classifier_second_tap_inside_window_is_double(load_main):
    m = load_main(DOUBLE_TAP_WINDOW_MS=400)
    c = m._TapClassifier()
    assert c.advance(0, True) is None
    assert c.advance(200, False) is None
    assert c.advance(350, True) == "double"


def test_tap_classifier_second_tap_outside_window_is_two_singles(load_main):
    m = load_main(DOUBLE_TAP_WINDOW_MS=400)
    c = m._TapClassifier()
    assert c.advance(0, True) is None
    assert c.advance(400, False) == "single"    # first tap resolves alone
    assert c.advance(400, True) is None          # a NEW pending tap starts
    assert c.advance(800, False) == "single"    # resolves alone too


def test_tap_classifier_resets_after_reporting(load_main):
    m = load_main(DOUBLE_TAP_WINDOW_MS=400)
    c = m._TapClassifier()
    c.advance(0, True)
    c.advance(400, False)  # -> "single"
    assert c._pending_since is None
    for t in range(500, 2000, 100):
        assert c.advance(t, False) is None  # nothing pending, stays quiet


# ── _WakeState ────────────────────────────────────────────────────


def test_wake_state_starts_awake(load_main):
    m = load_main()
    w = m._WakeState()
    assert w.awake is True
    assert w.wake_until is None


def test_wake_state_wake_sets_countdown(load_main):
    m = load_main(WAKE_MINUTES=30)
    w = m._WakeState()
    w.wake(1000)
    assert w.awake is True
    assert w.wake_until == 1000 + 30 * 60_000


def test_wake_state_is_expired_before_and_after(load_main):
    m = load_main(WAKE_MINUTES=30)
    w = m._WakeState()
    w.wake(0)
    assert w.is_expired(30 * 60_000 - 1) is False
    assert w.is_expired(30 * 60_000) is True


def test_wake_state_sleep_clears_expiry(load_main):
    m = load_main(WAKE_MINUTES=30)
    w = m._WakeState()
    w.wake(0)
    w.sleep()
    assert w.awake is False
    assert w.wake_until is None
    assert w.is_expired(10**9) is False  # not awake -> never "expired"


def test_wake_state_re_wake_resets_countdown(load_main):
    # Extend / re-wake is the SAME operation whether already awake or not.
    m = load_main(WAKE_MINUTES=30)
    w = m._WakeState()
    w.wake(0)
    w.wake(1000)  # e.g. a double-tap extend partway through
    assert w.wake_until == 1000 + 30 * 60_000


# ── _StatusMessage ────────────────────────────────────────────────


def test_status_message_inactive_by_default(load_main):
    m = load_main()
    s = m._StatusMessage()
    assert s.active(0) is False


def test_status_message_active_until_expiry(load_main):
    m = load_main()
    s = m._StatusMessage()
    s.show(1000, (128, 0, 200), 2500)
    assert s.active(1000) is True
    assert s.active(3499) is True
    assert s.active(3500) is False
    assert s.color == (128, 0, 200)


# ── _classify_wake_response ──────────────────────────────────────


def test_classify_no_tap_is_none(load_main):
    m = load_main()
    assert m._classify_wake_response(False, None, True) is None
    assert m._classify_wake_response(True, None, False) is None


def test_classify_quiet_hours_always_wins(load_main):
    m = load_main()
    # ANY tap during quiet hours -> quiet_tap_ack, regardless of awake state
    assert m._classify_wake_response(True, "single", True) == "quiet_tap_ack"
    assert m._classify_wake_response(True, "double", True) == "quiet_tap_ack"
    assert m._classify_wake_response(True, "single", False) == "quiet_tap_ack"
    assert m._classify_wake_response(True, "double", False) == "quiet_tap_ack"


def test_classify_asleep_any_tap_wakes(load_main):
    m = load_main()
    assert m._classify_wake_response(False, "single", False) == "wake_ceremony"
    assert m._classify_wake_response(False, "double", False) == "wake_ceremony"


def test_classify_awake_single_is_secondary_action(load_main):
    m = load_main()
    assert m._classify_wake_response(False, "single", True) == "secondary_action"


def test_classify_awake_double_is_extend(load_main):
    m = load_main()
    assert m._classify_wake_response(False, "double", True) == "extend"


# ── _all_signals_hidden ───────────────────────────────────────────


def test_all_signals_hidden_single_direction(load_main):
    m = load_main()
    assert m._all_signals_hidden(m.LeaveSignal([]), None) is True
    assert m._all_signals_hidden(m.LeaveSignal([3.0]), None) is False


def test_all_signals_hidden_bidirectional(load_main):
    m = load_main()
    assert m._all_signals_hidden(m.LeaveSignal([]), m.LeaveSignal([])) is True
    assert m._all_signals_hidden(m.LeaveSignal([]), m.LeaveSignal([3.0])) is False
    assert m._all_signals_hidden(m.LeaveSignal([3.0]), m.LeaveSignal([])) is False


# ── _cycle_brightness / _run_secondary_action ────────────────────


def test_cycle_brightness_wraps_through_presets(load_main):
    m = load_main(BRIGHTNESS=0.15, BRIGHTNESS_PRESETS=(0.15, 0.35, 0.6))
    assert m._cycle_brightness() == 0.35
    assert m._cycle_brightness() == 0.6
    assert m._cycle_brightness() == 0.15  # wraps back around


def test_cycle_brightness_starts_over_if_not_a_preset(load_main):
    m = load_main(BRIGHTNESS=0.9, BRIGHTNESS_PRESETS=(0.15, 0.35, 0.6))
    assert m._cycle_brightness() == 0.15


def test_run_secondary_action_default_cycles_brightness(load_main):
    m = load_main(
        BRIGHTNESS=0.15, BRIGHTNESS_PRESETS=(0.15, 0.35, 0.6),
        SECONDARY_ACTION="brightness_cycle",
    )
    m._run_secondary_action()
    assert m.BRIGHTNESS == 0.35


def test_run_secondary_action_unknown_action_is_noop(load_main):
    m = load_main(
        BRIGHTNESS=0.15, BRIGHTNESS_PRESETS=(0.15, 0.35, 0.6),
        SECONDARY_ACTION="not_a_real_action",
    )
    m._run_secondary_action()
    assert m.BRIGHTNESS == 0.15  # unchanged


# ── load_schedule failure modes ──────────────────────────────────


def test_load_schedule_raises_oserror_on_missing_file(load_main, tmp_path):
    m = load_main()
    missing = tmp_path / "nope.json"
    try:
        m.load_schedule(str(missing))
        assert False, "expected OSError"
    except OSError:
        pass


def test_load_schedule_raises_valueerror_on_malformed_json(load_main, tmp_path):
    m = load_main()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    try:
        m.load_schedule(str(bad))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_load_schedule_returns_parsed_dict_on_success(load_main, tmp_path):
    m = load_main()
    good = tmp_path / "good.json"
    good.write_text('{"station": "test", "weekday": {"a": [100]}}')
    data = m.load_schedule(str(good))
    assert data["station"] == "test"
    assert data["weekday"]["a"] == [100]
