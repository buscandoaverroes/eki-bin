"""Boot ceremony — docs/contracts/startup-sequence.md.

Only the PURE helpers are host-testable here (_startup_circle_index,
_startup_burst_mult, _startup_error_mult, and the one-frame renderer
_draw_startup_circle). connect_wifi(), _play_startup_burst(),
_run_startup_failure_forever(), and run_startup_sequence() itself all drive
real time.ticks_ms()/sleep_ms() (and connect_wifi() touches `network`) —
none of that is host-testable, same limitation render_for_interval's real
frame loop already has. Real-hardware validation is required for all of it.
"""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


# ── loading-circle spin ──────────────────────────────────────────


def test_circle_index_starts_at_zero(load_main):
    m = load_main(STARTUP_SPIN_HZ=0.5, NUM_LEDS=10)
    assert m._startup_circle_index(0) == 0


def test_circle_index_advances_over_one_revolution(load_main):
    m = load_main(STARTUP_SPIN_HZ=0.5, NUM_LEDS=10)  # period = 2000ms
    assert m._startup_circle_index(0) == 0
    assert m._startup_circle_index(1000) == 5    # halfway around
    assert m._startup_circle_index(1999) == 9    # just before wrapping


def test_circle_index_wraps_around(load_main):
    m = load_main(STARTUP_SPIN_HZ=0.5, NUM_LEDS=10)  # period = 2000ms
    assert m._startup_circle_index(2000) == m._startup_circle_index(0)
    assert m._startup_circle_index(2500) == m._startup_circle_index(500)


def test_draw_startup_circle_lights_exactly_one_led(load_main):
    m = load_main(STARTUP_SPIN_HZ=0.5, NUM_LEDS=10, DITHER=False, BRIGHTNESS=1.0)
    m._draw_startup_circle(1000)
    assert _lit(m.np) == [5]
    assert m.np.buf[5] == tuple(int(c * m.BRIGHTNESS) for c in m.STARTUP_COLOR)


def test_draw_startup_circle_respects_brightness(load_main):
    m = load_main(STARTUP_SPIN_HZ=0.5, NUM_LEDS=10, DITHER=False, BRIGHTNESS=0.5)
    m._draw_startup_circle(0)
    assert m.np.buf[0] == tuple(int(c * 0.5) for c in m.STARTUP_COLOR)


# ── success burst ─────────────────────────────────────────────────


def test_burst_mult_rises_during_burst_phase(load_main):
    m = load_main(STARTUP_BURST_MS=1000, STARTUP_FADE_MS=1000)
    assert m._startup_burst_mult(0) == 0.0
    assert m._startup_burst_mult(500) == 0.5
    assert m._startup_burst_mult(999) < 1.0


def test_burst_mult_decays_during_fade_phase(load_main):
    m = load_main(STARTUP_BURST_MS=1000, STARTUP_FADE_MS=1000)
    assert m._startup_burst_mult(1000) == 1.0    # peak, right at the handoff
    assert m._startup_burst_mult(1500) == 0.5
    assert m._startup_burst_mult(1999) > 0.0


def test_burst_mult_zero_after_total_duration(load_main):
    m = load_main(STARTUP_BURST_MS=1000, STARTUP_FADE_MS=1000)
    assert m._startup_burst_mult(2000) == 0.0
    assert m._startup_burst_mult(5000) == 0.0


def test_burst_mult_monotonic_rise_then_fall(load_main):
    m = load_main(STARTUP_BURST_MS=800, STARTUP_FADE_MS=1500)
    samples = [m._startup_burst_mult(t) for t in range(0, 2301, 100)]
    peak = samples.index(max(samples))
    assert all(b >= a for a, b in zip(samples[:peak], samples[1 : peak + 1]))
    assert all(b <= a for a, b in zip(samples[peak:], samples[peak + 1 :]))


def test_burst_mult_handles_zero_burst_ms(load_main):
    # No rise phase at all — starts straight into decay.
    m = load_main(STARTUP_BURST_MS=0, STARTUP_FADE_MS=1000)
    assert m._startup_burst_mult(0) == 1.0
    assert m._startup_burst_mult(500) == 0.5


def test_burst_mult_handles_zero_fade_ms(load_main):
    # No decay phase at all — drops straight to 0 once the rise completes.
    m = load_main(STARTUP_BURST_MS=1000, STARTUP_FADE_MS=0)
    assert m._startup_burst_mult(999) < 1.0
    assert m._startup_burst_mult(1000) == 0.0


# ── failure state ─────────────────────────────────────────────────


def test_error_mult_matches_breathe_with_its_own_period(load_main):
    m = load_main(ERROR_BREATHE_PERIOD_MS=4000)
    for t in (0, 1000, 2000, 3000, 4000):
        assert m._startup_error_mult(t) == m.breathe(t, 4000, floor=0.15)


def test_error_mult_independent_of_contract_breathe_period(load_main):
    # ERROR_BREATHE_PERIOD_MS is deliberately separate from BREATHE_PERIOD_MS
    # — retuning a contract's breathing feel must not move the failure state.
    m = load_main(ERROR_BREATHE_PERIOD_MS=4000, BREATHE_PERIOD_MS=999)
    assert m._startup_error_mult(1000) == m.breathe(1000, 4000, floor=0.15)


def test_error_mult_never_goes_fully_dark(load_main):
    m = load_main(ERROR_BREATHE_PERIOD_MS=4000)
    samples = [m._startup_error_mult(t) for t in range(0, 4001, 200)]
    assert all(s >= 0.15 for s in samples)  # floor=0.15, never truly off


# ── failure colours stay distinguishable ─────────────────────────


def test_failure_colours_are_all_distinct(load_main):
    # docs/contracts/led-status-messages.md's stated principle: "different
    # failure CAUSES get visually distinct colours. One universal
    # 'something's wrong, breathe red' for every failure defeats that."
    # Three terminal failures exist now — WiFi/NTP, schedule load, and (new)
    # a bad config value — and the whole point is telling them apart with no
    # laptop attached, so a copy-paste that collapsed two of them into the
    # same colour would silently undo the feature.
    m = load_main()
    colours = [m.ERROR_COLOR, m.SCHEDULE_ERROR_COLOR, m.CONFIG_ERROR_COLOR]
    assert len(set(colours)) == len(colours), (
        f"failure colours must be distinguishable, got {colours}"
    )


# ── TIME_SOURCE ──────────────────────────────────────────────────


def test_time_source_defaults_to_wifi(load_main):
    m = load_main()
    assert m.TIME_SOURCE == "wifi"  # V1 behaviour unchanged for existing configs


def test_wifi_creds_optional_so_a_wifi_free_unit_can_boot():
    # TIME_SOURCE="rtc" units (the only way to run a full app on the XIAO
    # ESP32-C3 — docs/insights.md §11) have no reason to carry credentials.
    # These were a hard `config.WIFI_SSID` read, which AttributeError'd at
    # import before main() could explain anything.
    #
    # Built directly rather than via load_main, because that fixture always
    # merges DEFAULT_CONFIG — and OMITTING the keys is the whole point here.
    import importlib
    import sys
    import types

    import conftest

    conftest._install_device_fakes()
    cfg = types.ModuleType("config")
    for key, value in conftest.DEFAULT_CONFIG.items():
        if key not in ("WIFI_SSID", "WIFI_PASS"):
            setattr(cfg, key, value)
    cfg.TIME_SOURCE = "rtc"
    sys.modules["config"] = cfg
    sys.modules.pop("main", None)
    if conftest.MICROPYTHON_DIR not in sys.path:
        sys.path.insert(0, conftest.MICROPYTHON_DIR)

    m = importlib.import_module("main")  # must not raise
    assert m.WIFI_SSID is None
    assert m.TIME_SOURCE == "rtc"
