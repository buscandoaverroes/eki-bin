# micropython/hue_test.py — eki-bin colour bring-up
# HOW MANY LINES CAN THE GLASS SUPPORT? Shows candidate line colours side by
# side so you can judge separation through an actual vessel. Standalone and
# NOT config-driven — edit the constants below, same convention as
# led_test.py and low_pwm_test.py.
#
# ══ THE QUESTION ════════════════════════════════════════════════════════
# Colour is the line identity in this design (docs/contracts/
# approach-contract.md): position means urgency, hue means which line. So
# the number of lines the product can support is capped by how many hues
# stay distinguishable through the glass — not by anything in the data model.
#
# docs/insights.md §12 found that through the brown bottle only NEAR-OPPOSITE
# hues survive: blue vs yellow/red separate, adjacent hues collapse. That was
# observed incidentally on a running unit. This makes it a deliberate test.
#
# ══ WHY THIS NEEDS THE BOTTLE, UNLIKE low_pwm_test.py ═══════════════════
# The low-PWM floor is a property of the LED and is answerable on a bench.
# Hue separation is a property of the GLASS — diffusion and tint change what
# is distinguishable without changing what the chip emits. A bare strip will
# tell you a comforting lie here.
#
# An 8-LED stick on long jumpers, dropped unfastened into a vessel, is a
# BETTER rig than the assembled unit for this: candidate hues sit adjacent
# for direct comparison instead of scattered around an arc. Absolute
# brightness will not transfer (spacing and distance-to-glass differ), but
# relative discrimination does — and that is the question.
#
# ⚠ Try SEVERAL vessels. The glass is a design variable, not a fixed
# constraint: `docs/glass-stone-concept.md` §3 argues clear glass sidesteps
# this problem entirely. If brown caps you at three lines and clear supports
# six, that is a product decision this script can inform.
#
# Run:  make run-file FILE=micropython/hue_test.py
#
# ══ HOW TO USE IT ═══════════════════════════════════════════════════════
#   1. Start with MODE="even", COUNT=3. Can you name each one confidently
#      through the glass, without knowing the order?
#   2. Raise COUNT until two neighbours stop separating. COUNT-1 is what
#      that vessel supports.
#   3. Repeat per vessel, and at 2-3 BRIGHTNESS values — §12 suspects
#      brightness and discrimination interact through diffusion.
#   4. Then MODE="tokyo" for the real-world case: those colours include a
#      DELIBERATE near-collision (chuo/ginza, both orange). If they separate
#      through your glass, real line colours are viable; if not, the palette
#      has to be chosen for the bottle rather than for realism.
#
# Record what you find in docs/insights.md §12, with the vessel described.

import time

from machine import Pin
from neopixel import NeoPixel

DATA_PIN = 1  # ⚠ SET PER BOARD — verify against pinouts/<board>.md FIRST.
#                A wrong pin leaves the strip unaddressed, holding whatever
#                state it powered up in, at up to ~480mA (insights.md §13).
NUM_LEDS = 8

MODE = "tokyo"  # "even" | "tokyo" | "pairs"
COUNT = 5  # how many distinct hues to show (even/tokyo)
BRIGHTNESS = 0.30  # scales everything; §12 expects the bottle needs more
HUE_SHIFT_DEG = 0.0  # rotate the whole palette — cheap probe for whether a
#                      tinted glass can be compensated by pre-rotating hues
SPREAD = True  # True: repeat hues to fill the strip (bigger patches,
#                      easier to judge). False: one LED each, rest dark.

# Per-channel GAIN, applied BEFORE brightness. The glass-compensation probe,
# and the one thing raising BRIGHTNESS cannot do.
#
# Measured 2026-08-24: a thick opaque brown bottle collapses the hue wheel
# onto the RED-GREEN axis. Amber glass is a blue-cut filter by design — it
# exists to block short wavelengths — so a light blue (0,178,229) read as
# "faint vomit yellow/green": its blue absorbed, only green surviving. Red
# and violet merged for the same reason (violet minus blue IS red).
#
# BRIGHTNESS could never fix that: scaling preserves the RATIOS between
# channels, so it cannot restore one the glass removes. 0.15 -> 0.30 changed
# nothing in that bottle, exactly as this predicts.
#
# GAIN can. Try (1.0, 1.0, 3.0) or higher in a thick brown vessel. Both
# outcomes are useful:
#   * blue recovers     -> the vessel is usable, at the cost of a compensated
#                          palette and less blue headroom before clipping
#   * blue stays absent -> the glass has removed a dimension. The palette
#                          must live on red-green, or line identity needs a
#                          non-colour channel — see docs/insights.md §12.
GAIN = (1.0, 1.0, 1.0)

# Real Tokyo line colours, mirroring scripts/make_test_schedule.py's TOKYO
# palette so what you see here is what a generated schedule would render.
# chuo and ginza near-collide ON PURPOSE — that pair is the hard case.
TOKYO = [
    ("yamanote", (154, 205, 50)),
    ("chuo", (255, 102, 0)),
    ("keihin_tohoku", (0, 178, 229)),
    ("marunouchi", (243, 0, 8)),
    ("ginza", (255, 149, 0)),
    ("hanzomon", (149, 129, 200)),
]

np = NeoPixel(Pin(DATA_PIN, Pin.OUT), NUM_LEDS)


def _hsv_to_rgb(h, s, v):
    """Minimal HSV→RGB; MicroPython has no colorsys. Matches the maths in
    scripts/make_test_schedule.py's evenly_spaced_palette()."""
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    i %= 6
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i]
    return (int(r * 255), int(g * 255), int(b * 255))


def even_palette(n):
    return [
        (
            "hue %d" % i,
            _hsv_to_rgb(((i / float(n)) + HUE_SHIFT_DEG / 360.0) % 1.0, 1.0, 1.0),
        )
        for i in range(n)
    ]


def _scaled(rgb):
    """GAIN first, then BRIGHTNESS, then clamp. Clipping is REPORTED rather
    than hidden: a channel pinned at 255 stops responding to further gain,
    and reading that as "the glass ate it" is the obvious wrong conclusion."""
    return tuple(
        max(0, min(255, int(c * GAIN[ch] * BRIGHTNESS))) for ch, c in enumerate(rgb)
    )


def _show(palette):
    n = len(palette)
    if SPREAD:
        assign = [i * n // NUM_LEDS for i in range(NUM_LEDS)]
    else:
        assign = [i if i < n else None for i in range(NUM_LEDS)]
    for led, idx in enumerate(assign):
        np[led] = (0, 0, 0) if idx is None else _scaled(palette[idx][1])
    np.write()
    print()
    for led, idx in enumerate(assign):
        if idx is None:
            print("    LED %d : —" % led)
        else:
            name, rgb = palette[idx]
            clipped = "".join(
                "RGB"[ch] for ch in range(3) if rgb[ch] * GAIN[ch] * BRIGHTNESS > 255
            )
            print(
                "    LED %d : %-14s %-16s → %s%s"
                % (led, name, rgb, _scaled(rgb),
                   "  ⚠ %s CLIPPED" % clipped if clipped else "")
            )
    print()


def main():
    print("\n══ eki-bin hue separation test ═══════════════════")
    print(
        "  %d LEDs on GPIO%d   brightness %.2f   hue shift %+.0f°"
        % (NUM_LEDS, DATA_PIN, BRIGHTNESS, HUE_SHIFT_DEG)
    )
    if GAIN != (1.0, 1.0, 1.0):
        print("  gain: R x%.1f  G x%.1f  B x%.1f" % GAIN)
    print("  mode: %r   count: %d" % (MODE, COUNT))

    if MODE == "even":
        palette = even_palette(COUNT)
    elif MODE == "tokyo":
        if COUNT > len(TOKYO):
            print("  ✗ tokyo palette has %d colours; COUNT=%d" % (len(TOKYO), COUNT))
            return
        palette = TOKYO[:COUNT]
    elif MODE == "pairs":
        # The hardest case: two hues HUE_SHIFT_DEG apart, alternating. Shrink
        # the gap until they merge — that angle is the glass's resolution.
        base = _hsv_to_rgb(0.0, 1.0, 1.0)
        other = _hsv_to_rgb((HUE_SHIFT_DEG / 360.0) % 1.0, 1.0, 1.0)
        palette = [("base", base), ("shifted", other)]
    else:
        print("  ✗ MODE=%r unknown — use even, tokyo or pairs" % MODE)
        return

    _show(palette)
    print("  Judge through the glass, not on the bench. Ctrl+C to stop")
    print("  (the strip LATCHES — this clears it on exit).")
    try:
        while True:
            time.sleep_ms(200)
    except KeyboardInterrupt:
        for i in range(NUM_LEDS):
            np[i] = (0, 0, 0)
        np.write()
        print("\n  cleared — bye\n")


main()
