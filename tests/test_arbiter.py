"""The arbiter — micropython/arbiter.py, docs/imu-interaction-plan.md §2.

A classified tap is a claim; these pin how each kind of claim is settled,
on hand-built sequences where the right answer is known by construction.
What they cannot say is whether the thresholds are right — that is
scripts/sim.py's job, on recordings.
"""

import importlib
import random
import sys

import pytest

DT = 1000.0 / 240


def _load(load_main, **overrides):
    load_main(**overrides)
    sys.modules.pop("arbiter", None)
    return importlib.import_module("arbiter")


@pytest.fixture
def ar(load_main):
    return _load(load_main)


def _run(arb, t_from, t_to, jitter_mg=0.5, gyro=0.2, tilting=False, seed=1):
    """Feed samples from t_from to t_to: an upright bottle with `jitter_mg`
    of noise and a steady rotation rate. Returns every decision made."""
    rnd = random.Random(seed)
    out, t = [], t_from
    while t < t_to:
        a = (rnd.gauss(0, jitter_mg), rnd.gauss(0, jitter_mg), 1000.0 + rnd.gauss(0, jitter_mg))
        g = gyro(t) if callable(gyro) else gyro
        out += arb.update(int(t), a, g, tilting(t) if callable(tilting) else tilting)
        t += DT
    return out


def test_a_still_tap_commits_once_classify_agrees(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000)                       # a quiet bottle beforehand
    arb.claim(3000)
    assert _run(arb, 3000, 4200) == []       # proved still at +600, but no verdict yet
    arb.verdict(3000, True)
    assert _run(arb, 4200, 4210) == [(ar.COMMIT, 3000, None)]


def test_classify_saying_no_is_passed_on_not_overruled(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, False, "gyro")
    assert _run(arb, 3000, 3010) == [(ar.REJECT, 3000, "gyro")]


def test_a_hold_then_tilt_is_vetoed_when_the_rotation_starts(ar):
    # The guided session's H trial: a grab, a ~1 s still hold (with the
    # hand's tremor), then rotation.
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, True)
    out = _run(arb, 3000, 5000, jitter_mg=2.5, gyro=lambda t: 40.0 if t > 4000 else 0.3)
    assert out == [(ar.VETO, 3000, "handled after")]


def test_once_proved_still_a_later_grab_cannot_undo_the_tap(ar):
    # The D trial: a tap, a second of stillness, then a grab and tilt.
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    _run(arb, 3000, 3700)                                  # still through +600
    out = _run(arb, 3700, 4300, gyro=40.0, jitter_mg=5.0)   # the grab
    arb.verdict(3000, True)
    assert out + _run(arb, 4300, 4310, gyro=40.0) == [(ar.COMMIT, 3000, None)]


def test_a_tap_with_a_hand_on_the_bottle_never_settles(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, True)
    out = _run(arb, 3000, 5200, jitter_mg=3.0)             # tremor, no rotation
    assert out == [(ar.VETO, 3000, "not still")]


def test_letting_go_is_vetoed_by_what_came_before(ar):
    # A release or set-down: rotation (the hand moving it) ending just
    # before the trigger.
    arb = ar.Arbiter()
    _run(arb, 0, 3000, gyro=lambda t: 30.0 if 1500 < t < 2500 else 0.2)
    arb.claim(3200)
    assert _run(arb, 3200, 3210) == [(ar.VETO, 3200, "handled before")]


def test_handling_long_enough_ago_is_forgiven(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 6000, gyro=lambda t: 30.0 if 1500 < t < 2500 else 0.2)
    arb.claim(6000)                                       # 3.5 s after it ended
    arb.verdict(6000, True)
    assert _run(arb, 6000, 6700) == [(ar.COMMIT, 6000, None)]


def test_a_taps_own_ring_down_is_not_handling(ar):
    # A tap rocks the bottle: >10 dps is over by ~170 ms (guided session).
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, True)
    out = _run(arb, 3000, 3700, gyro=lambda t: 25.0 if t < 3160 else 0.2)
    assert out == [(ar.COMMIT, 3000, None)]


def test_active_tilting_vetoes_but_an_open_tilt_session_alone_does_not(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, True)
    out = _run(arb, 3000, 3500, jitter_mg=2.5, tilting=lambda t: t > 3300)
    assert out == [(ar.VETO, 3000, "tilt")]


def test_no_gyro_baseline_is_no_rotation_evidence_either_way(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000, gyro=None)
    arb.claim(3000)
    arb.verdict(3000, True)
    assert _run(arb, 3000, 3700, gyro=None) == [(ar.COMMIT, 3000, None)]


def test_claims_settle_independently(ar):
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.claim(3100)
    arb.verdict(3100, False, "vertical")
    arb.verdict(3000, True)
    out = _run(arb, 3000, 3800)
    assert (ar.REJECT, 3100, "vertical") in out and (ar.COMMIT, 3000, None) in out


def test_settings_reach_the_arbiter(load_main):
    ar = _load(load_main, ARBITER_QUIET_MG=5.0)
    arb = ar.Arbiter()
    _run(arb, 0, 3000)
    arb.claim(3000)
    arb.verdict(3000, True)
    # 2 mg per axis ≈ 3.5 mg RMS: vetoed at the default 1.6, settled at 5.0.
    assert _run(arb, 3000, 3700, jitter_mg=2.0) == [(ar.COMMIT, 3000, None)]


def test_the_stillness_sums_are_taken_about_a_nearby_reference(ar):
    # On the device floats are 32-bit: summing x² with gravity in it (~1e6
    # mg²) and subtracting the squared mean loses a ~1 mg² variance. Sums
    # about the window's first sample stay a few mg. Host floats are 64-bit,
    # so assert the sums directly rather than the (correct either way) RMS.
    arb = ar.Arbiter()
    c = arb.claim(0)
    _run(arb, 0, 500, jitter_mg=1.0)
    assert c.n > 50 and max(abs(v) for v in c.ss) / c.n < 10.0


def test_the_rms_is_right(ar):
    arb = ar.Arbiter()
    c = arb.claim(0)
    _run(arb, 0, 700, jitter_mg=1.0, seed=7)
    assert c.rms_mg == pytest.approx(3 ** 0.5, rel=0.25)   # 1 mg on each of three axes


def test_ticks_wrap_does_not_strand_a_claim(ar):
    # ticks_ms wraps at 2**30; a claim made just before must still settle.
    from primitives import TICKS_PERIOD
    arb = ar.Arbiter()
    t0 = TICKS_PERIOD - 300
    _run(arb, t0 - 3000, t0)
    arb.claim(t0)
    arb.verdict(t0, True)
    out, t = [], t0
    while t < t0 + 700:
        out += arb.update(int(t) % TICKS_PERIOD, (0.3, -0.2, 1000.0), 0.2)
        t += DT
    assert out == [(ar.COMMIT, t0, None)]
