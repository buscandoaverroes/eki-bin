# micropython/onboard_led_test.py — eki-bin bring-up
# WHICH ONBOARD INDICATORS EXIST, AND WHICH CAN SOFTWARE ACTUALLY TURN OFF?
#
# Run:  make onboard-led-test
#
# ══ THE QUESTION ════════════════════════════════════════════════════════
# A board typically has more LEDs than it documents, and they are not all
# equal: some hang off a GPIO, some are wired straight to the power rail
# and cannot be controlled at all. That distinction is invisible on a bench
# and decisive inside a glass jar — a pinprick of light no firmware can
# reach has to be dealt with physically (tape, desolder, orientation), and
# you want to know that BEFORE the unit is sealed.
#
# This walks every controllable indicator through known states with pauses,
# so you can watch what changes. **Anything still lit during the ALL-OFF
# steps is hardwired.** That is the whole answer.
#
# ⚠ Do not infer from colour. On 2026-08-23 an apparent "bright red =
# healthy, faint yellow = sagging rail" correlation drove a long
# misdiagnosis; it broke when faint yellow appeared on a bare, healthy
# board. Colour told us nothing. Only "does it change when I drive it"
# distinguishes a GPIO LED from a power LED. docs/insights.md §13.
#
# Findings go in pinouts/<board>.md, not here — this script is per-board
# reusable, the answers are not.

from machine import Pin
import time

PAUSE_S = 4  # long enough to look up from the screen and actually look
# Level for the NeoPixel steps. Raised from 40 to 160 on 2026-09-03: at 40 the
# RED step read as "nothing happened" in two consecutive runs, because this
# board has a faint always-on red LED right beside the pixel that masked it.
# A full-scale (255,0,0) check proved the channel fine. A diagnostic that can
# report a working channel as dead is worse than no diagnostic.
NP_LEVEL = 160


def _try(label, fn):
    """Run a step; report what the board does or doesn't have. A missing
    alias is a FINDING about this board, not an error."""
    try:
        fn()
        print("    %s" % label)
        return True
    except (AttributeError, ImportError, TypeError, ValueError) as e:
        print("    %s — not available on this board (%s)" % (label, e))
        return False


def _led(on):
    """⚠ POLARITY IS PER-BOARD. XIAO RP2350's "LED" is ACTIVE-LOW: value(0)
    lights it. Pico 2W's is active-high. This helper takes the INTENT ("on")
    and the caller sets ACTIVE_LOW; getting it backwards is how you 'turn
    off' an LED by lighting it."""
    Pin("LED", Pin.OUT).value(0 if (on == ACTIVE_LOW) else 1)


ACTIVE_LOW = True  # XIAO RP2350. Set False for a Pico-2W-style board.


def _np(color):
    from neopixel import NeoPixel
    gate = Pin("NEOPIXEL_POWER", Pin.OUT)
    gate.on()                     # gate is active-high on the XIAO RP2350
    np = NeoPixel(Pin("NEOPIXEL"), 1)
    np[0] = color
    np.write()


def _np_off():
    from neopixel import NeoPixel
    gate = Pin("NEOPIXEL_POWER", Pin.OUT)
    gate.on()
    np = NeoPixel(Pin("NEOPIXEL"), 1)
    np[0] = (0, 0, 0)
    np.write()                    # BLACK FIRST — the pixel latches, so
    gate.off()                    # gating a lit pixel leaves it primed


def step(n, title, fn):
    print("\n  [%d] %s" % (n, title))
    fn()
    time.sleep(PAUSE_S)


def main():
    print("\n══ eki-bin onboard indicator test ════════════════")
    print("  Watch the BOARD, not the screen. %ds per step." % PAUSE_S)
    print("  ⚠ The answer is what stays lit in steps 1 and 7.\n")

    step(1, "ALL OFF — note anything STILL LIT (that one is hardwired)",
         lambda: (_try("user LED off", lambda: _led(False)),
                  _try("NeoPixel off + power gated", _np_off)))
    step(2, "user LED ON", lambda: _try("→ did a light appear?", lambda: _led(True)))
    step(3, "user LED OFF", lambda: _try("→ did it go?", lambda: _led(False)))
    step(4, "NeoPixel RED", lambda: _try("→ red?", lambda: _np((160, 0, 0))))
    step(5, "NeoPixel GREEN", lambda: _try("→ green?", lambda: _np((0, 160, 0))))
    step(6, "NeoPixel BLUE", lambda: _try("→ blue?", lambda: _np((0, 0, 160))))
    step(7, "ALL OFF again — anything still lit is NOT software-controllable",
         lambda: (_try("user LED off", lambda: _led(False)),
                  _try("NeoPixel off + power gated", _np_off)))

    print("\n  ── what you just learned ──")
    print("  • changed in steps 2/3  → the user LED, on a GPIO. Controllable.")
    print("  • changed in steps 4-6  → the NeoPixel. Controllable.")
    print("  • LIT THROUGHOUT        → hardwired to the rail. No firmware")
    print("                            fix exists. Options are physical:")
    print("                            opaque tape (reversible), desolder the")
    print("                            LED or its resistor (permanent), or")
    print("                            orient the board away from the glass.")
    print("\n  Record the result in pinouts/<board>.md, not here.\n")


main()
