#!/usr/bin/env python3
"""
scripts/prepare_tap_dataset.py
Host-side only. Converts vibration_*.jsonl (or legacy .json) session files
into one flat CSV of engineered per-capture features + labels — data prep
for a classifier, not the classifier itself.

Usage:
    python3 scripts/prepare_tap_dataset.py data/vibration_*.jsonl
    python3 scripts/prepare_tap_dataset.py data/vibration_*.jsonl -o data/tap_dataset.csv

Why this is a separate script from analyze_taps.py, not an extra column on
it: analyze_taps.py's "detected_taps" / "peak_magnitudes_mg" are the OUTPUT
of our own hand-tuned hysteresis peak-counter. Training a classifier on that
would just have it learn to imitate that algorithm's mistakes (rocking
included). Every feature below is computed straight from the raw per-sample
x/y/z instead, so a classifier gets a genuinely independent look at the
signal — including a spacing-regularity feature aimed at telling a real
multi-tap apart from one tap plus rocking echo (see docs/insights.md §8):
mechanical rocking is roughly periodic (low spacing variance), deliberate
human taps are looser (higher variance).

Deliberately stdlib-only — this produces the CSV; an actual scikit-learn
spike is a separate follow-up step once there's enough rows to bother with,
not something to wire in speculatively before that data exists.
"""

import csv
import math
import statistics
import sys
from pathlib import Path

from analyze_taps import MG_PER_LSB_AT_2G, _dominant_axis, load_session

# Lower/more sensitive than analyze_taps.py's PEAK_THRESHOLD_FRAC (0.5) —
# this script wants to see *every* excursion (including rocking echoes), not
# just ones big enough to plausibly be a deliberate tap. That's the point:
# the regularity of ALL crossings, not just the "real" ones, is the feature.
CROSSING_THRESHOLD_FRAC = 0.3
SETTLE_FRAC = 0.1

FIELDNAMES = [
    "bottle",
    "fastening",
    "position",
    "taps_intended",
    "peak_deviation_mg",
    "ring_down_ms",
    "energy",
    "duration_ms",
    "dominant_axis",
    "num_crossings",
    "spacing_mean_ms",
    "spacing_stdev_ms",
]


def _magnitude_mg(sample):
    return math.sqrt(sample["x"] ** 2 + sample["y"] ** 2 + sample["z"] ** 2) * MG_PER_LSB_AT_2G


def engineer_features(capture):
    samples = capture["samples"]
    mags = [_magnitude_mg(s) for s in samples]
    baseline = statistics.median(mags)
    deviations = [m - baseline for m in mags]

    peak_dev = max(deviations)
    peak_idx = deviations.index(peak_dev)
    peak_t = samples[peak_idx]["t_ms"]
    duration_ms = samples[-1]["t_ms"]

    # Total excursion energy over the whole capture — a proxy for "how much
    # total motion happened." Rocking (several oscillations) should read
    # higher than one clean tap even at similar peak amplitude.
    energy = sum(d * d for d in deviations if d > 0)

    ring_down_ms = None
    settle_dev = SETTLE_FRAC * peak_dev
    for s, dev in zip(samples[peak_idx:], deviations[peak_idx:]):
        if dev < settle_dev:
            ring_down_ms = s["t_ms"] - peak_t
            break

    # Sensitive threshold-crossing count + spacing regularity — see module
    # docstring. Not the same algorithm as analyze_taps.py's tap counter on
    # purpose: this one is meant to see everything, not just "real" taps.
    # peak_dev <= 0 means a perfectly flat capture (never happens with real
    # sensor noise, but guard it anyway — a threshold of 0 would otherwise
    # register every sample as "above" it).
    threshold = CROSSING_THRESHOLD_FRAC * peak_dev
    crossing_times = []
    above = False
    if peak_dev > 0:
        for sample, dev in zip(samples, deviations):
            if not above and dev >= threshold:
                above = True
                crossing_times.append(sample["t_ms"])
            elif above and dev < threshold:
                above = False
    gaps = [b - a for a, b in zip(crossing_times, crossing_times[1:])]

    return {
        "peak_deviation_mg": round(peak_dev, 1),
        "ring_down_ms": ring_down_ms,
        "energy": round(energy, 1),
        "duration_ms": duration_ms,
        "dominant_axis": _dominant_axis(samples[peak_idx]),
        "num_crossings": len(crossing_times),
        "spacing_mean_ms": round(statistics.mean(gaps), 1) if gaps else "",
        "spacing_stdev_ms": round(statistics.stdev(gaps), 1) if len(gaps) > 1 else "",
    }


def main():
    args = sys.argv[1:]
    output = "data/tap_dataset.csv"
    if "-o" in args:
        i = args.index("-o")
        if i + 1 >= len(args):
            sys.exit("Usage: python3 scripts/prepare_tap_dataset.py data/vibration_*.jsonl [-o output.csv]")
        output = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if not args:
        sys.exit("Usage: python3 scripts/prepare_tap_dataset.py data/vibration_*.jsonl [-o output.csv]")

    rows = []
    for path_str in args:
        path = Path(path_str)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        bottle, fastening, captures = load_session(path)
        for c in captures:
            row = {
                "bottle": bottle,
                "fastening": fastening,
                "position": c["position"],
                "taps_intended": c["taps_intended"],
            }
            row.update(engineer_features(c))
            rows.append(row)

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ {len(rows)} rows → {out_path}")


if __name__ == "__main__":
    main()
