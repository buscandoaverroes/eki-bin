"""N_TRAINS / _paint_layers — nested-arc rendering for multiple departures.

Stage 1 (LeaveSignal.ttls) needed zero changes for this feature — it was
already a plain list of continuous times. Everything here is Stage 2
(rendering) only, verifying the compositing primitive contracts build on.
"""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


def test_layer_mult_falloff(load_main):
    m = load_main(BACKGROUND_BRIGHTNESS=0.35)
    assert m._layer_mult(0) == 1.0  # primary always full-relative
    assert m._layer_mult(1) == 0.35
    assert m._layer_mult(2) == 0.35 ** 2


def test_n_trains_1_matches_original_single_arc_behavior(load_main):
    # Regression: default N_TRAINS=1 must render byte-identical to the
    # pre-multi-train SandTimerContract (a single arc, no dimming).
    m = load_main(N_TRAINS=1, DITHER=False, BRIGHTNESS=1.0)
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([3.0]), 0)
    assert _lit(m.np) == [0, 1, 2]
    assert m.np.buf[0] == m.np.buf[2]  # uniform brightness — no falloff applied


def test_two_trains_render_as_nested_bands(load_main):
    m = load_main(
        N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0, GAMMA=1.0,
        BACKGROUND_BRIGHTNESS=0.35, MINUTES_PER_LED=1, NUM_LEDS=8,
    )
    sig = m.LeaveSignal([2.0, 6.0])  # primary arc_len=2, secondary arc_len=6
    m.ACTIVE_CONTRACT.render(sig, 0)
    bright = m.np.buf[0]
    dim = m.np.buf[3]
    assert _lit(m.np) == [0, 1, 2, 3, 4, 5]  # primary's 2 + secondary's extra 4
    assert bright == m.np.buf[1]  # primary band uniform
    assert dim == m.np.buf[2] or dim == m.np.buf[5]  # secondary band uniform
    assert bright != dim
    assert bright[0] > dim[0]  # primary strictly brighter than the background band


def test_equal_extent_overlap_favors_the_primary(load_main):
    # Two trains whose ttls round up to the SAME arc length — the primary
    # (brighter) must win the overlap, not the later/dimmer train.
    m = load_main(N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0, GAMMA=1.0,
                  MINUTES_PER_LED=1)
    assert m._arc_len(2.5) == m._arc_len(2.9) == 3
    sig = m.LeaveSignal([2.5, 2.9])
    m.ACTIVE_CONTRACT.render(sig, 0)
    primary_color = m.PALETTE[sig.urgency]
    full_level = tuple(int(c * m.BRIGHTNESS) for c in primary_color)
    assert m.np.buf[0] == m.np.buf[1] == m.np.buf[2] == full_level


def test_fewer_ttls_than_n_trains_does_not_crash(load_main):
    m = load_main(N_TRAINS=3, DITHER=False, BRIGHTNESS=1.0)
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([4.0]), 0)  # only 1 available
    assert _lit(m.np) == [0, 1, 2, 3]


def test_color_contract_ignores_n_trains(load_main):
    # ColorContract has no arc/length axis — always the full bar, one layer,
    # regardless of N_TRAINS. Confirms it wasn't accidentally wired in.
    m = load_main(CONTRACT="color", N_TRAINS=3, DITHER=False, BRIGHTNESS=1.0)
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([2.0, 6.0, 10.0]), 0)
    assert _lit(m.np) == list(range(m.NUM_LEDS))
    assert len(set(m.np.buf)) == 1  # uniform — no per-train dimming


def test_breathing_combines_layer_falloff_with_breath(load_main):
    # BreathingContract multiplies _layer_mult(i) * breath — verify the
    # secondary band is dimmer than the primary at the same phase, not just
    # equal-but-breathing-together.
    m = load_main(N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0, GAMMA=1.0,
                  CONTRACT="breathing", MINUTES_PER_LED=1)
    sig = m.LeaveSignal([2.0, 6.0])
    m.ACTIVE_CONTRACT.render(sig, 1100)  # arbitrary phase, non-zero breath
    assert m.np.buf[0][0] > m.np.buf[3][0] > 0
