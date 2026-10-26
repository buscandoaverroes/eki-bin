"""scripts/sim.py — the IMU pipeline with swappable blocks, on synthetic streams.

The one property that makes the simulator worth anything: with the shipped
blocks plugged in it IS replay.replay(), event for event. Every later
comparison ("the vector trigger catches 29/30") rests on that, so it is
tested first. Then the vector trigger's reason to exist, the streaming
edge cases, and per-trial scoring.
"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import replay as rp  # noqa: E402
import sim  # noqa: E402

DT = 1000.0 / 240
G = 16384


def stream(seconds, pulses=(), gyro_dps=0.0):
    """A still, upright bottle with short accel pulses: [(t_ms, (dx, dy, dz) LSB, ms)]."""
    out, t = [], 0.0
    gl = int(gyro_dps * 1000 / 35.0)
    while t < seconds * 1000:
        ax, ay, az = 0, 0, G
        for t0, (dx, dy, dz), dur in pulses:
            if t0 <= t < t0 + dur:
                ax, ay, az = ax + dx, ay + dy, az + dz
        out.append(rp.Sample(t, ax, ay, az, gl, 0, 0))
        t += DT
    return out


def sideways(mg):
    return (int(mg / 0.061), 0, 0)


def down(mg):
    return (0, 0, int(mg / 0.061))


@pytest.fixture
def fw():
    return rp.load_firmware()


# ── the guarantee ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("hz,ideal", [(240, False), (145, False), (57, False), (240, True)])
def test_shipped_blocks_reproduce_replay_exactly(hz, ideal):
    pulses = [(2000 + 1700 * k, down(150 + 40 * k), 12) for k in range(8)]
    samples = stream(16, pulses, gyro_dps=0.3)
    key = lambda e: (e["t"], e["e"], e.get("valid"), str(e.get("feats")), e.get("engaged"))  # noqa: E731
    want = sorted(key(e) for e in rp.replay(rp.load_firmware(), samples, hz, gyro_mdps=35.0, ideal=ideal)
                  if e["e"] in ("tap", "tilt"))
    got = sorted(key(e) for e in sim.Pipeline(rp.load_firmware(), hz, gyro_mdps=35.0, ideal=ideal).run(samples)
                 if e["e"] in ("tap", "tilt"))
    assert want and got == want


def test_a_capture_still_filling_at_the_end_is_judged_on_what_there_is(fw):
    samples = stream(2.5, [(2300, down(200), 12)])
    taps = [e for e in sim.Pipeline(fw, 240).run(samples) if e["e"] == "tap"]
    assert len(taps) == 1 and taps[0]["t"] >= 2300


def test_the_gyro_baseline_is_frozen_at_the_trigger_not_shared():
    # estimate() returns GyroBias's own list; a held reference would keep
    # learning while the window fills. Overlapping captures (ideal) expose it.
    fw = rp.load_firmware()
    bias = fw.gestures.GyroBias(mdps=35.0)
    arb = sim.CaptureArbiter(fw, sim.AcceptClassifier(fw), gyro_mdps=35.0)
    for _ in range(2000):
        bias.update((10, 0, 0), DT)
    arb.trigger(0.0, 0, 60.0, bias)
    snap = list(arb.pending[0][3].estimate())
    for _ in range(2000):
        bias.update((60, 0, 0), DT)
    assert arb.pending[0][3].estimate() == snap


# ── why the vector trigger exists ─────────────────────────────────────────
def test_a_sideways_tap_moves_the_vector_but_barely_lengthens_it(fw):
    samples = stream(4, [(2000, sideways(200), 12)])
    trig = lambda name: [e for e in sim.Pipeline(rp.load_firmware(), 240, name).run(samples)  # noqa: E731
                         if e["e"] == "trigger"]
    assert trig("magnitude") == []              # √(1000² + 200²) − 1000 = 20 mg < 50
    assert len(trig("vector")) == 1


def test_both_triggers_agree_on_a_push_along_gravity(fw):
    samples = stream(4, [(2000, down(200), 12)])
    for name in ("magnitude", "vector"):
        trig = [e for e in sim.Pipeline(rp.load_firmware(), 240, name).run(samples) if e["e"] == "trigger"]
        assert len(trig) == 1 and trig[0]["dev"] == pytest.approx(200, abs=5)


def test_a_slow_tilt_does_not_fire_the_vector_trigger(fw):
    # 40° over 2 s: the buffer's median moves with it (~0.7° per 33 ms).
    import math
    out, t = [], 0.0
    while t < 5000:
        a = math.radians(min(40.0, max(0.0, (t - 1000) / 2000 * 40)))
        out.append(rp.Sample(t, int(G * math.sin(a)), 0, int(G * math.cos(a)), 0, 0, 0))
        t += DT
    assert [e for e in sim.Pipeline(fw, 240, "vector").run(out) if e["e"] == "trigger"] == []


def test_accept_classifier_scores_detect_alone(fw):
    samples = stream(4, [(2000, down(300), 60)])          # a long shove: firmware may reject
    taps = [e for e in sim.Pipeline(fw, 240, classify="accept").run(samples) if e["e"] == "tap"]
    assert taps and all(e["valid"] for e in taps)


# ── the loop ──────────────────────────────────────────────────────────────
def test_the_loop_keeps_the_ideal_schedule():
    loop = sim.Loop(57)
    seen = sum(loop.sees(k * DT) for k in range(2400))      # 10 s of 240 Hz
    assert 565 <= seen <= 575


# ── live ──────────────────────────────────────────────────────────────────
def test_follow_waits_for_the_newline(tmp_path):
    path = tmp_path / "rec.jsonl"
    path.write_text('{"k": "h"}\n{"k": "b", "t0"')
    done = []

    def finish():
        time.sleep(0.15)
        with open(path, "a") as f:
            f.write(': 0, "d": []}\n{"k": "t"}\n')

    threading.Thread(target=finish).start()
    gen = sim.follow(path, poll_s=0.01, stop=lambda: len(done) >= 3)
    for rec in gen:
        done.append(rec["k"])
        if len(done) >= 3:
            break
    assert done == ["h", "b", "t"]


def test_samples_of_a_batch_are_device_ms_in_sample_order():
    rec = {"k": "b", "t0": 1_000_000, "d": [[0, 1, 2, 3, 4, 5, 6, 3], [4166, 7, 8, 9, 10, 11, 12, 3]]}
    s = sim.samples_of(rec)
    assert [x.t for x in s] == [1000.0, 1004.166]
    assert (s[1].gx, s[1].gy, s[1].gz, s[1].ax, s[1].ay, s[1].az) == (7, 8, 9, 10, 11, 12)


# ── per-trial scoring ─────────────────────────────────────────────────────
def _recs(*trials):
    """A guided recording's records: one batch fixes device time = host time."""
    recs = [{"k": "b", "h": 0.0, "t0": 0, "d": [[0, 0, 0, 0, 0, 0, G, 3]]}]
    for n, kind, go, done in trials:
        recs.append({"k": "l", "h": go, "trial": n, "attempt": 1, "type": kind, "edge": "go"})
        recs.append({"k": "l", "h": done, "trial": n, "attempt": 1, "edge": "done", "status": "ok"})
    return recs


def _tap(t_s, valid, why=None):
    return {"e": "tap", "t": t_s * 1000.0, "valid": valid, "why": why}


def test_score_trials_counts_each_kind_of_trial_its_own_way():
    recs = _recs((1, "T", 10, 12), (2, "G", 20, 24), (3, "D", 30, 36), (4, "T", 40, 42))
    events = [{"e": "trigger", "t": 10_800.0}, _tap(10.8, True),     # tap kept
              _tap(21.0, True), _tap(22.0, True),                    # two false taps, one trial
              _tap(31.0, True), _tap(33.0, True),                    # D: the tap, then a false one
              {"e": "trigger", "t": 40_900.0}, _tap(40.9, False, "gyro"),   # tap rejected
              _tap(50.0, True)]                                      # hands-off countdown
    sc = sim.score_trials(events, recs)
    assert sc["T"] == [1, 2] and sc["T_trig"] == 2
    assert sc["GH"] == [1, 1] and sc["GH_false"] == 2
    assert sc["D"] == [1, 1] and sc["D_false_after"] == 1
    assert sc["rest_false"] == 1 and sc["why"] == {"T:gyro": 1}


def test_redone_attempts_claim_their_events_but_are_not_scored():
    recs = _recs((1, "T", 10, 12))
    recs.append({"k": "l", "h": 13.0, "trial": 1, "attempt": 1, "edge": "verdict", "status": "redo"})
    sc = sim.score_trials([_tap(10.8, True)], recs)
    assert sc["T"] == [0, 0] and sc["rest_false"] == 0     # inside a (redone) attempt, not a countdown


def test_main_runs_end_to_end_on_a_guided_file(tmp_path, capsys):
    samples = stream(20, [(4500, sideways(200), 12)])
    recs = [{"k": "h", "h": 0.0, "kind": "imu_stream", "protocol": "tap-vs-grab"},
            {"k": "m", "t": 0, "CTRL6": 3}]
    for i in range(0, len(samples), 20):
        chunk = samples[i:i + 20]
        t0 = int(chunk[0].t * 1000)
        recs.append({"k": "b", "h": chunk[-1].t / 1000.0, "t0": t0,
                     "d": [[int(s.t * 1000) - t0, 0, 0, 0, s.ax, s.ay, s.az, 3] for s in chunk]})
    recs += [{"k": "l", "h": 4.0, "id": 1, "trial": 1, "attempt": 1, "type": "T", "where": "body", "edge": "go"},
             {"k": "l", "h": 6.0, "id": 2, "trial": 1, "attempt": 1, "edge": "done", "status": "ok"}]
    path = tmp_path / "imu-test-guided.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    sim.main([str(path), "--detect", "magnitude,vector"])
    out = capsys.readouterr().out
    assert "magnitude · capture · firmware     taps  0/1 (triggered  0/1)" in out
    assert "vector · capture · firmware        taps  1/1 (triggered  1/1)" in out


# ── the settle arbiter, inside the pipeline ───────────────────────────────
def _tremor(samples, t_from, mg, seed=3):
    """Add a hand's tremor (per-axis gaussian, mg) from t_from on."""
    import random
    rnd = random.Random(seed)
    k = 1 / 0.061
    return [rp.Sample(s.t, s.ax + int(rnd.gauss(0, mg) * k), s.ay + int(rnd.gauss(0, mg) * k),
                      s.az + int(rnd.gauss(0, mg) * k), s.gx, s.gy, s.gz) if s.t >= t_from else s
            for s in samples]


def _taps(samples, arbiter):
    return [e for e in sim.Pipeline(rp.load_firmware(), 240, "vector", arbiter, gyro_mdps=35.0).run(samples)
            if e["e"] == "tap"]


def test_settle_commits_a_tap_on_a_bottle_left_alone():
    samples = stream(10, [(8000, sideways(200), 12)], gyro_dps=0.2)
    taps = _taps(samples, "settle")
    assert [(e["valid"], e["why"]) for e in taps] == [(True, None)]
    assert taps[0]["decided"] - taps[0]["t"] >= 1200       # after classify's capture, not before


def test_settle_vetoes_the_same_tap_with_a_hand_on_the_bottle():
    samples = _tremor(stream(10, [(8000, sideways(200), 12)], gyro_dps=0.2), 7000, 2.5)
    assert [(e["valid"], e["why"]) for e in _taps(samples, "capture")] == [(True, None)]
    assert [(e["valid"], e["why"]) for e in _taps(samples, "settle")] == [(False, "not still")]
