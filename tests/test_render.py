"""Stage 2 — rendering geometry and the contracts' framebuffers."""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


def test_arc_len_shrinks_and_caps(load_main):
    m = load_main(MINUTES_PER_LED=1, NUM_LEDS=8)
    assert m._arc_len(3) == 3
    assert m._arc_len(0) == 1     # always at least 1 while catchable
    assert m._arc_len(20) == 8    # capped at NUM_LEDS


def test_heartbeat_pin_disabled_when_falsy(load_main):
    m = load_main(HEARTBEAT_PIN=None)
    assert m._heartbeat_pin(None) is None
    assert m._heartbeat_pin("") is None


def test_heartbeat_pin_constructed_when_set(load_main):
    m = load_main(HEARTBEAT_PIN="LED")
    assert m._heartbeat_pin("LED") is not None
    assert m._heartbeat_pin(2) is not None  # a bare GPIO number, e.g. XIAO boards


def test_physical_near_vs_far(load_main):
    near = load_main(ARC_ORIGIN="near", NUM_LEDS=8)
    assert [near._physical(i) for i in range(3)] == [0, 1, 2]
    far = load_main(ARC_ORIGIN="far", NUM_LEDS=8)
    assert [far._physical(i) for i in range(3)] == [7, 6, 5]


def test_sandtimer_lights_arc(load_main):
    m = load_main(CONTRACT="sandtimer", ARC_ORIGIN="near")
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([3.0]), 0)   # 3 min → 3 LEDs
    assert _lit(m.np) == [0, 1, 2]


def test_far_origin_reverses_arc(load_main):
    m = load_main(CONTRACT="sandtimer", ARC_ORIGIN="far")
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([3.0]), 0)
    assert _lit(m.np) == [5, 6, 7]


def test_dither_averages_to_target(load_main):
    # sigma-delta: a fractional brightness must average to itself over frames,
    # while each individual frame stays an integer (0..255).
    m = load_main()
    res = [0.0, 0.0, 0.0]
    outs = [m._quantize(1.4, res, 0) for _ in range(400)]
    assert all(isinstance(o, int) for o in outs)
    assert set(outs) <= {1, 2}                      # only the neighbouring codes
    assert abs(sum(outs) / len(outs) - 1.4) < 0.02  # mean tracks the target


def test_dither_leaves_integers_exact(load_main):
    # an already-integer brightness must not flicker
    m = load_main()
    res = [0.3, 0.3, 0.3]
    outs = [m._quantize(30.0, res, 0) for _ in range(50)]
    assert set(outs) == {30}


def test_dither_off_is_plain_truncation(load_main):
    m = load_main(DITHER=False, BRIGHTNESS=1.0)
    m.SandTimerContract().render(m.LeaveSignal([3.0]), 0)
    # LEVEL_2 default colour (200,180,0) at full brightness, no dither → exact
    assert m.np.buf[m._physical(0)] == (200, 180, 0)


def test_hidden_clears_strip(load_main):
    m = load_main()
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)       # no catchable trains
    assert _lit(m.np) == []


def test_breathing_lights_and_does_not_crash(load_main):
    # guards the staticmethod / breathe_fn binding fix
    m = load_main(CONTRACT="breathing")
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([3.0]), 1100)  # near breath peak
    assert _lit(m.np) == [0, 1, 2]


def test_every_registered_contract_lights_somewhere(load_main):
    # Animated contracts dim to (near) black at the trough of the breath BY
    # DESIGN, so "lit at one fixed phase" is the wrong assertion. Require instead
    # that each contract lights the arc at *some* phase across a full cycle —
    # i.e. it renders and isn't a silent no-op.
    for name in ("sandtimer", "color", "breathing",
                 "breathing_exponent", "breathing_inverse"):
        m = load_main(CONTRACT=name)
        lit_phases = []
        for phase in range(0, 8001, 200):
            m.ACTIVE_CONTRACT.render(m.LeaveSignal([3.0]), phase)
            if _lit(m.np):
                lit_phases.append(phase)
        assert lit_phases, f"{name} never lit across a full cycle"
