# micropython/primitives.py — eki-bin
# Pure animation math: phase/shape helpers, easing, colour transforms.
# Extracted verbatim from main.py by the V1.6 split
# (docs/v1.6-refactor.md) — MOVED, not rewritten.
#
# "Pure" is load-bearing, not decorative. Nothing here touches the strip,
# the clock, or any hardware, which is why this is the best-tested layer in
# the firmware and why it was safe to extract early. Keep it that way: if
# something here ever needs `np` or `time.ticks_ms()`, it belongs in
# leds.py or a contract instead.
#
# [→ Rust] This is the layer that ports most directly — pure functions over
# f32, no HAL, no ownership questions.

import math

from settings import *  # noqa: F401,F403

# ─────────────────────────────────────────────────────────────
# Animation primitives  ←  YOUR PART (reusable building blocks)
# ─────────────────────────────────────────────────────────────
# Pure, LED-free helpers that contracts compose into motion. Keeping them pure
# means they're host-testable (no hardware) and reused across every contract,
# instead of each one re-deriving wave math. Three layers:
#   A. phase / shape — turn elapsed time into a 0.0–1.0 wave
#   B. envelopes     — named brightness multipliers (breathe / blink / pulse)
#   C. colour        — interpolate / dim (r, g, b) tuples
# Candidates to extract into a separate animations.py once they settle.
#
# `dim` and `lerp_color` are worked examples — they set the pattern; you draft
# the rest. None are wired into a contract yet, so stubs are safe to leave.


# ── A. phase / shape (all take/return 0.0–1.0) ──────────────────
def phase_sawtooth(elapsed_ms, period_ms):
    """Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return elapsed_ms % period_ms / period_ms


def phase_exp_sawtooth(elapsed_ms, period_ms):
    """Exponential/surved Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return ((elapsed_ms % period_ms) / period_ms) ** 2


def phase_inv_parabola(elapsed_ms, period_ms):
    """inverse parabolic Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return 1 - ((elapsed_ms % period_ms) / period_ms) ** 2


def tri01(p):
    """Triangle from a 0..1 phase: 0 → 1 (at p=0.5) → 0."""
    return 1 - abs(2 * p - 1)


def sine01(p):
    """Smooth sine from a 0..1 phase, starting at 0: 0 → 1 → 0."""
    return 0.5 * (1 - math.cos(2 * math.pi * p))


def square01(p, duty=0.5):
    """Hard gate from a 0..1 phase: 1.0 while p < duty, else 0.0."""
    return 1.0 if p < duty else 0.0


# ── B. brightness envelopes (elapsed_ms → 0.0–1.0 multiplier) ───
# Each composes layer A and maps into [floor, ceiling] so the arc never fully
# dies (floor) and — new — never needs to reach full-static brightness either
# (ceiling). Default ceiling=1.0 keeps every existing call byte-identical;
# pass a lower ceiling for a layer that should never be mistaken for a
# fully-lit primary at its peak (e.g. a breathing 2nd-train band — see
# docs/insights.md §6: "don't want to mistake bright mode for all lit").
def breathe(elapsed_ms, period_ms=8000, floor=0.2, ceiling=1.0):
    """Smooth in/out glow."""
    return floor + (ceiling - floor) * sine01(phase_sawtooth(elapsed_ms, period_ms))


def breathe_exponent(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """exponential build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_exp_sawtooth(elapsed_ms, period_ms))


def breathe_inverse(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """inverse build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_inv_parabola(elapsed_ms, period_ms))


def blink(elapsed_ms, period_ms=600, duty=0.5, floor=0.2, ceiling=1.0):
    """Hard on/off between `floor` and `ceiling` (`duty` = fraction of the cycle 'on')."""
    return floor + (ceiling - floor) * square01(phase_sawtooth(elapsed_ms, period_ms), duty)


def pulse(elapsed_ms, period_ms=1000, floor=0.1, ceiling=1.0):
    """Sharp triangular ramp up/down, mapped into [floor, ceiling]."""
    return floor + (ceiling - floor) * tri01(phase_sawtooth(elapsed_ms, period_ms))


# ── C. colour helpers ───────────────────────────────────────────
def dim(color, mult):
    """Scale an (r, g, b) by mult (0.0–1.0). Worked example — the pattern."""
    return tuple(int(c * mult) for c in color)


def lerp_color(c0, c1, t):
    """Blend c0 → c1 as t goes 0 → 1 (per-channel linear). Worked example.
    Lets a contract *fade* between urgency colours instead of snapping bands."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def _rgb_to_hsv(r, g, b):
    """(r,g,b) each 0..1 → (h,s,v) each 0..1. Standard reference algorithm
    (same one CPython's colorsys uses — not reinvented, just inlined since
    MicroPython doesn't ship that module)."""
    maxc, minc = max(r, g, b), min(r, g, b)
    v = maxc
    if maxc == minc:
        return 0.0, 0.0, v
    s = (maxc - minc) / maxc
    rc = (maxc - r) / (maxc - minc)
    gc = (maxc - g) / (maxc - minc)
    bc = (maxc - b) / (maxc - minc)
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    return (h / 6.0) % 1.0, s, v


def _hsv_to_rgb(h, s, v):
    """(h,s,v) each 0..1 → (r,g,b) each 0..1. Inverse of _rgb_to_hsv."""
    if s == 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    return v, p, q


def hue_rotate(color, degrees):
    """Shift a colour's HUE by `degrees` (can be any number, wraps mod 360),
    keeping saturation and brightness the same — a "similar yet distinguishable"
    variant, e.g. for a 2nd train's colour instead of dimming it (dimming alone
    doesn't work well on bare-strip hardware — see docs/insights.md §6: at low
    brightness, dithering runs out of headroom and diffusion runs out of light).
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r, g, b = _hsv_to_rgb(h, s, v)
    # round, not truncate — a 360° round-trip should be a lossless identity,
    # not off-by-one from floating-point drift through the hsv conversion.
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def desaturate(color, saturation):
    """Scale a colour's SATURATION by `saturation` (0.0 = fully gray, 1.0 =
    unchanged), keeping hue and value the same — a genuinely MUTED variant of
    a colour, not just a dimmer one. `hue_rotate()`'s counterpart on the other
    HSV axis: hue_rotate keeps the same brightness/vividness and shifts which
    colour it is; desaturate keeps the same colour/brightness and shifts how
    vivid it is.

    Distinct from just lowering a render `mult` (brightness): scaling
    brightness scales R/G/B by the same factor, which is mathematically
    identical to picking a *dimmer* version of the same colour — it can't
    produce a *muted* (desaturated, toward-gray) version, since that requires
    each channel to move toward the colour's own maximum channel value, not
    toward zero. Used for ApproachContract's LINE_COLOR (LINE_SATURATION) —
    see docs/contracts/approach-contract.md.
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    s *= max(0.0, saturation)
    r, g, b = _hsv_to_rgb(h, s, v)
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


# ── D. perceptual correction  ←  YOUR PART ──────────────────────
def gamma(mult, g=GAMMA):
    """Perceptual-brightness correction for an animation multiplier (0..1 → 0..1).

    Why: the eye responds ~logarithmically but WS2812B PWM is linear, so a linear
    fade looks steppy/uneven — worst at the dim end. Raising the multiplier to a
    power `g` (≈2.2–2.8) spreads the visible steps to match perception. This is
    the single biggest smoothness win for the breath — bigger than frame rate.

    Contract: monotonic; endpoints fixed (gamma(0)=0, gamma(1)=1); stays in [0,1].
    Applied to `mult` in _paint (not the base colour), so static contracts — which
    pass mult=1.0 → gamma(1.0)=1.0 — are unaffected.

    TODO(you): return mult ** g   (that's the whole thing; g comes from config).
    Currently a no-op pass-through so the display keeps working until you fill it.

    ⚠ Interaction to watch: gamma pushes the dim end *down* (0.2 ** 2.2 ≈ 0.03), so
    after you enable it the breath will dip closer to black — you may want to raise
    BREATHE_FLOOR to keep it visible through the jar.
    """
    return mult ** g

