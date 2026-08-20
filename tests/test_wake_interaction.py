"""LED status messages + what survived the wake-interaction layer.

docs/contracts/led-status-messages.md (live), and
docs/contracts/wake-interaction.md (largely superseded).

**16 tests were removed here on 2026-08-18** when the v1 gesture contract
(docs/contracts/gesture-envelope.md §11) replaced this layer's tap
vocabulary: _imu_tap_detected (an always-False STUB), _TapClassifier
(single-vs-double disambiguation — v1 ships ONE gesture, so there is
nothing to disambiguate), _WakeState (superseded by _TapCycleState, which
adds the WAKING/SETTLING debounce it lacked) and _classify_wake_response
(its job moved into _TapCycleState.resolve plus the loop's quiet-hours
short-circuit). Recorded rather than silently dropped, since those tests
passing is exactly what made the stub look functional for so long.

What remains here is NOT superseded: _StatusMessage and _all_signals_hidden
still back the quiet-hours and no-data acknowledgments unchanged, and
load_schedule's error paths just happen to live in this file.

⚠ _cycle_brightness / _run_secondary_action are still tested but are
currently **unbound** — in the old model they were AWAKE+single-tap; in v1
that gesture is CYCLE. Kept because they are small, pure, and a plausible
future binding, but nothing invokes them today.
"""


# ── _StatusMessage ───────────────────────────────────────────────


# ── _TapClassifier ────────────────────────────────────────────────


# ── _WakeState ────────────────────────────────────────────────────


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
