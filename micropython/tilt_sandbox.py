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

# ── Response curve ───────────────────────────────────────────────
# Fine control near upright, fast at the extremes — a small tilt should
# nudge, a big one should move. A LINEAR map does not give that: at half
# tilt it already runs at half rate, which is far too fast to aim with.
#
# The standard fix is an expo curve, the same one RC transmitters use on
# a stick: raise the normalised input to a power, keeping the sign. At
# CURVE = 2.5, half tilt runs at 18% rate rather than 50%, while full
# tilt still reaches full rate — so the useful range is spread across the
# whole travel instead of being crammed into the first few degrees.
CURVE = 2.5

# ── Rejecting taps that look like tilt ───────────────────────────
# Found by stress test (2026-09-13): tapping the bottle hard while it sat
# FLAT on the table spoofed a tilt roughly one time in five — engaging a
# session and reading 30-40° that never physically happened.
#
# The cause is that an accelerometer measures gravity PLUS whatever else
# is accelerating it, and a tap is briefly much larger than gravity. Once
# normalised, that sum points somewhere far from "down".
#
# The discriminator is exact and needs no tuning of time constants:
# **tilting preserves the magnitude, accelerating does not.** A bottle
# held at any angle, not moving, still reads |a| = 1 g. A tap reads well
# above (and, on the rebound, below) it. So reject any sample that does
# not have gravity's magnitude BEFORE using its direction.
#
# Worth noting for later: this is the tap recognizer's test run backwards.
# Taps want |a| >> 1 g, tilt wants |a| ≈ 1 g — one sensor stream, split by
# magnitude, so the two gestures can coexist without fighting.
G_TOLERANCE = 0.25          # accept |a| within ±25% of 1 g
SMOOTH_ALPHA = 0.15         # EMA on the gravity direction, ~150ms at 40Hz —
                            #   catches what slips past the magnitude gate
ENGAGE_SAMPLES = 4          # consecutive good samples past the deadzone
                            #   before a session may start

MIN_BRIGHT = 0.03           # never all the way off — a dark strip is
MAX_BRIGHT = 0.90           #   indistinguishable from a fault
POLL_MS = 25

FEEDBACK_COLOR = settings.STARTUP_COLOR
# Green because §12 measured that thick amber glass is a blue-cut filter and
# collapses the hue wheel onto the red-green axis — a blue or purple marker
# would be the obvious choice in air and invisible in this bottle.
TARGET_COLOR = (0, 255, 0)

# ── Target-acquisition test (curve_test) ─────────────────────────
# CURVE is a FEEL parameter, and the edit-reflash-retry loop is a terrible
# way to tune feel. This turns it into a measurement: given a target
# brightness, how long does it take to land on it, and how close do you get?
# Fine control is exactly what expo is supposed to buy, so "time to acquire
# a target" is the thing it should improve. If a higher CURVE does not make
# targets faster to hit, it is not earning its complexity — the same bar
# insights.md §8 held the tap classifier to.
TARGET_TOLERANCE = 0.04     # ≈ one LED of the bar. "Land on the marker."
TARGET_SETTLE_MS = 800      # hold within tolerance this long to count
ROUND_LIMIT_MS = 45000      # give up on a round rather than hang forever

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


def _bar_index(value):
    """Brightness → how many LEDs of the bar are lit."""
    frac = (value - MIN_BRIGHT) / max(1e-6, MAX_BRIGHT - MIN_BRIGHT)
    return max(0, min(NUM_LEDS, int(round(frac * NUM_LEDS))))


def _render(target=None):
    """Whole ring at the CURRENT settings.BRIGHTNESS — or, with a target,
    a level bar plus a marker.

    The plain form takes no argument on purpose: _write_frame multiplies
    by settings.BRIGHTNESS itself, so passing a level would mean two
    sources of truth for one number. It is NOT a level bar, also on
    purpose — the overshoot question is whether this is glare-y in a dark
    room, and only lighting what a real display would light can answer it.

    **The target form is a different test and deliberately renders
    differently.** curve_test asks how precisely you can AIM, not how the
    result looks in a dark room, and aiming at a value you cannot see is
    not a test of the control curve. Both the bar and the marker still go
    through BRIGHTNESS, so they dim together and relative position stays
    readable at any level."""
    if target is None:
        leds._write_frame([(FEEDBACK_COLOR, 1.0)] * NUM_LEDS)
        return
    lit = _bar_index(settings.BRIGHTNESS)
    frame = [(FEEDBACK_COLOR, 1.0) if i < lit else None
             for i in range(NUM_LEDS)]
    mark = max(0, min(NUM_LEDS - 1, _bar_index(target) - 1))
    frame[mark] = (TARGET_COLOR, 1.0)
    leds._write_frame(frame)


def run(curve=None, target=None, announce=True):
    """Adjust brightness by tilting.

    Two shapes, one loop:

    * `target=None` — the OVERSHOOT test. Whole ring at BRIGHTNESS, runs
      until Ctrl+C, reports each session's go-up-first overshoot.
    * `target=<0..1>` — one round of the ACQUISITION test. Renders a bar
      and a marker, returns `(elapsed_ms, final_value)` once the value has
      held within TARGET_TOLERANCE for TARGET_SETTLE_MS, or `None` if
      ROUND_LIMIT_MS expires first. This is what curve_test drives.

    `curve` overrides the module-level CURVE for this call, which is the
    whole point of the second shape — comparing feel parameters by editing
    a constant and reflashing is how you end up trusting the last one you
    tried rather than the best one.
    """
    if curve is None:
        curve = CURVE
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU — nothing to tilt. Check wiring, `make i2c-scan`.")
        return None

    if announce:
        print("\n== tilt_sandbox ==")
        print("   mode=%s  first tilt means %s  deadzone=%.0f°  full=%.0f°"
              "  curve=%.1f"
              % (MODE, FIRST_TILT_MEANS.upper(), DEADZONE_DEG, FULL_TILT_DEG,
                 curve))
        print("   ⚠ RUN THIS IN THE DARK. Try to DIM it, from a standing start.")
        print("   Ctrl+C to stop.\n")

    settings.BRIGHTNESS = max(MIN_BRIGHT, min(MAX_BRIGHT, settings.BRIGHTNESS))
    base = settings.BRIGHTNESS
    sign = 1.0 if FIRST_TILT_MEANS == "up" else -1.0

    round_start = None      # starts at the FIRST ENGAGE, not at the call —
    #   reading the prompt is not part of what the curve is being judged on
    tol_since = [None]
    outcome = [None]

    rest_hat = None
    session = None
    quiet_since = None
    last_err = time.ticks_ms()
    last_ms = time.ticks_ms()
    last_live = time.ticks_ms()
    g_filt = None       # smoothed gravity direction
    rejected = 0        # samples the magnitude gate threw away
    past_deadzone = 0   # consecutive good samples past it — engage debounce

    def _settled(now):
        """True once BRIGHTNESS has held within tolerance long enough.

        Called on EVERY path, deadzone included — settling happens while
        holding still, and holding still is the deadzone branch. Checking
        it only where brightness changes would mean the round could never
        end."""
        if target is None:
            return False
        if abs(settings.BRIGHTNESS - target) <= TARGET_TOLERANCE:
            if tol_since[0] is None:
                tol_since[0] = now
            elif time.ticks_diff(now, tol_since[0]) >= TARGET_SETTLE_MS:
                return True
        else:
            tol_since[0] = None
        return False

    try:
        while True:
            now = time.ticks_ms()
            if round_start is not None and target is not None:
                if time.ticks_diff(now, round_start) >= ROUND_LIMIT_MS:
                    outcome[0] = "timeout"
                    break
            dt_ms = time.ticks_diff(now, last_ms)
            last_ms = now

            raw, last_err = gestures._safe_read_accel(i2c, addr, now, last_err)
            if raw is None:
                time.sleep_ms(POLL_MS)
                continue

            sample_hat, mag_g = _norm(tuple(c * _G_LSB for c in raw))

            # GATE 1 — magnitude. Not gravity, not orientation: drop it
            # before its direction can be believed. See G_TOLERANCE.
            if abs(mag_g - 1.0) > G_TOLERANCE:
                rejected += 1
                time.sleep_ms(POLL_MS)
                continue

            # GATE 2 — smoothing. A glancing knock can land inside the
            # magnitude window; an EMA on the DIRECTION costs one line and
            # makes a single bad sample a fraction of a degree instead of
            # a whole engage. Tilt is slow (~1s), so this loses nothing
            # real.
            if g_filt is None:
                g_filt = sample_hat
            else:
                g_filt = _norm((
                    g_filt[0] + (sample_hat[0] - g_filt[0]) * SMOOTH_ALPHA,
                    g_filt[1] + (sample_hat[1] - g_filt[1]) * SMOOTH_ALPHA,
                    g_filt[2] + (sample_hat[2] - g_filt[2]) * SMOOTH_ALPHA,
                ))[0]
            g_hat = g_filt

            if rest_hat is None:
                rest_hat = g_hat        # first good sample is "upright"
                _render(target)
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
                past_deadzone = 0
                _render(target)
                if _settled(now):
                    outcome[0] = "hit"
                    break
                time.sleep_ms(POLL_MS)
                continue

            quiet_since = None

            # GATE 3 — debounce. One good sample past the deadzone is not
            # a tilt; four in a row (~100ms) is. Cheap, and it is the last
            # thing standing between a knock that survives both gates and
            # a spuriously captured axis.
            past_deadzone += 1
            if session is None and past_deadzone < ENGAGE_SAMPLES:
                _render(target)
                time.sleep_ms(POLL_MS)
                continue

            if session is None:
                if round_start is None:
                    round_start = now
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
            amount = max(0.0, min(1.0, (deg - DEADZONE_DEG) / span))
            amount = (amount ** curve) * along * sign   # expo — see CURVE

            if MODE == "rate":
                settings.BRIGHTNESS += RATE_PER_SEC * amount * (dt_ms / 1000.0)
            else:
                settings.BRIGHTNESS = base + GAIN * amount
            settings.BRIGHTNESS = max(MIN_BRIGHT,
                                      min(MAX_BRIGHT, settings.BRIGHTNESS))

            session.observe(settings.BRIGHTNESS, dt_ms)
            _render(target)
            if _settled(now):
                outcome[0] = "hit"
                break

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
        outcome[0] = "interrupt"
    finally:
        if target is None:
            if session is not None:
                session.report(settings.BRIGHTNESS)
            leds.clear()
            print("\n  %d samples rejected by the magnitude gate (|a| outside"
                  " 1g ±%.0f%%)" % (rejected, G_TOLERANCE * 100))
            print("  cleared — BRIGHTNESS left at %.2f (in RAM only;"
                  " config.py is untouched)" % settings.BRIGHTNESS)

    if target is None or outcome[0] != "hit":
        return None
    elapsed = time.ticks_diff(time.ticks_ms(), round_start or time.ticks_ms())
    return elapsed, settings.BRIGHTNESS


CURVES = (1.0, 2.5, 4.0)        # linear, the current default, aggressive
TARGETS = (0.70, 0.20, 0.45)    # up, a long way down, then a middle value


def curve_test(curves=CURVES, targets=TARGETS):
    """Which CURVE lets you actually hit a number?

    For each curve, for each target: land the bar on the green marker and
    hold it. Time starts at your first tilt, not at the prompt. The
    summary at the end is the finding — if a higher curve does not make
    targets faster to acquire, expo is not earning its keep.

    ⚠ Read insights.md §8's methodology lesson before believing a result
    here: everything this project validated at small n came back smaller
    at scale. One pass of three targets is a HYPOTHESIS. Run it a few
    times, on different days, before changing CURVE on the strength of it.
    """
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU — nothing to tilt. Check wiring, `make i2c-scan`.")
        return

    print("\n== tilt_sandbox: curve test ==")
    print("   Land the bar on the GREEN marker and hold it for %.1fs."
          % (TARGET_SETTLE_MS / 1000.0))
    print("   Tolerance ±%.2f (about one LED). Ctrl+C aborts.\n"
          % TARGET_TOLERANCE)

    results = []
    try:
        for curve in curves:
            print("   ── curve %.1f ──" % curve)
            for target in targets:
                settings.BRIGHTNESS = MIN_BRIGHT if target > 0.5 else MAX_BRIGHT
                print("      target %.2f   (starting from %.2f)"
                      % (target, settings.BRIGHTNESS))
                got = run(curve=curve, target=target, announce=False)
                if got is None:
                    print("      … gave up")
                    results.append((curve, target, None, None))
                else:
                    ms, final = got
                    print("      ✓ %.1fs   landed %.2f (off by %.3f)"
                          % (ms / 1000.0, final, abs(final - target)))
                    results.append((curve, target, ms, final))
            print("")
    except KeyboardInterrupt:
        print("\n   (aborted)")
    finally:
        leds.clear()

    print("   ── summary ──")
    print("   curve   hit   mean time   mean error")
    for curve in curves:
        rows = [r for r in results if r[0] == curve and r[2] is not None]
        total = len([r for r in results if r[0] == curve])
        if not rows:
            print("   %5.1f   0/%d        —           —" % (curve, total))
            continue
        mean_ms = sum(r[2] for r in rows) / len(rows)
        mean_err = sum(abs(r[3] - r[1]) for r in rows) / len(rows)
        print("   %5.1f   %d/%d     %6.1fs      %.3f"
              % (curve, len(rows), total, mean_ms / 1000.0, mean_err))
    print("\n   n=%d per curve — a hypothesis, not a result (insights §8)."
          % len(targets))


ACTIVE = run    # ← swap to curve_test, or call either from the REPL

if __name__ == "__main__":
    ACTIVE()
