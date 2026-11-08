#!/usr/bin/env python3
"""
scripts/analyze_taps.py
Host-side only. Reads one or more vibration_*.jsonl (or legacy .json) files
produced by micropython/vibration_sandbox.py and reports whether tap
position (neck/body) and tap count (1/2/3) look separable by simple
thresholds.

Current format is JSON Lines (.jsonl) — one JSON object per line, streamed
to flash by the device rep-by-rep rather than built up as one big structure
in RAM (see vibration_sandbox.py's main() for why that changed: it was
MemoryError-ing on real hardware at 240Hz). The single-JSON-blob .json
format from before that change is still readable here, so earlier sessions
don't need re-collecting.

Usage:
    python3 scripts/analyze_taps.py data/vibration_mystation_blue_tack.jsonl
    python3 scripts/analyze_taps.py data/vibration_*.jsonl   # multiple sessions
    python3 scripts/analyze_taps.py --verbose data/vibration_*.jsonl  # + raw peak mg per rep

v1 scope, deliberately: plain time-domain features (peak magnitude,
ring-down duration, dominant axis, tap-peak count/spacing) and a threshold
separability check — no ML dependency. If a feature doesn't cleanly separate
groups, this script says so rather than forcing a cutoff; the JSON format
carries everything a classifier would need too (raw per-sample x/y/z), so
moving to scikit-learn later doesn't require re-collecting data.
"""

import json
import math
import statistics
import sys
from pathlib import Path

# Centralized here on purpose — vibration_sandbox.py stores raw int16 LSB
# counts and leaves unit conversion to this script. Same constant/caveat as
# imu_test.py: power-on-default full-scale (±2g), not independently calibrated.
MG_PER_LSB_AT_2G = 0.061

PEAK_THRESHOLD_FRAC = 0.5  # secondary peaks must clear this fraction of the primary peak
MIN_PEAK_GAP_MS = 60  # debounce — real taps aren't closer together than this
SETTLE_FRAC = 0.1  # ring-down "done" once deviation drops below this fraction of peak


def _magnitude_mg(sample):
    return math.sqrt(sample["x"] ** 2 + sample["y"] ** 2 + sample["z"] ** 2) * MG_PER_LSB_AT_2G


def _dominant_axis(sample):
    return max(("x", "y", "z"), key=lambda ax: abs(sample[ax]))


def _count_peaks(samples, deviations, peak_dev):
    """Threshold-crossing with hysteresis: count a tap when deviation rises
    above threshold, then don't arm again until it drops back below —
    instead of a pure local-maxima scan. Real data exposed why local-maxima
    doesn't work here: a single tap's ring-down oscillation dips and re-rises
    before fully settling, so it was getting counted as two taps 62-78ms
    apart (well inside the observed ring-down duration). MIN_PEAK_GAP_MS is
    a second guard against any remaining ultra-fast re-crossing.

    PEAK_THRESHOLD_FRAC is relative to this capture's own single largest
    peak, which has a known failure mode too: if an earlier tap in a
    multi-tap rep lands harder than a later one, the softer one can fall
    below the threshold and go undetected. Left as-is for now — distinguishing
    "threshold too strict" from "genuinely weak signal" (esp. at the neck,
    where peaks run single-digit mg) needs more data than one session's
    worth. Use --verbose to inspect raw peak magnitudes when tuning this."""
    threshold = PEAK_THRESHOLD_FRAC * peak_dev
    peak_times = []
    peak_mags = []
    above = False
    last_peak_t = -MIN_PEAK_GAP_MS * 10
    for sample, dev in zip(samples, deviations):
        t = sample["t_ms"]
        if not above and dev >= threshold:
            above = True
            if t - last_peak_t >= MIN_PEAK_GAP_MS:
                peak_times.append(t)
                peak_mags.append(dev)
                last_peak_t = t
        elif above and dev < threshold:
            above = False
    inter_tap_ms = [b - a for a, b in zip(peak_times, peak_times[1:])]
    return len(peak_times), inter_tap_ms, peak_mags


def extract_features(capture):
    samples = capture["samples"]
    mags = [_magnitude_mg(s) for s in samples]
    baseline = statistics.median(mags)
    deviations = [m - baseline for m in mags]

    peak_dev = max(deviations)
    peak_idx = deviations.index(peak_dev)
    peak_t = samples[peak_idx]["t_ms"]

    ring_down_ms = None
    settle_dev = SETTLE_FRAC * peak_dev
    for s, dev in zip(samples[peak_idx:], deviations[peak_idx:]):
        if dev < settle_dev:
            ring_down_ms = s["t_ms"] - peak_t
            break

    detected_taps, inter_tap_ms, peak_mags = _count_peaks(samples, deviations, peak_dev)

    return {
        "peak_deviation_mg": peak_dev,
        "ring_down_ms": ring_down_ms,
        "dominant_axis": _dominant_axis(samples[peak_idx]),
        "detected_taps": detected_taps,
        "inter_tap_ms": inter_tap_ms,
        "peak_magnitudes_mg": peak_mags,
    }


def summarize_group(label, values):
    if not values:
        print(f"    {label}: no data")
        return
    line = f"    {label}: n={len(values)}  min={min(values):.0f}  max={max(values):.0f}  mean={statistics.mean(values):.0f}"
    if len(values) > 1:
        line += f"  stdev={statistics.stdev(values):.0f}"
    print(line)


def check_separability(label_a, values_a, label_b, values_b):
    if not values_a or not values_b:
        print("    (need at least one capture per group to check separability)")
        return
    a_min, a_max = min(values_a), max(values_a)
    b_min, b_max = min(values_b), max(values_b)
    if a_max < b_min:
        print(f"    ✓ clean separation — {label_a} < {(a_max + b_min) / 2:.0f} < {label_b}")
    elif b_max < a_min:
        print(f"    ✓ clean separation — {label_b} < {(b_max + a_min) / 2:.0f} < {label_a}")
    else:
        print(
            f"    ✗ overlapping ranges — {label_a}=[{a_min:.0f},{a_max:.0f}]  "
            f"{label_b}=[{b_min:.0f},{b_max:.0f}]. Not a clean single threshold; "
            "consider a second feature (ring_down_ms) or a lightweight classifier."
        )


def load_session(path):
    """Reads the current streaming .jsonl format (one JSON object per line:
    a header, then one per rep with compact [t,x,y,z] samples) and falls
    back to the legacy single-JSON-blob format (one document, dict-keyed
    samples) so older sessions stay readable without re-collecting."""
    text = path.read_text()
    try:
        payload = json.loads(text)
        return payload["bottle"], payload["fastening"], payload["captures"]
    except json.JSONDecodeError:
        pass  # not one JSON document — try line-delimited (current format)

    lines = [line for line in text.splitlines() if line.strip()]
    header = json.loads(lines[0])
    captures = []
    for line in lines[1:]:
        record = json.loads(line)
        record["samples"] = [
            {"t_ms": t, "x": x, "y": y, "z": z} for t, x, y, z in record["samples"]
        ]
        captures.append(record)
    return header["bottle"], header["fastening"], captures


def analyze_file(path, verbose=False):
    bottle, fastening, captures = load_session(path)
    print(f"\n══ {path.name}: {bottle!r} / {fastening!r} — {len(captures)} rep(s) ══")

    for c in captures:
        c["_features"] = extract_features(c)

    print("\n  position (peak magnitude, mg):")
    by_position = {}
    for c in captures:
        by_position.setdefault(c["position"], []).append(c["_features"]["peak_deviation_mg"])
    for pos, values in by_position.items():
        summarize_group(pos, values)
    if len(by_position) == 2:
        (label_a, values_a), (label_b, values_b) = list(by_position.items())
        check_separability(label_a, values_a, label_b, values_b)

    print("\n  ring-down duration (ms) — secondary position feature:")
    by_position_ring = {}
    for c in captures:
        if c["_features"]["ring_down_ms"] is not None:
            by_position_ring.setdefault(c["position"], []).append(c["_features"]["ring_down_ms"])
    for pos, values in by_position_ring.items():
        summarize_group(pos, values)

    print("\n  tap count (detected vs intended):")
    by_taps = {}
    for c in captures:
        by_taps.setdefault(c["taps_intended"], []).append(c)
    for n, group in sorted(by_taps.items()):
        correct = sum(1 for c in group if c["_features"]["detected_taps"] == n)
        print(f"    {n}-tap: {correct}/{len(group)} detected correctly")
        gaps = [gap for c in group for gap in c["_features"]["inter_tap_ms"]]
        if gaps:
            print(
                f"      inter-tap spacing: min={min(gaps)}ms  max={max(gaps)}ms  mean={statistics.mean(gaps):.0f}ms"
            )
        if verbose:
            for c in group:
                f = c["_features"]
                mark = "✓" if f["detected_taps"] == n else "✗"
                mags = ", ".join(f"{m:.0f}" for m in f["peak_magnitudes_mg"])
                print(f"      {mark} {c['position']}: detected={f['detected_taps']}  peaks=[{mags}]mg")


def main():
    args = sys.argv[1:]
    verbose = "--verbose" in args
    paths = [a for a in args if a != "--verbose"]
    if not paths:
        sys.exit("Usage: python3 scripts/analyze_taps.py [--verbose] data/vibration_*.json")

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        analyze_file(path, verbose=verbose)

    print()


if __name__ == "__main__":
    main()
