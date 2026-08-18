#!/usr/bin/env python3
"""
scripts/train_tap_classifier.py
Host-side only, exploratory. Reads scripts/prepare_tap_dataset.py's CSV
output and checks whether a lightweight trained classifier actually beats
the simple hand-tuned baselines already in use (a single peak-magnitude
threshold for position; the hysteresis peak-counter for tap count).

NOT wired into the shipped pipeline — this answers "is a classifier worth
the complexity for THIS bottle's data," it doesn't produce anything main.py
consumes. See docs/insights.md §8 for the reasoning this follows from:
ML doesn't out-generalize hardcoded thresholds unless the FEATURES are
better, so this evaluates the engineered features (spacing regularity,
energy, etc.) from prepare_tap_dataset.py, not raw detected_taps.

Needs scikit-learn (optional, analysis-only — deliberately not in
requirements.txt / `make setup`, since nothing else in this repo needs it):
    pip install scikit-learn

Usage:
    python3 scripts/train_tap_classifier.py data/tap_dataset.csv --target position
    python3 scripts/train_tap_classifier.py data/tap_dataset.csv --target taps
    python3 scripts/train_tap_classifier.py data/tap_dataset.csv --target position --bottle muji
"""

import csv
import sys
from pathlib import Path

try:
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.tree import DecisionTreeClassifier
except ImportError:
    sys.exit("Missing dependency: pip install scikit-learn")

FEATURE_COLUMNS = [
    "peak_deviation_mg",
    "ring_down_ms",
    "energy",
    "duration_ms",
    "num_crossings",
    "spacing_mean_ms",
    "spacing_stdev_ms",
]
# dominant_axis is categorical (x/y/z) — one-hot encoded separately below.

MODELS = {
    "decision_tree": lambda: DecisionTreeClassifier(max_depth=4, random_state=0),
    "random_forest": lambda: RandomForestClassifier(n_estimators=100, max_depth=6, random_state=0),
}


def load_rows(path, bottle_filter=None):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if bottle_filter:
        rows = [r for r in rows if r["bottle"] == bottle_filter]
    return rows


def build_xy(rows, target):
    axes = sorted({r["dominant_axis"] for r in rows})
    X, y = [], []
    for r in rows:
        feats = [float(r[c]) if r[c] != "" else 0.0 for c in FEATURE_COLUMNS]
        feats += [1.0 if r["dominant_axis"] == ax else 0.0 for ax in axes]
        X.append(feats)
        y.append(r[target])
    return np.array(X), np.array(y)


def majority_baseline(y):
    values, counts = np.unique(y, return_counts=True)
    return counts.max() / len(y)


def peak_threshold_baseline(rows, target):
    """Only meaningful for target=='position': the same best-pairwise-
    threshold-on-peak-magnitude approach used ad hoc earlier in this
    project, as a sanity-check baseline a classifier should beat by more
    than noise to be worth the added complexity."""
    if target != "position":
        return None
    positions = sorted({r["position"] for r in rows})
    if len(positions) != 2:
        return None  # only a clean binary comparison for now
    a, b = positions
    va = sorted(float(r["peak_deviation_mg"]) for r in rows if r["position"] == a)
    vb = sorted(float(r["peak_deviation_mg"]) for r in rows if r["position"] == b)
    all_vals = sorted(set(va + vb))
    best = 0.0
    for i in range(len(all_vals) - 1):
        thr = (all_vals[i] + all_vals[i + 1]) / 2
        acc1 = (sum(1 for v in va if v > thr) + sum(1 for v in vb if v < thr)) / (len(va) + len(vb))
        acc2 = (sum(1 for v in va if v < thr) + sum(1 for v in vb if v > thr)) / (len(va) + len(vb))
        best = max(best, acc1, acc2)
    return best


def cross_bottle_eval(path, target, train_bottle, test_bottle):
    """Train on one bottle entirely, test on another entirely — no pooling,
    no shuffling across bottles. A stricter, more honest generalization
    check than k-fold on pooled data, which can let bottle identity leak
    across folds. Test rows whose true label the training bottle never saw
    (e.g. muji's leftover 3-tap rows, from before that combo was dropped)
    are excluded — scoring against a label the model had zero chance to
    learn measures matrix mismatch, not generalization."""
    train_rows = load_rows(path, train_bottle)
    test_rows = load_rows(path, test_bottle)
    if not train_rows or not test_rows:
        sys.exit(f"No rows for one of {train_bottle!r} / {test_bottle!r} in {path}")

    train_labels = {r[target] for r in train_rows}
    test_rows_filtered = [r for r in test_rows if r[target] in train_labels]
    dropped = len(test_rows) - len(test_rows_filtered)

    Xtr, ytr = build_xy(train_rows, target)
    Xte, yte = build_xy(test_rows_filtered, target)

    print(f"\n== {target} classifier — train={train_bottle} (n={len(train_rows)}), test={test_bottle} (n={len(test_rows_filtered)}", end="")
    if dropped:
        print(f", {dropped} test row(s) dropped — label not in training set", end="")
    print(") ==")
    print(f"  majority-class baseline (test set): {majority_baseline(yte)*100:.1f}%")

    for name, build_model in MODELS.items():
        model = build_model()
        model.fit(Xtr, ytr)
        acc = model.score(Xte, yte)
        print(f"  {name}: {acc*100:.1f}%")
    print()


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(
            "Usage: python3 scripts/train_tap_classifier.py data/tap_dataset.csv --target position|taps [--bottle NAME]\n"
            "       python3 scripts/train_tap_classifier.py data/tap_dataset.csv --target position|taps --train-bottle NAME --test-bottle NAME"
        )

    path = Path(args[0])
    if not path.exists():
        sys.exit(f"File not found: {path}")

    target = "position"
    if "--target" in args:
        i = args.index("--target")
        target = {"position": "position", "taps": "taps_intended"}.get(args[i + 1], args[i + 1])

    if "--train-bottle" in args and "--test-bottle" in args:
        train_bottle = args[args.index("--train-bottle") + 1]
        test_bottle = args[args.index("--test-bottle") + 1]
        cross_bottle_eval(path, target, train_bottle, test_bottle)
        return

    bottle_filter = None
    if "--bottle" in args:
        i = args.index("--bottle")
        bottle_filter = args[i + 1]

    rows = load_rows(path, bottle_filter)
    if len(rows) < 10:
        sys.exit(f"Only {len(rows)} rows — too few to cross-validate meaningfully")

    X, y = build_xy(rows, target)
    class_counts = {str(c): list(y).count(c) for c in sorted(set(y))}
    min_class_n = min(class_counts.values())
    k = max(2, min(5, min_class_n))  # fold count can't exceed the smallest class

    scope = bottle_filter or "all bottles pooled"
    print(f"\n== {target} classifier — {scope} — n={len(rows)}, classes={class_counts}, {k}-fold CV ==")

    print(f"  majority-class baseline: {majority_baseline(y)*100:.1f}%")
    thr_baseline = peak_threshold_baseline(rows, target)
    if thr_baseline is not None:
        print(f"  single-threshold-on-peak-magnitude baseline: {thr_baseline*100:.1f}%")

    cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=0)
    for name, build_model in MODELS.items():
        scores = cross_val_score(build_model(), X, y, cv=cv)
        folds = [round(float(s), 2) for s in scores]
        print(f"  {name}: {scores.mean()*100:.1f}% ± {scores.std()*100:.1f}%  (folds: {folds})")

    # Feature importances from a fresh RF fit on everything — diagnostic
    # only (not a held-out score), just to see which engineered features the
    # model actually leans on.
    axes = sorted({r["dominant_axis"] for r in rows})
    feature_names = FEATURE_COLUMNS + [f"axis_{ax}" for ax in axes]
    rf = MODELS["random_forest"]()
    rf.fit(X, y)
    ranked = sorted(zip(feature_names, rf.feature_importances_), key=lambda t: -t[1])
    print("  feature importances (random_forest, fit on all rows):")
    for name, importance in ranked:
        print(f"    {name}: {importance:.3f}")
    print()


if __name__ == "__main__":
    main()
