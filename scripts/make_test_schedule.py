#!/usr/bin/env python3
"""
scripts/make_test_schedule.py
Host-side only. Generates a synthetic multi-LINE timetable for testing.

Why this exists: line-cycling (docs/contracts/gesture-envelope.md §11) can't
be tested against a real schedule, because a real one has exactly one line.
Hand-writing several is slow and produces timetables too regular to exercise
the interesting paths (rush-hour density, last train, empty periods).

Emits **YAML, not JSON**, on purpose. `scripts/convert_schedule.py` stays the
only thing that writes a .json, so this can't quietly become a second and
divergent source of truth — docs/contracts/schedule-json.md already says
"never hand-edit the JSON," and a generator that skipped the converter would
be hand-editing it with extra steps.

    python3 scripts/make_test_schedule.py --lines 4 --out schedules/testbench.yaml
    make schedule STATION=testbench     # → schedules/testbench.json

Then point config.py at it: SCHEDULE_FILE stays "schedule.json"; `make upload`
copies schedules/<STATION>.json to that name on the device.
"""

import argparse
import colorsys
import sys
from pathlib import Path

# Real Tokyo line colours. Deliberately includes near-collisions (Chuo orange
# vs Ginza orange; Marunouchi red vs Chuo orange) because that is the actual
# discrimination problem through tinted glass — docs/insights.md §3 found red
# vs. orange already ambiguous in the brown jar. A palette that *only* used
# comfortably-separated hues would flatter the display and prove nothing.
TOKYO = [
    ("yamanote", (154, 205, 50)),    # yellow-green
    ("chuo", (255, 102, 0)),         # orange
    ("keihin_tohoku", (0, 178, 229)), # light blue
    ("marunouchi", (243, 0, 8)),     # red
    ("ginza", (255, 149, 0)),        # orange — near-collides with chuo, on purpose
    ("hanzomon", (149, 129, 200)),   # purple
]


def evenly_spaced_palette(n, hue_shift_deg=0.0, saturation=1.0, value=1.0):
    """n maximally-separated hues. The DIAGNOSTIC default: even spacing is
    what tells you where separability breaks through your particular glass.
    Realism is what `--palette tokyo` is for."""
    out = []
    for i in range(n):
        hue = ((i / n) + hue_shift_deg / 360.0) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
        out.append((f"line_{i + 1}", (round(r * 255), round(g * 255), round(b * 255))))
    return out


def shift_hue(rgb, degrees):
    """Rotate one colour's hue, preserving saturation/value. Mirrors main.py's
    hue_rotate() so a shift previewed here matches what the firmware would do."""
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb((h + degrees / 360.0) % 1.0, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def departures(start_min, end_min, base_headway, rush_headway, rush_windows, offset=0):
    """Build one direction's departures, denser during rush windows.

    Not a uniform comb on purpose: a perfectly regular timetable never
    exercises the interesting branches (a long gap before the last train,
    a period with nothing catchable). Times are minutes since midnight, and
    may exceed 1440 — that's the extended-hours convention ("24:30" = 00:30),
    which convert_schedule.py already expects and which keeps arrays sorted.
    """
    times, t = [], start_min + offset
    while t <= end_min:
        times.append(t)
        in_rush = any(lo <= (t % 1440) <= hi for lo, hi in rush_windows)
        t += rush_headway if in_rush else base_headway
    return times


def to_hhmm(minutes):
    """Extended-hours HH:MM, e.g. 1470 → '24:30'. Deliberately does NOT wrap
    past midnight — see the module docstring of convert_schedule.py."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build(args):
    if args.palette == "tokyo":
        if args.lines > len(TOKYO):
            sys.exit(f"--palette tokyo has {len(TOKYO)} colours; asked for {args.lines}")
        palette = TOKYO[: args.lines]
        if args.hue_shift:
            palette = [(n, shift_hue(c, args.hue_shift)) for n, c in palette]
    else:
        palette = evenly_spaced_palette(args.lines, args.hue_shift)

    rush = [(7 * 60, 9 * 60), (17 * 60, 20 * 60)]
    lines = []
    for i, (name, color) in enumerate(palette):
        line = {"name": name, "color": list(color)}
        for period in ("weekday", "weekend"):
            base = args.headway if period == "weekday" else args.headway + 4
            windows = rush if period == "weekday" else []
            line[period] = {
                # Each line and direction is phase-offset so they don't all
                # depart in lockstep — otherwise every line renders identically
                # and line-cycling would look broken when it's working.
                "a": [to_hhmm(m) for m in departures(
                    args.first * 60, args.last * 60, base, args.rush_headway,
                    windows, offset=(i * 2) % base)],
                "b": [to_hhmm(m) for m in departures(
                    args.first * 60, args.last * 60, base, args.rush_headway,
                    windows, offset=(i * 2 + base // 2) % base)],
            }
        lines.append(line)
    return lines


def render_yaml(station, lines):
    """Hand-rolled rather than yaml.dump so the output keeps its comments and
    reads like the committed example file — a generated file people actually
    open should look like one they'd have written."""
    out = [
        "# GENERATED by scripts/make_test_schedule.py — safe to overwrite.",
        "# Synthetic multi-line test data. Not a real timetable.",
        "#",
        "# Format: docs/contracts/schedule-json.md § Multiple lines at one station.",
        "# `color` is the line's NOMINAL colour; per-enclosure correction belongs",
        "# in config.py, since how it must be driven to look right through YOUR",
        "# glass is a fact about your bottle, not about the line.",
        "",
        f"station: {station}",
        "",
        "lines:",
    ]
    for line in lines:
        out.append(f"  - name: {line['name']}")
        out.append(f"    color: [{line['color'][0]}, {line['color'][1]}, {line['color'][2]}]")
        for period in ("weekday", "weekend"):
            out.append(f"    {period}:")
            for direction in ("a", "b"):
                out.append(f"      {direction}:")
                for t in line[period][direction]:
                    out.append(f'        - "{t}"')
        out.append("")
    return "\n".join(out) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    p.add_argument("--lines", type=int, default=3, help="how many lines (default 3)")
    p.add_argument("--station", default="testbench")
    p.add_argument("--palette", choices=("even", "tokyo"), default="even",
                   help="'even' = maximally-separated hues (diagnostic, default); "
                        "'tokyo' = real line colours incl. near-collisions")
    p.add_argument("--hue-shift", type=float, default=0.0, metavar="DEG",
                   help="rotate the whole palette — cheap way to probe tinted-glass "
                        "compensation without regenerating timetables")
    p.add_argument("--headway", type=int, default=8, help="off-peak minutes between trains")
    p.add_argument("--rush-headway", type=int, default=3)
    p.add_argument("--first", type=int, default=5, help="first departure hour")
    p.add_argument("--last", type=int, default=24, help="last departure hour (24+ = past midnight)")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if args.lines < 1:
        sys.exit("--lines must be >= 1")
    if args.last <= args.first:
        sys.exit("--last must be after --first")

    lines = build(args)
    out = args.out or Path("schedules") / f"{args.station}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_yaml(args.station, lines))

    print(f"✓ {out}")
    total = 0
    for line in lines:
        n = len(line["weekday"]["a"])
        c = line["color"]
        total += sum(len(v) for p in ("weekday", "weekend") for v in line[p].values())
        print(f"   {line['name']:<16} rgb{tuple(c)}  {n} weekday departures/direction")

    # Departure counts matter on this hardware, so say so rather than letting
    # it be discovered on the device. The single real line is ~8KB of JSON;
    # main.py parses the whole file into RAM at boot, and the resulting object
    # graph is several times the text size. docs/insights.md §11 is the
    # cautionary tale — a few KB in the wrong place cost days.
    approx_kb = total * 9 // 1024  # ~9 bytes/entry as rendered JSON text
    print(f"\n   {total} departures total, ≈{approx_kb}KB of JSON")
    if approx_kb > 15:
        print("   ⚠ Large. main.py holds the WHOLE file in RAM; the parsed object")
        print("     graph is several times this. If the device struggles, cut")
        print("     --lines, widen --headway, or narrow --first/--last.")
    print(f"\n   next:  make schedule STATION={args.station}")


if __name__ == "__main__":
    main()
