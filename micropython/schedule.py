# micropython/schedule.py — eki-bin
# Reading schedule.json and answering questions about it. Extracted from
# main.py by the V1.6 split (docs/v1.6-refactor.md).
#
# Schema + the YAML → JSON pipeline: docs/contracts/schedule-json.md.
#
# schedule_lines() is the compatibility seam for multi-line stations: a file
# with `lines` returns it directly, a file without one IS a single line. That
# older shape is NOT deprecated, and normalizing here rather than at every
# use site is what keeps every pre-existing schedule working untouched.
#
# Note next_departures() is NOT here — it lives in signals.py, because
# leave_signal() calls it and it is really the first half of stage 1
# (timetable → minutes-until → LeaveSignal).

import json

from settings import *  # noqa: F401,F403

def is_quiet(now):
    """True during the configured quiet hours. The window can wrap past midnight
    (e.g. 23:00 → 06:00), so we test the gap with OR, not a simple range."""
    return now >= QUIET_START or now < QUIET_END




# ─────────────────────────────────────────────────────────────
# Schedule loading
# [→ Rust] build.rs reads schedule.json at compile time and emits
#          const arrays — zero runtime parsing cost on device.
# ─────────────────────────────────────────────────────────────
def load_schedule(filename):
    """
    Load schedule.json from device filesystem.
    Returns the full parsed dict (station, weekday, weekend).
    Raises (OSError: missing file; ValueError: malformed JSON) rather than
    halting itself — the caller decides what "failed to load" looks like on
    the LEDs (see main()'s call site and
    docs/contracts/led-status-messages.md's schedule-load-failure entry).
    """
    try:
        with open(filename) as f:
            return json.load(f)
    except OSError:
        print(f"✗ Schedule file not found: {filename}")
        print("  Upload it with: make upload")
        raise
    except ValueError:
        print(f"✗ Schedule file malformed (bad JSON): {filename}")
        print("  Regenerate it with: make schedule && make upload")
        raise




def schedule_lines(schedule_data):
    """PURE: normalize EITHER schedule shape to a list of line dicts, so no
    caller ever has to branch on which format it was handed.

    Contract: docs/contracts/schedule-json.md § Multiple lines at one
    station. A file with `lines` returns it directly. A file without one is
    a single-line station, and the document itself IS that line — that shape
    is not deprecated, and normalizing here rather than at every use site is
    what keeps every pre-existing schedule working untouched (principle #9).

    Returns at least one entry, so `lines[i % len(lines)]` is always safe.
    Each entry may carry an optional "color" — the line's NOMINAL colour,
    which is what makes a line identifiable at a glance rather than only at
    the moment you cycle to it (gesture-envelope.md §11)."""
    lines = schedule_data.get("lines")
    if lines:
        return lines
    single = {"name": schedule_data.get("station", "line")}
    for period in ("weekday", "weekend"):
        if period in schedule_data:
            single[period] = schedule_data[period]
    return [single]


