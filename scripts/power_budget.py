#!/usr/bin/env python3
"""scripts/power_budget.py — can eki-bin run on batteries, and for how long?

Run it:  python3 scripts/power_budget.py            (defaults)
         python3 scripts/power_budget.py --help     (every knob)

═══ WHY A MODEL RATHER THAN AN ANSWER ══════════════════════════════════
Every number below that is not measured is marked ESTIMATE, because this
project has been burned repeatedly by plausible assumptions (a filesystem
1.78x its flash; blue assumed to be the weak LED channel; brightness assumed
to fix hue separation). The point of this script is to show WHICH number
decides the outcome, so measurement effort goes where it matters instead of
being spread evenly.

═══ THE FINDING THAT DECIDES IT ════════════════════════════════════════
**A WS2812B draws current when it is BLACK.** Each pixel contains a
constant-current driver IC that is powered whenever VDD is present,
regardless of the colour latched into it — roughly 0.7-1.0 mA each.

    21 LEDs x ~0.8 mA  =  ~17 mA, CONTINUOUSLY, showing nothing at all.

On a 2000 mAh pack that is about five days with the display never once
lighting up. It dwarfs the MCU's sleep current by an order of magnitude and
makes every other optimisation irrelevant.

    => A battery build REQUIRES a load switch (P-MOSFET or a load-switch IC)
       cutting VDD to the strip while idle. This is not a refinement; it is
       the difference between five days and several months.

Note this also explains something already observed: an unaddressed strip
holding its power-up state browned out the board (docs/insights.md §13).
Same root cause — the strip draws power on its own terms, not the
firmware's.

═══ WHAT MUST BE MEASURED (in priority order) ══════════════════════════
  1. Board-level SLEEP current of the XIAO RP2350 with the LED strip gated
     off. Datasheet core figures are useless here: the regulator's quiescent
     draw and any always-on board LED dominate, and they are board facts, not
     chip facts. Measure with a multimeter in series with the pack.
  2. Strip quiescent current, ungated, all-black. Confirms the 0.8 mA/LED
     figure on YOUR tape.
  3. Active current with the display actually running the approach contract.
  4. Real tap frequency. The duty cycle is the second-largest lever and it is
     a behaviour, not a spec.
"""

import argparse

# ── Component currents, mA ────────────────────────────────────────
# ESTIMATE markers are load-bearing: replace them with measurements.
DEFAULTS = {
    "mcu_sleep_ma": 1.0,       # ESTIMATE. XIAO RP2350 board-level, dormant.
    #                            Regulator quiescent usually dominates the core.
    "mcu_active_ma": 35.0,     # ESTIMATE. RP2350 running, no radio.
    "imu_sleep_ma": 0.02,      # LSM6DSV16X low-power + wake-on-tap, datasheet
    "led_idle_ma_each": 0.8,   # ESTIMATE. WS2812B quiescent, BLACK.
    "led_lit_ma_each": 5.0,    # ESTIMATE. One lit pixel at BRIGHTNESS 0.15,
    #                            line colours (not full white, which is ~60mA)
    "switch_leak_ma": 0.001,   # load-switch off-state leakage, typical
}

# Nominal capacities, mAh. NiMH figures are Eneloop-class.
PACKS = [
    ("2x AA alkaline",    2500, 3.0),
    ("3x AA alkaline",    2500, 4.5),
    ("4x AA NiMH",        1900, 4.8),
    ("3x AA NiMH",        1900, 3.6),
    ("4x AAA NiMH",        750, 4.8),
    ("3x AAA alkaline",   1000, 4.5),
]


def runtime_days(idle_ma, active_ma, hours_active_per_day, capacity_mah,
                 derate=0.8):
    """Days per charge. `derate` accounts for the fraction of nominal capacity
    actually usable before the pack sags below the regulator's dropout —
    NOT a safety margin, a real effect, and pessimistic-ish at 0.8."""
    per_day = (active_ma * hours_active_per_day
               + idle_ma * (24 - hours_active_per_day))
    if per_day <= 0:
        return float("inf")
    return capacity_mah * derate / per_day * 1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leds", type=int, default=21)
    ap.add_argument("--lit", type=int, default=4,
                    help="pixels actually lit — the approach contract shows "
                         "an anchor plus a few trains, not the whole strip")
    ap.add_argument("--awake-min", type=float, default=15.0,
                    help="AWAKE_MINUTES: how long a tap keeps the display on")
    ap.add_argument("--taps-per-day", type=float, default=6.0)
    ap.add_argument("--gated", action="store_true", default=True,
                    help="LED strip on a load switch (default)")
    ap.add_argument("--no-gate", dest="gated", action="store_false",
                    help="strip permanently powered — shows why you can't")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=v)
    a = ap.parse_args()

    hours_active = a.taps_per_day * a.awake_min / 60.0
    strip_idle = 0.0 if a.gated else a.leds * a.led_idle_ma_each
    idle_ma = a.mcu_sleep_ma + a.imu_sleep_ma + strip_idle + (
        a.switch_leak_ma if a.gated else 0.0)
    active_ma = a.mcu_active_ma + a.lit * a.led_lit_ma_each + \
        (a.leds - a.lit) * a.led_idle_ma_each

    print("\n══ eki-bin power budget ══════════════════════════════════")
    print("  strip: %d LEDs, %d lit    display on %.0f min x %.1f taps/day "
          "= %.2f h/day" % (a.leds, a.lit, a.awake_min, a.taps_per_day,
                            hours_active))
    print("  LED power: %s" % ("GATED (load switch)" if a.gated
                               else "⚠ ALWAYS ON"))
    print()
    print("  IDLE   %6.3f mA   = mcu %.3f + imu %.3f + strip %.3f"
          % (idle_ma, a.mcu_sleep_ma, a.imu_sleep_ma, strip_idle))
    print("  ACTIVE %6.1f mA   = mcu %.0f + %d lit x %.1f + %d dark x %.1f"
          % (active_ma, a.mcu_active_ma, a.lit, a.led_lit_ma_each,
             a.leds - a.lit, a.led_idle_ma_each))
    per_day = active_ma * hours_active + idle_ma * (24 - hours_active)
    print("  → %.1f mAh/day   (%.0f%% of it idle)"
          % (per_day, 100 * idle_ma * (24 - hours_active) / per_day))
    print()
    print("  pack                 mAh    V    runtime")
    print("  ─────────────────────────────────────────────")
    for name, mah, volts in PACKS:
        d = runtime_days(idle_ma, active_ma, hours_active, mah)
        note = ""
        if volts < 3.5:
            note = "  ⚠ below WS2812B VDD min"
        print("  %-18s %5d  %3.1fV  %6.1f days%s" % (name, mah, volts, d, note))

    print("\n  ── what moves the needle ──")
    base = runtime_days(idle_ma, active_ma, hours_active, 1900)
    for label, kw in [
        ("AWAKE_MINUTES 15 → 3", dict(hours_active=a.taps_per_day * 3 / 60.0)),
        ("taps/day 6 → 2", dict(hours_active=2 * a.awake_min / 60.0)),
        ("MCU sleep 1.0 → 0.1 mA", dict(idle_ma=idle_ma - a.mcu_sleep_ma + 0.1)),
        ("lit pixels 4 → 2", dict(active_ma=active_ma - 2 * a.led_lit_ma_each)),
    ]:
        d = runtime_days(kw.get("idle_ma", idle_ma),
                         kw.get("active_ma", active_ma),
                         kw.get("hours_active", hours_active), 1900)
        print("  %-26s %6.1f days  (%+.0f%%)"
              % (label, d, 100 * (d - base) / base))
    print()


if __name__ == "__main__":
    main()
