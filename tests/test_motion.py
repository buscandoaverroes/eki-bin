"""The motion words as shipped — docs/contracts/light-language.md §3.

The pure geometry is checkable here; whether the words are legible
through a particular bottle is not, and `make motion-sandbox` is where
that gets answered. Same division test_gesture_sandbox.py draws.

The tests that matter most are the last two: they pin the no-op-tap
defect, which is the one thing in this branch that was a BUG rather than
a feature.
"""

import importlib
import sys
import time


def _fake_ticks():
    """`time.ticks_ms`/`ticks_diff` are MicroPython-only and conftest does
    not install them — the existing gesture tests simply never reach a
    line that calls one. The two _handle_tap tests below do, because they
    exercise the full trigger→resolve path rather than a pure helper."""
    if not hasattr(time, "ticks_ms"):
        time.ticks_ms = lambda: int(time.monotonic() * 1000)
        time.ticks_diff = lambda a, b: a - b
        time.sleep_ms = lambda ms: None


def _load(load_main, **overrides):
    load_main(**overrides)
    sys.modules.pop("motion", None)
    return importlib.import_module("motion")


def _peak(m):
    return max(range(len(m)), key=lambda i: m[i])


def _lit(m, floor=0.001):
    return [i for i, v in enumerate(m) if v > floor]


# ── the words reach their destinations ───────────────────────────


def test_outward_starts_at_the_anchor_not_the_middle(load_main):
    """The strike point is the station. Only visible when they differ."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=4)
    assert _peak(m.outward(0)) == 4


def test_outward_decays_as_it_travels(load_main):
    """Energy leaving. Constant amplitude would read as an expanding
    thing rather than a dissipating one."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    assert max(m.outward(700)) < max(m.outward(50))


def test_inward_lands_on_the_anchor(load_main):
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    assert _peak(m.inward(m.MOTION_INWARD_MS)) == 10


def test_around_reaches_every_led(load_main):
    """One lap must be one lap — an easing or wrap bug would show as a
    dead arc on the far side."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    seen = [0.0] * 21
    for phase in range(0, m.MOTION_AROUND_MS, 10):
        for i, v in enumerate(m.around(phase)):
            seen[i] = max(seen[i], v)
    assert all(v > 0.0 for v in seen)


def test_shake_never_leaves_its_bounds(load_main):
    """It bounces against the label edge; escaping would make the "no"
    read as motion that went somewhere — the opposite of the message."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10, SHAKE_BOUNDS=(7, 13))
    for phase in range(0, m.MOTION_SHAKE_MS, 5):
        for i in _lit(m.shake(phase)):
            assert 5 <= i <= 15


def test_no_word_ever_exceeds_full_brightness(load_main):
    """_write_frame gamma-corrects, and gamma(mult) for mult > 1 grows
    FASTER than mult — so an overshooting word clamps to white long
    before BRIGHTNESS does. That is the bug ACK_PEAK_CEIL shipped with."""
    m = _load(load_main, NUM_LEDS=21, ANCHOR_INDEX=10)
    for name, fn in m.WORDS.items():
        for phase in range(0, 4200, 25):
            frame = fn(phase)
            assert len(frame) == 21, name
            assert all(0.0 <= v <= 1.0 for v in frame), (name, phase)


def test_no_word_runs_at_constant_velocity(load_main):
    """light-language.md §5's rule: a loading spinner is constant angular
    velocity, physical rotation decelerates. ease_out is what separates
    "an object moved" from "a machine is thinking"."""
    m = _load(load_main)
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert m.ease_out(t) > t


# ── the no-op tap defect ─────────────────────────────────────────


def test_a_cycle_with_nowhere_to_go_returns_none(load_main):
    """THE defect. _handle_tap used to play its CONFIRM before main.py
    checked len(lines) > 1, so a single-line unit said "yes, done" and
    changed nothing. A confident acknowledgment of a no-op makes a
    working device look broken."""
    _fake_ticks()
    main = load_main(NUM_LEDS=21, MOTION_ENABLED=True)
    sys.modules.pop("gestures", None)
    g = importlib.import_module("gestures")

    class _State:
        def acknowledge(self): pass
        def resolve(self, now, valid): return "cycle"

    played = []
    g.motion.play = lambda word, *a, **k: played.append(word)
    g._capture_with_ack = lambda *a, **k: []
    g.extract_gesture_features = lambda s: {"energy": 0}
    g.classify_valid_input = lambda f: True

    out = g._handle_tap(None, None, 0, 500, _State(), main.LeaveSignal([]),
                        None, main._StatusMessage(), can_cycle=False)
    assert out is None, "the caller must not advance the line"
    assert played == ["shake"], "the answer to an unavailable action is 'no'"


def test_a_cycle_with_somewhere_to_go_renders_nothing_here(load_main):
    """main.py plays `around` AFTER applying the new line, so the motion
    arrives in the new line's colour and IS the transition rather than a
    preface to it (light-language.md §4)."""
    _fake_ticks()
    main = load_main(NUM_LEDS=21, MOTION_ENABLED=True)
    sys.modules.pop("gestures", None)
    g = importlib.import_module("gestures")

    class _State:
        def acknowledge(self): pass
        def resolve(self, now, valid): return "cycle"

    played = []
    g.motion.play = lambda word, *a, **k: played.append(word)
    g._capture_with_ack = lambda *a, **k: []
    g.extract_gesture_features = lambda s: {"energy": 0}
    g.classify_valid_input = lambda f: True

    out = g._handle_tap(None, None, 0, 500, _State(), main.LeaveSignal([]),
                        None, main._StatusMessage(), can_cycle=True)
    assert out == "cycle"
    assert played == []


def test_shake_stays_narrow_enough_to_not_be_a_lap(load_main):
    """Measured 2026-09-14: at ±5 LEDs the shake reads as a short lap of
    `around` and the two words stop being distinguishable — which breaks
    the one thing a vocabulary has to do. ±3 is a head-shake.

    The width is therefore a VOCABULARY constant, not a per-bottle
    preference, and this pins the default against drifting wider."""
    m = _load(load_main, NUM_LEDS=21)
    st = importlib.import_module("settings")
    assert st.SHAKE_HALF_WIDTH <= 3
    a, b = m.SHAKE_BOUNDS
    assert b - a <= 6


def test_shake_centre_is_the_per_unit_half(load_main):
    """Centre moves to the label edge; width does not move with it."""
    m = _load(load_main, NUM_LEDS=21, SHAKE_CENTER=4)
    assert m.SHAKE_BOUNDS == (1, 7)


def test_explicit_bounds_still_win(load_main):
    """An asymmetric bounce is a legitimate thing to want, and splitting
    the constant should not take the option away."""
    m = _load(load_main, NUM_LEDS=21, SHAKE_BOUNDS=(2, 5))
    assert m.SHAKE_BOUNDS == (2, 5)
