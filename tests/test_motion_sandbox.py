"""The five motion words — docs/contracts/light-language.md §3.

Only the pure geometry is checkable here. Whether the words are
DISTINGUISHABLE THROUGH GLASS is the actual open question and is
answered on hardware by `make motion-sandbox`, not by any assertion —
same division test_gesture_sandbox.py already draws between "the
constants can't saturate" (checkable) and "do real taps cluster"
(empirical).

What these do catch is the class of bug that would waste a bench
session: a word that never reaches its destination, one that lights an
LED outside the bounds it is supposed to respect, or a mult above 1.0
that silently clamps to white the way ACK_PEAK_CEIL once did.
"""

import importlib
import sys


def _load(load_main, **overrides):
    load_main(**overrides)
    sys.modules.pop("motion_sandbox", None)
    return importlib.import_module("motion_sandbox")


def _peak(mults):
    return max(range(len(mults)), key=lambda i: mults[i])


def _lit(mults, floor=0.001):
    return [i for i, v in enumerate(mults) if v > floor]


# ── Easing: the deceleration rule (§5) ───────────────────────────


def test_easings_share_endpoints(load_main):
    """Only the MIDDLE may differ — otherwise the A/B isn't isolating
    velocity, it's comparing two different journeys."""
    m = _load(load_main)
    for ease in (m.linear, m.ease_out, m.ease_in_out):
        assert abs(ease(0.0) - 0.0) < 1e-9
        assert abs(ease(1.0) - 1.0) < 1e-9


def test_ease_out_is_ahead_of_linear_throughout(load_main):
    """Decelerating means covering ground EARLY and arriving slowly. If
    ease_out ever lagged linear it would be accelerating, which is the
    spinner feel the rule exists to avoid."""
    m = _load(load_main)
    for i in range(1, 100):
        t = i / 100.0
        assert m.ease_out(t) > m.linear(t)


# ── The words reach their destinations ───────────────────────────


def test_inward_starts_at_the_ends_and_lands_on_the_anchor(load_main):
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    at_start = m.inward(0)
    assert _lit(at_start)[0] == 0
    assert _lit(at_start)[-1] == 20
    assert _peak(m.inward(1600)) == 10


def test_outward_starts_at_the_anchor(load_main):
    """The strike point is the station, not the strip's centre — the
    distinction only shows up when they differ."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=4)
    assert _peak(m.outward(0)) == 4


def test_outward_decays_as_it_travels(load_main):
    """Energy leaving. A word that radiated at constant amplitude would
    read as an expanding thing rather than a dissipating one."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    early = max(m.outward(50))
    late = max(m.outward(700))
    assert late < early


def test_around_reaches_every_led(load_main):
    """One lap must actually be one lap. An easing or wrap bug that
    stalled the comet would show as a dead arc on the far side."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    seen = [0.0] * 21
    for phase in range(0, 1400, 10):
        for i, v in enumerate(m.around(phase)):
            seen[i] = max(seen[i], v)
    assert all(v > 0.0 for v in seen)


def test_shake_never_leaves_its_bounds(load_main):
    """It bounces against the label edge; escaping the bounds would make
    the "no" read as motion that went somewhere — the opposite of the
    message. Tolerance is the blob's own width, not slack."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    a, b = m.SHAKE_BOUNDS
    for phase in range(0, 650, 5):
        for i in _lit(m.shake(phase)):
            assert a - 2 <= i <= b + 2


def test_shake_decays_to_nothing(load_main):
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    assert max(m.shake(640)) < max(m.shake(0))


# ── Invariants every word must hold ──────────────────────────────


def test_every_word_returns_a_full_frame_within_range(load_main):
    """Length NUM_LEDS and mult in [0, 1].

    The ceiling is the one that matters: _write_frame gamma-corrects,
    and gamma(mult) for mult > 1 grows FASTER than mult, so an
    overshooting word clamps to white long before BRIGHTNESS does. That
    is exactly the bug ACK_PEAK_CEIL shipped with (test_gesture_sandbox
    docstring), caught there only after real hardware."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    for name, (fn, kwargs, ms) in m.WORDS.items():
        for phase in range(0, ms + 200, 25):
            frame = fn(phase, **kwargs)
            assert len(frame) == 21, name
            assert all(0.0 <= v <= 1.0 for v in frame), (name, phase)


def test_blob_interpolates_across_neighbours(load_main):
    """Sub-LED positioning is what makes 21 LEDs read as one thing
    moving instead of a chase of discrete dots — and thick glass blurs
    each dot without connecting them, so this cannot be fixed later by
    the enclosure."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    mults = [0.0] * 21
    m._blob(mults, 10.5, width=1.4)
    assert mults[10] > 0.0 and mults[11] > 0.0
    assert abs(mults[10] - mults[11]) < 1e-9   # dead centre → equal split
