# micropython/led_test.py — eki-bin hardware bring-up
# Hello-world for a WS2812B strip. Standalone and NOT config-driven: edit
# DATA_PIN / NUM_LEDS below by hand to match the board + strip you're testing.
# (One-off bring-up script, deliberately separate from main.py's config pipeline.)
#
# Wiring (see docs/hardware.md and pinouts/<board>.md):
#   Pico 2W:  VBUS(pin40)→VCC(5V)   GND(pin38)→GND   GP6(pin9)→DIN   → DATA_PIN=6
#   XIAO C3:  5V→VCC(5V)            GND→GND           D0/GPIO2→DIN    → DATA_PIN=2
#
# Run without flashing:   make led-test                 (runs this file)
#          any file:      make run-file FILE=<path>      (e.g. a NUM_LEDS=120 copy)
#
# [→ Rust/V2] In Embassy this becomes a PIO/RMT program generating the tight
#             800kHz WS2812B waveform in hardware, so the CPU isn't bit-banging.
#             `neopixel` here is the MicroPython frozen-module stand-in for that.

import time

from machine import Pin
from neopixel import NeoPixel

# ── Configuration ────────────────────────────────────────────────
DATA_PIN = 2  # WS2812B data line — SET PER BOARD (Pico 2W=6, XIAO C3=2); see header
NUM_LEDS = 8  # SET PER STRIP (AE-WS2812B-STICK8=8, WS2812B-4020 tape=120, …)
BRIGHTNESS = 0.15  # 0.0–1.0. Keep it low: 8 LEDs at full white ≈ 480mA off VBUS,
# and it's blinding from a hand's distance. 0.15 is ample for
# a bring-up — bump it later once you trust the wiring.

# NeoPixel wraps an output Pin and the LED count. WS2812B is physically GRB
# order, but MicroPython's driver handles that for us, so we always write (r,g,b).
np = NeoPixel(Pin(DATA_PIN, Pin.OUT), NUM_LEDS)

# Named colours at full scale; BRIGHTNESS is applied at write time.
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
AMBER = (255, 120, 0)
WHITE = (255, 255, 255)


def scale(color):
    """Apply BRIGHTNESS to an (r, g, b) tuple. Integer math, 0–255 per channel."""
    return tuple(int(c * BRIGHTNESS) for c in color)


def fill(color):
    """Set every LED to one colour and latch it to the strip."""
    c = scale(color)
    for i in range(NUM_LEDS):
        np[i] = c
    np.write()  # nothing changes on the strip until write() clocks the data out


def clear():
    fill((0, 0, 0))


def solid_cycle(hold=0.6):
    """Flood the whole stick with each colour in turn — confirms all 8 light and
    that red/green/blue channels are wired and ordered correctly."""
    for name, color in (
        ("RED", RED),
        ("GREEN", GREEN),
        ("BLUE", BLUE),
        ("AMBER", AMBER),
        ("WHITE", WHITE),
    ):
        print("  fill", name)
        fill(color)
        time.sleep(hold)


def chase(color, delay=0.18, trail=3):
    """Moving dot with a fading tail. The head is full BRIGHTNESS; each
    trailing LED is dimmer, so the eye reads motion rather than a lone pixel."""
    for head in range(NUM_LEDS + trail):  # +trail so the tail walks off the end
        for i in range(NUM_LEDS):
            dist = head - i
            if 0 <= dist <= trail:
                fade = (trail - dist) / trail  # 1.0 at head → 0 at tail end
                np[i] = tuple(int(c * BRIGHTNESS * fade) for c in color)
            else:
                np[i] = (0, 0, 0)
        np.write()
        time.sleep(delay)


def main():
    print("\n══ eki-bin LED test ══════════════════════════════")
    print(
        "  {} LEDs on GP{}, brightness {:.0f}%".format(
            NUM_LEDS, DATA_PIN, BRIGHTNESS * 100
        )
    )
    print("  Ctrl+C to stop\n")
    try:
        while True:
            solid_cycle()
            print("  chase ↓")
            for color in (RED, GREEN, BLUE):
                chase(color)
    except KeyboardInterrupt:
        pass
    finally:
        clear()  # always leave the strip dark on exit
        print("\n  cleared — bye")


main()
