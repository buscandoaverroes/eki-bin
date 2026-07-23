"""Animation primitives — pure wave/colour math. This file would have caught the
inverted `tri01` (and the negative `pulse` it caused)."""

import math


def test_phase_sawtooth_wraps(load_main):
    m = load_main()
    assert m.phase_sawtooth(0, 1000) == 0.0
    assert m.phase_sawtooth(500, 1000) == 0.5
    assert m.phase_sawtooth(1000, 1000) == 0.0  # wraps


def test_tri01_peaks_at_half(load_main):
    m = load_main()
    assert m.tri01(0) == 0
    assert m.tri01(0.5) == 1
    assert m.tri01(1) == 0
    # never negative across the range
    assert all(m.tri01(p / 100) >= 0 for p in range(0, 101))


def test_sine01_zero_to_one_to_zero(load_main):
    m = load_main()
    assert abs(m.sine01(0)) < 1e-9
    assert abs(m.sine01(0.5) - 1) < 1e-9
    assert abs(m.sine01(1)) < 1e-9


def test_square01_duty(load_main):
    m = load_main()
    assert m.square01(0.2, duty=0.5) == 1.0
    assert m.square01(0.7, duty=0.5) == 0.0


def test_envelopes_stay_in_unit_range(load_main):
    m = load_main()
    for fn in (m.breathe, m.blink, m.pulse):
        vals = [fn(t) for t in range(0, 2400, 25)]
        assert min(vals) >= 0.0, fn.__name__
        assert max(vals) <= 1.0, fn.__name__


def test_pulse_respects_floor(load_main):
    m = load_main()
    # default floor is 0.1 — the dim end must never dip below it
    assert min(m.pulse(t) for t in range(0, 1001, 25)) >= 0.1 - 1e-9


def test_ceiling_default_is_backward_compatible(load_main):
    # ceiling=1.0 by default — every pre-existing call site (which never
    # passed ceiling) must behave exactly as before.
    m = load_main()
    for fn in (m.breathe, m.breathe_exponent, m.breathe_inverse, m.blink, m.pulse):
        vals = [fn(t) for t in range(0, 2400, 25)]
        assert max(vals) <= 1.0 + 1e-9, fn.__name__


def test_ceiling_caps_the_peak(load_main):
    # A capped ceiling must never be exceeded — this is the whole point: a
    # background layer's peak should never reach "primary, fully lit."
    m = load_main()
    for fn in (m.breathe, m.breathe_exponent, m.breathe_inverse, m.blink, m.pulse):
        vals = [fn(t, floor=0.2, ceiling=0.7) for t in range(0, 4000, 25)]
        assert max(vals) <= 0.7 + 1e-9, fn.__name__
        assert min(vals) >= 0.2 - 1e-9, fn.__name__


def test_colour_helpers(load_main):
    m = load_main()
    assert m.dim((200, 100, 0), 0.5) == (100, 50, 0)
    assert m.lerp_color((0, 0, 0), (255, 0, 0), 0.5) == (127, 0, 0)


def test_hue_rotate_full_circle_is_identity(load_main):
    m = load_main()
    color = (255, 100, 0)
    assert m.hue_rotate(color, 360) == color


def test_hue_rotate_known_rotation(load_main):
    m = load_main()
    # pure red (hue 0°) rotated 120° -> pure green; 240° -> pure blue.
    assert m.hue_rotate((255, 0, 0), 120) == (0, 255, 0)
    assert m.hue_rotate((255, 0, 0), 240) == (0, 0, 255)


def test_hue_rotate_preserves_saturation_and_value(load_main):
    m = load_main()
    h, s, v = m._rgb_to_hsv(*(c / 255.0 for c in (200, 100, 50)))
    r, g, b = m.hue_rotate((200, 100, 50), 40)
    h2, s2, v2 = m._rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    assert abs(s - s2) < 0.02
    assert abs(v - v2) < 0.02


def test_hue_rotate_grey_is_unaffected(load_main):
    # zero saturation (grey/white/black) has no hue to shift
    m = load_main()
    assert m.hue_rotate((128, 128, 128), 90) == (128, 128, 128)


def test_desaturate_identity_at_one(load_main):
    m = load_main()
    assert m.desaturate((34, 139, 34), 1.0) == (34, 139, 34)


def test_desaturate_zero_is_grey_at_same_value(load_main):
    m = load_main()
    r, g, b = m.desaturate((200, 50, 50), 0.0)
    assert r == g == b  # fully grey
    _, _, v_before = m._rgb_to_hsv(*(c / 255.0 for c in (200, 50, 50)))
    _, _, v_after = m._rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    assert abs(v_before - v_after) < 0.02  # same brightness, not just same hue


def test_desaturate_preserves_hue_and_value(load_main):
    m = load_main()
    h, _, v = m._rgb_to_hsv(*(c / 255.0 for c in (34, 139, 34)))
    r, g, b = m.desaturate((34, 139, 34), 0.5)
    h2, s2, v2 = m._rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    assert abs(h - h2) < 0.02
    assert abs(v - v2) < 0.02
    assert s2 < 1.0  # actually less saturated, not a no-op


def test_desaturate_is_not_the_same_as_dimming(load_main):
    # The whole reason desaturate() exists: scaling brightness (mult) can only
    # ever produce a DARKER version of the same colour, never a MUTED one — a
    # muted colour's channels move toward each other (toward the colour's own
    # max channel), not toward zero. Confirm desaturate does the latter.
    m = load_main()
    muted = m.desaturate((34, 139, 34), 0.3)
    dimmed = tuple(int(c * 0.5) for c in (34, 139, 34))
    # dimming preserves the channel RATIOS (still exactly forest-green-shaped,
    # just darker); desaturation collapses the channels toward each other.
    assert muted[1] - muted[0] < 139 - 34  # G-R gap shrank (moved toward grey)
    assert dimmed[1] - dimmed[0] == int((139 - 34) * 0.5)  # gap only scaled


def test_gamma_contract(load_main):
    """Holds for the no-op stub AND the real curve: fixed endpoints, monotonic,
    in range. Once gamma() becomes `mult ** g`, add: assert m.gamma(0.5) < 0.5."""
    m = load_main()
    assert m.gamma(0.0) == 0.0
    assert m.gamma(1.0) == 1.0
    vals = [m.gamma(x / 20) for x in range(21)]
    assert all(b >= a for a, b in zip(vals, vals[1:])), "must be monotonic"
    assert all(0.0 <= v <= 1.0 for v in vals)
