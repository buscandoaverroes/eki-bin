"""scripts/replay.py — the Phase 1 replay harness, on synthetic streams.

The harness's value is that its verdicts come from the REAL firmware code; so
these tests check the plumbing around that code — sampling at a loop rate,
the capture window, blindness after a tap, the extra features, and scoring —
on streams whose right answer is known by construction.
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import replay as rp  # noqa: E402

DT = 1000.0 / 234          # the sandbox's real sample spacing, ms
G = 16384                  # 1 g in raw LSB at +/-2 g


@pytest.fixture(scope="module")
def fw():
    return rp.load_firmware({"TAP_TRIGGER_THRESHOLD_MG": 50, "TAP_ENERGY_THRESHOLD": 138000,
                             "TILT_ENABLED": True})


def still(t0, t1, ax=0, ay=0, az=G):
    out, t = [], t0
    while t < t1:
        out.append(rp.Sample(t, ax, ay, az, 0, 0, 0))
        t += DT
    return out


def with_impulse(samples, t, dx=0, dz=0, n=3):
    """Add a short impulse starting at the first sample at/after t."""
    k = next(i for i, s in enumerate(samples) if s.t >= t)
    for i in range(k, k + n):
        samples[i].ax += dx
        samples[i].az += dz
    return samples


def label(name, t_ms):
    return {"k": "l", "label": name, "tm": t_ms, "h": t_ms / 1000}


def test_a_lateral_tap_is_triggered_accepted_and_scored_as_a_hit(fw):
    s = with_impulse(still(0, 5000), 2000, dx=6000)
    ev = rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0)
    taps = [e for e in ev if e["e"] == "tap"]
    assert len(taps) == 1 and taps[0]["valid"]
    assert taps[0]["feats"]["z_share"] < 0.2
    sc = rp.score(ev, [label("tap_body", 2400)], [])
    assert (sc["hit"], sc["miss"]) == (1, 0)


def test_a_vertical_knock_is_accepted_today_but_the_z_veto_rejects_it(fw):
    s = with_impulse(still(0, 5000), 2000, dz=3000)
    cands = rp.candidate_rules()
    ev = rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0, candidates=cands)
    tap = [e for e in ev if e["e"] == "tap"][0]
    assert tap["valid"] and tap["feats"]["z_share"] > 0.8
    labs = [label("knock_table", 2400)]
    assert rp.score(ev, labs, [])["false"] == {"knock_table": 1}
    z = rp.score(ev, labs, [], accept=lambda e: e["valid"] and e["cand"]["z_veto"])
    assert z["false"] == {}


def test_a_tap_inside_the_previous_taps_busy_window_is_missed_as_blind(fw):
    s = still(0, 8000)
    with_impulse(s, 2000, dx=6000)
    with_impulse(s, 3000, dx=6000)            # 1 s later: still capturing/responding
    ev = rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0)
    sc = rp.score(ev, [label("tap_body", 2300), label("tap_body", 3300)], [])
    assert sc["hit"] == 1 and sc["miss_why"] == {"blind": 1}


def test_the_loop_reads_only_every_nth_sample(fw):
    s = still(0, 10_000)
    seen = []
    orig = fw.gestures._gesture_magnitude_mg
    fw.gestures._gesture_magnitude_mg = lambda smp: (seen.append(smp[0]), orig(smp))[1]
    try:
        rp.replay(fw, s, loop_hz=57)
    finally:
        fw.gestures._gesture_magnitude_mg = orig
    assert 56 * 10 <= len(seen) <= 58 * 10       # ~57 reads a second, not 234 (nor 47)


def test_a_held_tilt_engages_the_real_tilt_controller(fw):
    s = still(0, 3000)
    t = 3000.0
    while t < 10_000:                           # ramp to 25 deg over 2 s, then hold
        deg = min(25.0, (t - 3000) / 2000 * 25.0)
        r = math.radians(deg)
        s.append(rp.Sample(t, int(G * math.sin(r)), 0, int(G * math.cos(r)), 0, 0, 0))
        t += DT
    ev = rp.replay(fw, s, loop_hz=57)
    assert any(e["e"] == "tilt" and e["engaged"] for e in ev)
    sc = rp.score(ev, [], [("tilting", 4000.0, 10_000.0), ("rest_flat", 0.0, 3000.0)])
    flat, tilting = sc["segments"][1], sc["segments"][0]
    assert flat["engaged_s"] == 0.0 and tilting["engaged_s"] > 3.0


def test_gyro_bias_is_removed_before_measuring_late_rotation(fw):
    s = still(0, 5000)
    for smp in s:
        smp.gx, smp.gz = -62, 40                # a constant zero-rate offset, no rotation
    with_impulse(s, 2000, dx=6000)
    tap = [e for e in rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0) if e["e"] == "tap"][0]
    assert tap["feats"]["gyro_late_dps"] < 0.05


def test_one_tap_cannot_answer_two_labels(fw):
    s = with_impulse(still(0, 6000), 2000, dx=6000)
    ev = rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0)
    sc = rp.score(ev, [label("tap_body", 2300), label("tap_body", 3800)], [])
    assert (sc["hit"], sc["miss"]) == (1, 1)


def test_ideal_mode_judges_every_impulse_even_back_to_back(fw):
    s = still(0, 8000)
    with_impulse(s, 2000, dx=6000)
    with_impulse(s, 3000, dx=6000)
    ev = rp.replay(fw, s, loop_hz=240, gyro_mdps=35.0, ideal=True)
    sc = rp.score(ev, [label("tap_body", 2300), label("tap_body", 3300)], [])
    assert sc["hit"] == 2
