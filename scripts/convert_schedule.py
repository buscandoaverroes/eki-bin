#!/usr/bin/env python3
"""
scripts/convert_schedule.py
Host-side only. Converts human-readable YAML schedule → minutes-since-midnight arrays.

Usage:
    python3 scripts/convert_schedule.py schedules/mystation.yaml

Outputs:
    schedules/mystation.json  ← consumed by main.py (uploaded as schedule.json);
                                shared format; Rust build.rs can consume it too

Post-midnight convention: use extended hours, exactly as Japanese timetables print them.
    "24:30" → 1470 min  (00:30 AM, treated as continuation of the previous service day)
    "25:10" → 1510 min  (01:10 AM)
This means arrays are always sorted ascending and the firmware logic stays simple:
    find first entry > current_minutes.
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml   (or: make setup)")


def hhmm_to_minutes(t: str) -> int:
    """
    Convert "HH:MM" to minutes since midnight.
    Handles extended hours: "24:30" → 1470, "25:10" → 1510.
    Raises ValueError on bad format.
    """
    parts = t.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Bad time format: {t!r} — expected HH:MM")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 29 and 0 <= m <= 59):
        raise ValueError(f"Out-of-range time: {t!r}")
    return h * 60 + m


def convert_direction(times: list[str], label: str) -> list[int]:
    minutes = []
    for t in times:
        try:
            minutes.append(hhmm_to_minutes(t))
        except ValueError as e:
            sys.exit(f"Error in {label}: {e}")
    if minutes != sorted(minutes):
        sys.exit(
            f"Error in {label}: times must be in ascending order (check post-midnight entries use 24:xx / 25:xx)"
        )
    return minutes


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 scripts/convert_schedule.py schedules/<station>.yaml")

    source_path = Path(sys.argv[1])
    if not source_path.exists():
        sys.exit(f"File not found: {source_path}")

    with open(source_path) as f:
        data = yaml.safe_load(f)

    station = data.get("station", source_path.stem)
    schedule = {}

    for period in ("weekday", "weekend"):
        if period not in data:
            continue
        schedule[period] = {}
        for direction, times in data[period].items():
            label = f"{period}.{direction}"
            schedule[period][direction] = convert_direction(times, label)

    # ── Output: schedules/<station>.json ─────────────────────────────────────
    # main.py reads this (uploaded to the device as schedule.json); Rust build.rs
    # can consume the same file at compile time.
    json_path = source_path.with_suffix(".json")
    with open(json_path, "w") as f:
        json.dump({"station": station, **schedule}, f, indent=2)

    print(f"✓ {json_path}")

    # ── Summary ──────────────────────────────────────────────────────────────
    for period, directions in schedule.items():
        for direction, minutes in directions.items():
            print(
                f"   {period}.{direction}: {len(minutes)} departures  "
                f"({minutes[0] // 60:02d}:{minutes[0] % 60:02d} → "
                f"{minutes[-1] // 60:02d}:{minutes[-1] % 60:02d})"
            )


if __name__ == "__main__":
    main()
