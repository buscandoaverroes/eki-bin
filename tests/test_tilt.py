"""The tilt controller — docs/contracts/light-language.md §6, insights.md §15.

Every test here corresponds to something that failed on real hardware.
None of it was testable while the logic lived inside the sandbox's I2C
loop; extracting TiltController into tilt.py is what made the state
machine reachable from synthetic samples.

What still cannot be tested here is the part that matters most — whether
the control FEELS right in a bottle. That is what tilt_freeform.py
collects, and no assertion substitutes for it.
"""

import importlib
import math
import sys


def _load(load_main, **overrides):
    load_main(TILT_ENABLED=True, **overrides)
    sys.modules.pop("tilt", None)
    return importlib.import_module("tilt")


def _g(deg, axis=0):
    """A raw sample for a bottle leaning `deg` from upright.

    Upright is -Z (gravity pulling down on the sensor). Magnitude is
    exactly 1g in the units gestures.py assumes, so it passes the gate.
    """
    lsb = 1.0 / (0.061 / 1000.0)
    r = math.radians(deg)
    lean = [0.0, 0.0, 0.0]
    lean[axis] = math.sin(r) * lsb
    lean[2] = -math.cos(r) * lsb
    return tuple(lean)


def _settle(ctl, m, deg=0.0, ms=0, step=25, axis=0):
    """Feed steady samples for `ms`, returning the last state."""
    state = None
    for i in range(max(1, ms // step)):
        state = ctl.update(_g(deg, axis), (i + 1) * step, step)
    return state


# ── expo ─────────────────────────────────────────────────────────


def test_expo_pins_endpoints_and_softens_the_middle(load_main):
    m = _load(load_main)
    for a in (0.0, 0.6, 1.0):
        assert abs(m.expo(0.0, a)) < 1e-9
        assert abs(m.expo(1.0, a) - 1.0) < 1e-9
    assert m.expo(0.5, 0.6) < 0.5


# ── gate 1: the magnitude test that kills tap spoofing ───────────


def test_a_tap_sized_sample_is_rejected(load_main):
    """The observed failure: a hard tap on a bottle sitting FLAT spoofed a
    30-40° tilt about one time in five. Tilting preserves |a| = 1g."""
    m = _load(load_main)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    before = ctl.rejected
    tap = tuple(c * 3.0 for c in _g(0.0))     # 3g — unmistakably an impulse
    assert ctl.update(tap, 5000, 25) == "wait"
    assert ctl.rejected == before + 1


def test_a_real_tilt_is_not_rejected(load_main):
    m = _load(load_main)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    assert ctl.update(_g(20.0), 5000, 25) != "wait"


# ── gate 2: neutral is re-learned, not fixed at startup ──────────


def test_a_bottle_resting_off_level_becomes_neutral(load_main):
    """THE bug: the reference was captured once, so a bottle sitting at
    8.1° read 8.1° forever, never fell inside the deadzone, never
    released, and crept the brightness down the whole time."""
    m = _load(load_main)
    ctl = m.TiltController()
    ctl.update(_g(0.0), 0, 25)                 # startup reference at level
    # now it lives at 6° — inside the deadzone, so the baseline should leak
    _settle(ctl, m, 6.0, ms=6000)
    assert ctl.deg < 1.0, "neutral should have drifted to where it rests"


def test_the_baseline_does_not_eat_a_deliberate_tilt(load_main):
    """The leak is gated on not-engaged for exactly this reason — if it ran
    during a session, a slow deliberate tilt would be absorbed instead of
    obeyed."""
    m = _load(load_main)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    _settle(ctl, m, 25.0, ms=2000)
    assert ctl.engaged
    assert ctl.deg > 20.0


# ── gate 3: stillness is duration, not depth ─────────────────────


def test_holding_a_tilt_briefly_does_not_re_baseline(load_main):
    """The overcorrection: a hand holding 25° to aim passed a loose
    stillness test, and 25° became neutral — the same poisoned reference
    one layer in. Measured hand-held quiet runs top out near 2.75s."""
    m = _load(load_main, TILT_STILL_MS=6000)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    state = _settle(ctl, m, 25.0, ms=2500)
    assert state in ("up", "down")
    assert ctl.engaged, "2.5s of stillness is within reach of a human hand"


def test_setting_it_down_does_re_baseline(load_main):
    m = _load(load_main, TILT_STILL_MS=6000)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    _settle(ctl, m, 25.0, ms=2000)
    assert ctl.engaged
    _settle(ctl, m, 25.0, ms=8000)             # left alone on a surface
    assert not ctl.engaged
    assert ctl.deg < 1.0, "wherever it was set down is neutral now"


# ── the control itself ───────────────────────────────────────────


def test_brightness_moves_and_respects_its_rails(load_main):
    m = _load(load_main, TILT_MIN_BRIGHT=0.05, TILT_MAX_BRIGHT=0.90,
              TILT_RATE_PER_SEC=0.20, BRIGHTNESS=0.30)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    _settle(ctl, m, 35.0, ms=30000)
    assert m.settings.BRIGHTNESS == 0.90


def test_the_deadzone_holds_the_value(load_main):
    """Return to upright and the value stops and stays.

    ⚠ It does NOT stop instantly, and that is correct rather than a bug:
    TILT_SMOOTH_ALPHA makes the filtered angle lag the real one by ~150ms,
    so a snap back from 20° spends a few more samples above the deadzone
    on the way down. Measured here it is worth about 0.002 of brightness —
    below TARGET_TOLERANCE, below one LED of the bar, and the price of the
    smoothing that keeps a glancing knock from registering as a tilt.

    So the assertion is "it settles and then holds", not "it stops on the
    same sample" — an earlier version asserted the latter and failed on
    exactly this lag."""
    m = _load(load_main, BRIGHTNESS=0.30)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    _settle(ctl, m, 20.0, ms=1000)
    moved = m.settings.BRIGHTNESS
    assert moved > 0.30

    _settle(ctl, m, 2.0, ms=500)               # back to upright; filter drains
    settled = m.settings.BRIGHTNESS
    assert settled - moved < 0.01, "the lag must be small, not absent"

    _settle(ctl, m, 2.0, ms=4000)              # and now it must not budge
    assert m.settings.BRIGHTNESS == settled


def test_reversing_takes_as_long_as_you_like(load_main):
    """The sandbox tied the reversal window to the release timer, so
    turning around slowly forgot the axis and the next tilt meant UP
    again. Stillness-based release dissolves that: upright-in-hand is not
    still, so the session survives an arbitrarily slow reversal."""
    m = _load(load_main, TILT_STILL_MS=6000, BRIGHTNESS=0.30)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    _settle(ctl, m, 25.0, ms=1000)
    up_axis = ctl.axis
    _settle(ctl, m, 3.0, ms=4000)              # dawdling through neutral
    assert ctl.engaged, "the axis must survive a slow reversal"
    assert ctl.axis == up_axis


# ── hitting a brightness rail ────────────────────────────────────


def test_a_fresh_rail_hit_is_reported_once(load_main):
    """A rail is invisible — the display simply stops changing, and
    "already at maximum" looks exactly like "not working". That is how the
    first hardware session read it, and how 24h of real use read it again."""
    m = _load(load_main, BRIGHTNESS=0.89, TILT_MAX_BRIGHT=0.90,
              TILT_RATE_PER_SEC=0.20, TILT_RAIL_REPEAT_MS=900)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    hits = 0
    for i in range(40):                      # 1s of pushing past the top
        ctl.update(_g(35.0), 1000 + i * 25, 25)
        if ctl.rail_bounce:
            hits += 1
    assert m.settings.BRIGHTNESS == 0.90
    assert hits == 1, "throttled — a held tilt is one request, not forty"


def test_the_rail_repeats_while_you_keep_pushing(load_main):
    """Throttled, not edge-only: holding past the rail is a CONTINUOUS
    request, so answering once and then going quiet is the same silence
    the recoil exists to break."""
    m = _load(load_main, BRIGHTNESS=0.89, TILT_MAX_BRIGHT=0.90,
              TILT_RAIL_REPEAT_MS=400)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    hits = sum(1 for i in range(80)
               if (ctl.update(_g(35.0), 1000 + i * 25, 25),
                   ctl.rail_bounce)[1])
    assert hits >= 4, "2s past the rail at a 400ms throttle"


def test_both_rails_answer(load_main):
    """Symmetric on purpose. The top is the stronger metaphor — a bottle
    bounces off a table — but both are the same fact, "no further", and
    answering only one would be the more arbitrary choice."""
    m = _load(load_main, BRIGHTNESS=0.06, TILT_MIN_BRIGHT=0.05,
              TILT_FIRST_MEANS="down")
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    seen = set()
    for i in range(40):
        ctl.update(_g(35.0), 1000 + i * 25, 25)
        if ctl.rail_bounce:
            seen.add(ctl.rail_bounce)
    assert seen == {"min"}


def test_no_bounce_while_there_is_room_to_move(load_main):
    m = _load(load_main, BRIGHTNESS=0.40, TILT_MIN_BRIGHT=0.05,
              TILT_MAX_BRIGHT=0.90)
    ctl = m.TiltController()
    _settle(ctl, m, 0.0, ms=1000)
    for i in range(40):
        ctl.update(_g(30.0), 1000 + i * 25, 25)
        assert ctl.rail_bounce is None


# ── rate independence: the same motion, at different loop rates ───
# Replay of real recordings found the controller engaged on deliberate tilts
# 9/10 times at 57 Hz and 2/10 at 240 Hz (scripts/replay.py, 2026-10-04):
# every constant counted SAMPLES. They are durations now; these pin that the
# same physical motion gives the same answer at any rate the loop runs.

def _drive(ctl, script, hz):
    """script: list of (duration_ms, deg_at_end) linear ramps. Returns the
    controller's (time_ms, state, engaged) at every update."""
    step = 1000.0 / hz
    t, deg, out = 0.0, 0.0, []
    for dur, target in script:
        start, t0 = deg, t
        while t < t0 + dur:
            t += step
            frac = min(1.0, (t - t0) / dur)
            deg = start + (target - start) * frac
            state = ctl.update(_g(deg), int(t), step)
            out.append((t, state, ctl.engaged))
    return out


def _first_engaged_ms(trace):
    return next((t for t, _s, e in trace if e), None)


import pytest  # noqa: E402


@pytest.mark.parametrize("hz", [20, 40, 57, 139, 240])
def test_a_slow_deliberate_tilt_engages_at_every_loop_rate(load_main, hz):
    m = _load(load_main)
    ctl = m.TiltController()
    trace = _drive(ctl, [(1000, 0.0), (3000, 25.0), (2000, 25.0)], hz)
    assert _first_engaged_ms(trace) is not None, f"never engaged at {hz} Hz"


def test_engage_time_does_not_depend_on_loop_rate(load_main):
    times = []
    for hz in (40, 240):
        m = _load(load_main)
        times.append(_first_engaged_ms(_drive(m.TiltController(),
                                              [(1000, 0.0), (1500, 20.0), (1000, 20.0)], hz)))
    assert abs(times[0] - times[1]) < 60, times


@pytest.mark.parametrize("hz", [40, 240])
def test_resting_off_level_re_learns_neutral_at_the_same_speed(load_main, hz):
    m = _load(load_main)
    ctl = m.TiltController()
    _drive(ctl, [(500, 0.0), (100, 6.0), (6000, 6.0)], hz)
    assert ctl.deg < 1.0


def test_time_constants_default_to_what_was_tuned(load_main):
    m = _load(load_main, TILT_SMOOTH_ALPHA=0.15, TILT_ENGAGE_SAMPLES=4,
              TILT_STILL_WINDOW=24, TILT_BASELINE_ALPHA=0.02)
    assert abs(m.SMOOTH_TAU_MS - 153.9) < 1.0
    assert m.ENGAGE_MS == 75.0 and m.STILL_WINDOW_MS == 575.0
    assert abs(m.BASELINE_TAU_MS - 1237.5) < 1.0


def test_explicit_millisecond_knobs_win(load_main):
    m = _load(load_main, TILT_SMOOTH_TAU_MS=100, TILT_ENGAGE_MS=50)
    assert m.SMOOTH_TAU_MS == 100.0 and m.ENGAGE_MS == 50.0


def test_alpha_is_the_same_smoother_at_any_rate(load_main):
    m = _load(load_main)
    # 10 updates of 10 ms must decay exactly like 1 update of 100 ms
    x = 1.0
    for _ in range(10):
        x *= 1 - m.alpha(10, 154.0)
    assert abs(x - (1 - m.alpha(100, 154.0))) < 1e-9
