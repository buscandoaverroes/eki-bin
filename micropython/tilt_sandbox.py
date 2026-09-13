# micropython/tilt_sandbox.py — eki-bin
#
# Tilt as the native continuous input. Design: light-language.md §6.
#
# Sliding a finger up and down the bottle is the smartphone paradigm
# wearing a bottle. Tilting a bottle is what bottles are FOR — and the IMU
# already gives the gravity vector, so this needs no new hardware at all.
#
# THE QUESTION THIS EXISTS TO ANSWER, and it is one question:
#
#   The axis is defined on the fly by the first tilt, which always means
#   "up". So to DIM you must first BRIGHTEN. In a dark room that is a
#   glare flash — the exact failure the day/night work exists to prevent.
#   Is the overshoot small enough to live with?
#
# **Run this in the dark.** At noon it will feel fine and tell you nothing.
# Every session prints its overshoot: peak above start, and how long it
# spent there. That number is the finding, not the vibe.
#
# FIRST_TILT_MEANS below is the cheap escape hatch worth trying before
# anything more elaborate: if the first tilt means "down" instead, then
# the forced overshoot happens in the harmless direction. One constant.
#
# ⚠ PICK-UP DETECTION IS NOT HERE. light-language.md §6 opens the
# interaction with "pick up → engage", but pick-up currently sits INSIDE
# the pooled handling-noise class that gesture-envelope.md's 98.4%
# threshold rejects — promoting it to a signal is the ESN thread
# (dev-status.md), not this sandbox. So this engages on TILT ITSELF,
# past a deadzone. That tests the part that is actually undecided.
#
#   make tilt-sandbox

import math
import time

import gestures
import leds
import settings
from settings import NUM_LEDS

# ── Tunables ─────────────────────────────────────────────────────
FIRST_TILT_MEANS = "up"     # "up" (as designed) or "down" (the escape hatch)
MODE = "rate"               # "rate": tilt sets RATE of change — hold to keep
                            #   moving, return upright to STOP and keep the
                            #   value. A jog dial. Right for "set and let go".
                            # "absolute": tilt angle maps straight to a value;
                            #   returning upright returns the value. Simpler,
                            #   but you cannot set anything and let go.

DEADZONE_DEG = 8.0          # below this, nothing happens and nothing engages
FULL_TILT_DEG = 45.0        # tilt at which the control is at full authority

# ⚠ WAS 0.45 — retuned on hardware 2026-09-13. At 0.45 units/sec, full tilt
# crossed the whole 0.03..0.90 range in under two seconds: the first real
# session went 0.15 → 0.90 in one movement, which reads as a broken control
# rather than a fast one. 0.12 takes ~7s end to end, which is slow enough to
# aim and still fast enough not to feel stuck.
RATE_PER_SEC = 0.12         # "rate" mode: brightness units per second at full
GAIN = 0.45                 # "absolute" mode: brightness units at full tilt

# ⚠ WAS 1200 — and 1200 made DIMMING STRUCTURALLY IMPOSSIBLE. Reversing
# means tilting back through upright and out the other side, and upright is
# inside the deadzone. At 1200 ms the session released mid-reversal, forgot
# the axis, and the next tilt past the deadzone defined a NEW axis meaning
# UP again — so every attempt to dim brightened instead. See §6-on-hardware
# in light-language.md: "return to upright to stop" and "tilt back to
# reverse" are the SAME movement, and the release timer cannot be shorter
# than a deliberate reversal takes with glass in your hands.
RELEASE_MS = 3500           # this long inside the deadzone ends the session
                            #   and forgets the axis
LIVE_PRINT_MS = 250         # throttled telemetry — without it you cannot
                            #   tell "not working" from "already at a rail"

MIN_BRIGHT = 0.03           # never all the way off — a dark strip is
MAX_BRIGHT = 0.90           #   indistinguishable from a fault
POLL_MS = 25

FEEDBACK_COLOR = settings.STARTUP_COLOR

_G_LSB = 0.061 / 1000.0     # raw → g, same ±2g scaling gestures.py assumes


# ── Vector helpers ───────────────────────────────────────────────
# Three-element tuples rather than a class: this runs at 40 Hz on a
# microcontroller, and MicroPython has no numpy. Written out longhand so
# the geometry is readable, which matters more here than brevity — the
# whole interaction is one dot product and one projection.


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n == 0:
        return (0.0, 0.0, 0.0), 0.0
    return (v[0] / n, v[1] / n, v[2] / n), n


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def _tilt(g_hat, rest_hat):
    """Angle from rest, and the unit direction of the tilt.

    The bottle is radially symmetric and mounted arbitrarily, so there is
    no fixed "forward" to measure against — the reference has to be
    whatever upright happened to be when the session started. Hence
    `rest_hat`, captured at engage.

    Returns (degrees, perp_unit). `perp` is the component of the current
    gravity direction perpendicular to rest: its magnitude is sin(angle)
    and its direction is which way the bottle leaned. That direction is
    the axis the interaction gets defined on."""
    c = max(-1.0, min(1.0, _dot(g_hat, rest_hat)))
    perp = _sub(g_hat, _scale(rest_hat, c))
    perp_hat, mag = _norm(perp)
    # asin saturates at 90°, which is fine: past 90° a bottle is being
    # poured, not adjusted. It clamps rather than wrapping — a wrapped
    # angle would silently reverse the control at the worst moment.
    return math.degrees(math.asin(min(1.0, mag))), perp_hat


class _Session:
    """One engage → adjust → release cycle, and the overshoot it caused.

    Exists to produce the ONE number this sandbox is for: how far the
    brightness went the wrong way before it could go the right way, and
    for how long. A session that dimmed successfully but flashed to 0.8
    on the way there has failed, and only these fields would show it."""

    def __init__(self, start):
        self.start = start
        self.peak = start
        self.above_ms = 0
        self.axis = None

    def observe(self, value, dt_ms):
        if value > self.peak:
            self.peak = value
        if value > self.start + 0.001:
            self.above_ms += dt_ms

    def report(self, end):
        direction = "brighter" if end > self.start else "dimmer"
        print("   ── session: %.2f → %.2f (%s)" % (self.start, end, direction))
        if end < self.start:
            print("      OVERSHOOT: peak %.2f (+%.2f above start), %d ms above"
                  % (self.peak, self.peak - self.start, self.above_ms))
            if self.peak - self.start < 0.02:
                print("      → negligible. go-up-first is fine as designed.")
            else:
                print("      → visible. try FIRST_TILT_MEANS = \"down\".")
        else:
            print("      (brightening — overshoot only matters when dimming)")


def _render():
    """Whole ring at the CURRENT settings.BRIGHTNESS.

    Takes no argument on purpose: _write_frame multiplies by
    settings.BRIGHTNESS itself, so passing a level would mean two sources
    of truth for one number.

    NOT a level bar, on purpose: the question is whether this is glare-y
    in a dark room, and only lighting what a real display would light can
    answer that. The numbers go to the console instead."""
    leds._write_frame([(FEEDBACK_COLOR, 1.0)] * NUM_LEDS)


def run():
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU — nothing to tilt. Check wiring, `make i2c-scan`.")
        return

    print("\n== tilt_sandbox ==")
    print("   mode=%s  first tilt means %s  deadzone=%.0f°  full=%.0f°"
          % (MODE, FIRST_TILT_MEANS.upper(), DEADZONE_DEG, FULL_TILT_DEG))
    print("   ⚠ RUN THIS IN THE DARK. Try to DIM it, from a standing start.")
    print("   Ctrl+C to stop.\n")

    settings.BRIGHTNESS = max(MIN_BRIGHT, min(MAX_BRIGHT, settings.BRIGHTNESS))
    base = settings.BRIGHTNESS
    sign = 1.0 if FIRST_TILT_MEANS == "up" else -1.0

    rest_hat = None
    session = None
    quiet_since = None
    last_err = time.ticks_ms()
    last_ms = time.ticks_ms()
    last_live = time.ticks_ms()

    try:
        while True:
            now = time.ticks_ms()
            dt_ms = time.ticks_diff(now, last_ms)
            last_ms = now

            raw, last_err = gestures._safe_read_accel(i2c, addr, now, last_err)
            if raw is None:
                time.sleep_ms(POLL_MS)
                continue

            g_hat, _ = _norm(tuple(c * _G_LSB for c in raw))
            if rest_hat is None:
                rest_hat = g_hat        # first good sample is "upright"
                _render()
                time.sleep_ms(POLL_MS)
                continue

            deg, perp_hat = _tilt(g_hat, rest_hat)

            if deg < DEADZONE_DEG:
                # Inside the deadzone — which is ALSO the corridor you must
                # pass through to reverse direction. So this timer is not
                # just "idle detection": it is the budget for a deliberate
                # reversal, and if it expires mid-reversal the axis is lost
                # and the next tilt means UP again. See RELEASE_MS.
                if session is not None:
                    if quiet_since is None:
                        quiet_since = now
                        print("   · through neutral — %.1fs to reverse"
                              % (RELEASE_MS / 1000.0))
                    elif time.ticks_diff(now, quiet_since) >= RELEASE_MS:
                        session.report(settings.BRIGHTNESS)
                        base = settings.BRIGHTNESS
                        rest_hat = g_hat     # re-reference: wherever it now sits
                        session = None
                        quiet_since = None
                        print("   (released — tilt again to start over)\n")
                _render()
                time.sleep_ms(POLL_MS)
                continue

            quiet_since = None
            if session is None:
                session = _Session(settings.BRIGHTNESS)
                base = settings.BRIGHTNESS
                # THE AXIS IS DEFINED HERE, by whichever way it first
                # leaned — and forced to mean FIRST_TILT_MEANS. Everything
                # the doc calls "on the fly" is this one assignment.
                session.axis = perp_hat
                print("   engaged — axis captured, this direction = %s"
                      % FIRST_TILT_MEANS.upper())

            # Signed magnitude along the captured axis. Tilting back past
            # upright and out the other side flips the sign, which is what
            # makes one axis carry both directions.
            along = _dot(perp_hat, session.axis)
            span = max(1.0, FULL_TILT_DEG - DEADZONE_DEG)
            amount = (deg - DEADZONE_DEG) / span
            amount = max(-1.0, min(1.0, amount)) * along * sign

            if MODE == "rate":
                settings.BRIGHTNESS += RATE_PER_SEC * amount * (dt_ms / 1000.0)
            else:
                settings.BRIGHTNESS = base + GAIN * amount
            settings.BRIGHTNESS = max(MIN_BRIGHT,
                                      min(MAX_BRIGHT, settings.BRIGHTNESS))

            session.observe(settings.BRIGHTNESS, dt_ms)
            _render()

            # Throttled telemetry. Not decoration: the whole ring renders at
            # BRIGHTNESS, so once the value pins at a rail the display stops
            # changing and a WORKING control is indistinguishable from a
            # dead one. The first hardware session read as "nothing happens"
            # for exactly this reason — it was already at 0.90.
            if time.ticks_diff(now, last_live) >= LIVE_PRINT_MS:
                last_live = now
                rail = ""
                if settings.BRIGHTNESS >= MAX_BRIGHT - 1e-6:
                    rail = "  ⟨at MAX — tilt the other way⟩"
                elif settings.BRIGHTNESS <= MIN_BRIGHT + 1e-6:
                    rail = "  ⟨at MIN — tilt the other way⟩"
                print("   %5.1f°  %s  %.2f%s"
                      % (deg, "UP  " if amount > 0 else "DOWN",
                         settings.BRIGHTNESS, rail))

            time.sleep_ms(POLL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        if session is not None:
            session.report(settings.BRIGHTNESS)
        leds.clear()
        print("\n  cleared — BRIGHTNESS left at %.2f (in RAM only; config.py"
              " is untouched)" % settings.BRIGHTNESS)


if __name__ == "__main__":
    run()
