# micropython/low_pwm_test.py — eki-bin colour bring-up
# Finds the LOW-PWM FLOOR of a WS2812B strip: the smallest value at which
# equal R=G=B actually reads neutral. Standalone and NOT config-driven —
# edit the constants below by hand, same convention as led_test.py.
#
# ══ THE PROBLEM THIS ANSWERS ════════════════════════════════════════════
# Marker ticks render at (1,1,1) and read WARM YELLOW, not dim grey. Below
# roughly 4-5/255 the WS2812B's three channels stop matching each other, so
# "equal values" stops meaning "neutral" (docs/insights.md §12). The current
# MARKER_BRIGHTNESS = 0 is a WORKAROUND that removes the affordance
# entirely, not a fix.
#
# This is a STRIP property, not a bottle property — the channels mismatch
# whether or not there's glass in front of them. So it can be answered on
# the bench, unlike hue separation, which genuinely needs the bottle.
# Confirm the final number through the glass, but find it here.
#
# ══ ⚠ RAW VALUES — NO GAMMA, NO BRIGHTNESS SCALING ══════════════════════
# main.py's pipeline applies gamma correction and BRIGHTNESS before writing.
# This script deliberately does NEITHER: the question is what the LED does
# with a raw PWM value, and any scaling in between would hide the answer.
# Numbers here are what reaches the chip.
#
# ══ WIRING ══════════════════════════════════════════════════════════════
#   XIAO RP2350: 5V→VCC  GND→GND  D7/GPIO1→DIN  → DATA_PIN = 1
#   Pico 2W:     VBUS→VCC GND→GND  GP6→DIN       → DATA_PIN = 6
#   ⚠ Verify DATA_PIN against pinouts/<board>.md BEFORE connecting the
#     strip. A wrong pin means the strip is never addressed, holds whatever
#     state it powered up in (possibly full white, ~480mA), and can brown
#     the board out — see docs/insights.md §13.
#
# Run without flashing:  make run-file FILE=micropython/low_pwm_test.py
#
# ══ HOW TO USE IT ═══════════════════════════════════════════════════════
# Set MODE below, run, and LOOK at the strip. Every mode shows all its
# candidates AT ONCE, on different LEDs, because comparing colours
# side-by-side is reliable and comparing them across time is not — your
# eye adapts within a couple of seconds.
#
#   "ramp"      LED i shows (v,v,v) for v = 1..NUM_LEDS.
#               → Find the lowest LED that reads NEUTRAL GREY rather than
#                 warm/yellow. That index is your floor.
#
#   "channels"  Pairs of LEDs show pure R, pure G, pure B, then white, all
#               at CHANNEL_TEST_VALUE.
#               → If they differ in apparent brightness at the SAME numeric
#                 value, that mismatch is the cause of the colour cast.
#                 Measured on this strip: red > blue > green. Confirm per
#                 strip rather than assuming — the ramp above disproved an
#                 earlier guess that blue was the weak one.
#
#   "balanced"  Eight hand-picked (r,g,b) candidates that are NOT equal —
#               per-channel compensation attempts.
#               → Find the dimmest one that still reads neutral. If one
#                 works below the "ramp" floor, markers can live there and
#                 MARKER_BRIGHTNESS need not stay 0.
#
# Record what you find in docs/insights.md §12, with the strip and value.

import time

from machine import Pin
from neopixel import NeoPixel

DATA_PIN = 1  # ⚠ SET PER BOARD — see wiring above and pinouts/<board>.md
NUM_LEDS = 21  # AE-WS2812B-STICK8 = 8; gift-jar strip = 21

MODE = "ramp"  # "ramp" | "channels" | "balanced"

CHANNEL_TEST_VALUE = 2  # "channels" mode: the raw value to compare across R/G/B

# "balanced" mode candidates — these LIFT GREEN.
#
# Measured on the 8-LED stick 2026-08-24, from the "ramp" mode above:
#   (1,1,1) reads RED      → red is strongest at the bottom
#   (2,2,2) reads PURPLE   → red + blue present, GREEN missing
#   (3,3,3) reads neutral  → the equal-value floor on this strip
# So the low-PWM ordering here is red > blue > green, and green is what
# needs lifting. (An earlier version of this file assumed blue was weak and
# biased these candidates the wrong way — the ramp is what settled it.)
#
# Ordered by total output, dimmest first: the useful answer is the FIRST one
# that reads neutral, since anything below the (3,3,3) total of 9 beats the
# equal-value floor.
BALANCED_CANDIDATES = [
    (1, 1, 1),  # total 3 — the current marker colour, reads red
    (1, 2, 1),  # total 4
    (1, 2, 2),  # total 5
    (1, 3, 1),  # total 5
    (1, 3, 2),  # total 6
    (2, 3, 2),  # total 7
    (2, 4, 2),  # total 8
    (2, 3, 3),  # total 8
]

np = NeoPixel(Pin(DATA_PIN, Pin.OUT), NUM_LEDS)


def _show(values, legend):
    """Write raw tuples straight to the strip and print what's where."""
    for i in range(NUM_LEDS):
        np[i] = values[i] if i < len(values) else (0, 0, 0)
    np.write()
    print()
    for i, line in enumerate(legend):
        print("    LED %d : %s" % (i, line))
    print()


def ramp():
    print("  RAMP — LED i shows (v,v,v), v = i+1")
    print("  Look for the lowest LED that reads NEUTRAL GREY, not warm.")
    values = [(v, v, v) for v in range(1, NUM_LEDS + 1)]
    _show(values, ["(%d,%d,%d)" % v for v in values])


def channels():
    v = CHANNEL_TEST_VALUE
    print("  CHANNELS — pure R, G, B and white, all at raw value %d" % v)
    print("  Unequal apparent brightness at the SAME value is the cause")
    print("  of the colour cast. Note which channel looks weakest.")
    values = [
        (v, 0, 0),
        (v, 0, 0),
        (0, v, 0),
        (0, v, 0),
        (0, 0, v),
        (0, 0, v),
        (v, v, v),
        (v, v, v),
    ]
    _show(
        values,
        [
            "red %d" % v,
            "red %d" % v,
            "green %d" % v,
            "green %d" % v,
            "blue %d" % v,
            "blue %d" % v,
            "white %d" % v,
            "white %d" % v,
        ],
    )


def balanced():
    print("  BALANCED — per-channel compensation candidates")
    print("  Find the DIMMEST one that still reads neutral.")
    _show(BALANCED_CANDIDATES, ["%s" % (c,) for c in BALANCED_CANDIDATES])


def main():
    print("\n══ eki-bin low-PWM floor test ════════════════════")
    print(
        "  %d LEDs on GPIO%d — RAW values, no gamma, no BRIGHTNESS"
        % (NUM_LEDS, DATA_PIN)
    )
    print("  mode: %r" % MODE)

    modes = {"ramp": ramp, "channels": channels, "balanced": balanced}
    if MODE not in modes:
        print("  ✗ MODE=%r unknown — pick one of %s" % (MODE, ", ".join(sorted(modes))))
        return
    modes[MODE]()

    print("  Holding. Ctrl+C to stop (the strip keeps its last state —")
    print("  it latches, so clear it before unplugging).")
    try:
        while True:
            time.sleep_ms(200)
    except KeyboardInterrupt:
        for i in range(NUM_LEDS):
            np[i] = (0, 0, 0)
        np.write()
        print("\n  cleared — bye\n")


main()
