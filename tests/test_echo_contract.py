"""EchoContract — primary static, secondary+ hue-shifted + gently breathing.

Built from the sandbox-tested winning combination in docs/insights.md §6:
brightness-only differentiation didn't work on real hardware, colour + subtle
motion (staying near-full brightness throughout) did.
"""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


def test_layer_hue_shift_scales_with_index(load_main):
    m = load_main(SECONDARY_HUE_SHIFT_DEG=20)
    assert m._layer_hue_shift(0) == 0  # primary: no shift
    assert m._layer_hue_shift(1) == 20
    assert m._layer_hue_shift(2) == 40


def test_primary_layer_is_static_full_brightness(load_main):
    # The primary must render identically to SandTimer's plain, unshifted
    # colour at full mult — regardless of phase_ms (no animation on layer 0).
    m = load_main(CONTRACT="echo", N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0,
                  GAMMA=1.0, MINUTES_PER_LED=1)
    sig = m.LeaveSignal([2.0, 6.0])
    base_color = m.PALETTE[sig.urgency]
    expected = tuple(int(c * m.BRIGHTNESS) for c in base_color)
    for phase in (0, 500, 1500, 2900):
        m.ACTIVE_CONTRACT.render(sig, phase)
        assert m.np.buf[0] == expected, f"phase={phase}"


def test_secondary_layer_is_hue_shifted(load_main):
    m = load_main(CONTRACT="echo", N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0,
                  GAMMA=1.0, MINUTES_PER_LED=1, SECONDARY_HUE_SHIFT_DEG=20)
    sig = m.LeaveSignal([2.0, 6.0])
    base_color = m.PALETTE[sig.urgency]
    m.ACTIVE_CONTRACT.render(sig, 0)
    secondary_pixel = m.np.buf[3]  # inside the secondary's band, past the primary's
    assert secondary_pixel != base_color  # colour actually differs
    # confirm it's specifically the hue-rotated variant, at *some* brightness
    shifted = m.hue_rotate(base_color, m._layer_hue_shift(1))
    ratio = secondary_pixel[0] / shifted[0] if shifted[0] else None
    assert ratio is None or 0.5 <= ratio <= 1.0  # same hue direction, scaled by breath


def test_secondary_layer_stays_above_floor(load_main):
    # The whole point: never dip into the low-brightness flicker zone.
    m = load_main(CONTRACT="echo", N_TRAINS=2, DITHER=False, BRIGHTNESS=1.0,
                  GAMMA=1.0, MINUTES_PER_LED=1,
                  SECONDARY_BREATHE_FLOOR=0.7, SECONDARY_BREATHE_PERIOD_MS=3000)
    sig = m.LeaveSignal([2.0, 6.0])
    base_color = m.PALETTE[sig.urgency]
    shifted = m.hue_rotate(base_color, m._layer_hue_shift(1))
    brightest_channel = max(shifted)
    seen = []
    for phase in range(0, 3000, 100):
        m.ACTIVE_CONTRACT.render(sig, phase)
        seen.append(m.np.buf[3][shifted.index(brightest_channel)] if brightest_channel else 0)
    if brightest_channel:
        floor_value = brightest_channel * 0.7
        assert min(seen) >= floor_value - 1  # -1 for int() rounding


def test_n_trains_1_echo_matches_sandtimer_static(load_main):
    # With only the primary shown, EchoContract must render identically to a
    # plain static arc — no secondary layer means no animation-driven change.
    m = load_main(CONTRACT="echo", N_TRAINS=1, DITHER=False, BRIGHTNESS=1.0, GAMMA=1.0)
    sig = m.LeaveSignal([3.0])
    m.ACTIVE_CONTRACT.render(sig, 0)
    frame_a = list(m.np.buf)
    m.ACTIVE_CONTRACT.render(sig, 1500)  # different phase — should look the same
    assert list(m.np.buf) == frame_a


def test_echo_registered_and_hidden_clears(load_main):
    m = load_main(CONTRACT="echo")
    assert isinstance(m.ACTIVE_CONTRACT, m.EchoContract)
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)
    assert _lit(m.np) == []
