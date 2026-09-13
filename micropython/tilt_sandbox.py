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
# ⚠ WAS 45. Real sessions live in the 8-30° band — a bottle on a table is
# awkward past 35° and needs lifting past 45°. Full authority has to be
# reachable in the range actually used, or the top of the curve is
# decorative.
FULL_TILT_DEG = 35.0        # tilt at which the control is at full authority

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
# ⚠ WAS a power curve, `x ** CURVE`. Replaced 2026-09-13 after a real
# session reported that changing it "even to 10" made no perceptible
# difference. The arithmetic says it should: at 18° tilt x = 0.27, so
# x**10 ≈ 0.000002 — a dead stick. Two things hid that:
#
#   1. **A power curve collapses the mid-range.** All the authority ends
#      up in the last few degrees before FULL_TILT_DEG, and a bottle on a
#      table rarely gets there — so across the band actually used, every
#      high curve reads the same: "barely moving".
#   2. **The operator closes the loop.** Given a slower response people
#      just tilt further, which cancels the very change they were trying
#      to judge. It feels identical while being numerically very different.
#
# The blended form below is what RC transmitters actually use, and it is
# better behaved for exactly this complaint: EXPO is bounded 0..1, both
# endpoints are pinned (0→0, 1→1), and the mid-range degrades gently
# instead of falling off a cliff.
#
#   EXPO = 0.0  →  linear        EXPO = 1.0  →  pure cubic
#
# At EXPO 0.6, half tilt gives 0.6*0.125 + 0.4*0.5 = 0.275 — finer than
# linear's 0.5, but not x**2.5's 0.18 or x**10's 0.001.
EXPO = 0.6


def expo(x, amount=None):
    """PURE: blended linear/cubic expo. x in 0..1, returns 0..1."""
    if amount is None:
        amount = EXPO
    return amount * (x * x * x) + (1.0 - amount) * x

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

# ── Keeping "neutral" honest ─────────────────────────────────────
# The first version captured `rest_hat` once, from the first good sample,
# and never re-established it except on release. That produced the failure
# the 2026-09-13 session hit repeatedly: a bottle sitting FLAT ON THE TABLE
# reading 8.1° forever, never falling inside the deadzone, so the session
# never released and brightness kept creeping. Later, the same bottle sat
# at a rock-steady 28.5° — twelve identical prints, which no hand produces.
#
# Both are one bug. "Neutral" was whatever orientation happened to be
# under the sensor at the instant the script started — often mid-handling,
# and never the surface it ends up resting on.
#
# Two independent fixes, because each covers a case the other does not:
#
#   STILL_DEG   — release on "the tilt has STOPPED CHANGING", not only on
#                 "the tilt is small". A bottle steady at 8.1° is plainly
#                 at rest; only an absolute test could miss that.
#   BASELINE_*  — while idle and inside the deadzone, leak `rest_hat`
#                 toward where the bottle actually is. Whatever it has been
#                 resting on becomes neutral within a few seconds. This is
#                 the same auto-baselining every capacitive touch chip does
#                 at power-on, for the same reason (surface-as-input.md §2).
#
# The leak runs ONLY when no session is active AND we are inside the
# deadzone, so it can never eat a deliberate slow tilt.
# ⚠ STILL_DEG WAS 2.0, AND THAT WAS TOO LOOSE. A hand holding a tilt to
# aim sits inside 2° easily, so the release fired MID-TILT and made 25°
# the new neutral — the exact false reference the stillness test was added
# to escape. Overcorrected in the direction of the original bug.
#
# The discriminator that actually separates the two cases:
#
#     A HAND IS NEVER PERFECTLY STILL. A BOTTLE ON A TABLE IS.
#
# Not "has it stopped moving much" — that is a judgement call with a
# threshold in the middle of the distribution. "Is it moving at all, above
# the sensor's own noise" has the two populations on opposite sides of it:
# human tremor is always present, and a resting object has none.
#
# Two changes follow from that:
#
#   * Measure the SPREAD over a short window, not drift from a reference.
#     A slow hand drift passes a drift test while never being still.
#   * Measure it on the RAW sample, not the EMA'd one. SMOOTH_ALPHA exists
#     to remove exactly the high-frequency tremor that distinguishes a
#     hand from a table, so testing the smoothed signal throws away the
#     evidence.
#
# 0.4° is a STARTING GUESS, not a measured value. The telemetry prints the
# live spread precisely so the real number can be read off a session: hold
# it, then set it down, and look at where the two populations sit.
STILL_DEG = 0.4             # spread, in degrees, over STILL_WINDOW samples
STILL_WINDOW = 24           # ~0.6s at POLL_MS — long enough to catch tremor
STILL_RELEASE_MS = 1500     # stillness this long releases. DIFFERENT JOB
#   from RELEASE_MS, hence a different number: RELEASE_MS is the budget for
#   a deliberate reversal through the deadzone, this is "you put it down".
BASELINE_ALPHA = 0.02       # ~1.2s to re-learn neutral at 40Hz

MIN_BRIGHT = 0.03           # never all the way off — a dark strip is
MAX_BRIGHT = 0.90           #   indistinguishable from a fault
POLL_MS = 25

FEEDBACK_COLOR = settings.STARTUP_COLOR
# Green because §12 measured that thick amber glass is a blue-cut filter and
# collapses the hue wheel onto the red-green axis — a blue or purple marker
# would be the obvious choice in air and invisible in this bottle.
TARGET_COLOR = (0, 255, 0)

# ── Target-acquisition test (curve_test) ─────────────────────────
# EXPO is a FEEL parameter, and the edit-reflash-retry loop is a terrible
# way to tune feel. This turns it into a measurement: given a target
# brightness, how long does it take to land on it, and how close do you get?
# Fine control is exactly what expo is supposed to buy, so "time to acquire
# a target" is the thing it should improve. If a higher EXPO does not make
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

    `curve` overrides the module-level EXPO for this call, which is the
    whole point of the second shape — comparing feel parameters by editing
    a constant and reflashing is how you end up trusting the last one you
    tried rather than the best one.
    """
    if curve is None:
        curve = EXPO
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
    still_win = []      # recent RAW tilt angles — spread is the stillness test
    still_since = None

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

            # Stillness, on the RAW angle and as a SPREAD — see STILL_DEG.
            # Tested on the angle rather than on brightness because a
            # control pinned at a rail stops changing brightness while the
            # bottle is still being waved around.
            raw_deg, _unused = _tilt(sample_hat, rest_hat)
            still_win.append(raw_deg)
            if len(still_win) > STILL_WINDOW:
                still_win.pop(0)
            spread = (max(still_win) - min(still_win)) if len(still_win) >= STILL_WINDOW else 999.0
            if spread > STILL_DEG:
                still_since = now
            steady = time.ticks_diff(now, still_since) >= STILL_RELEASE_MS

            # A session that has gone quiet ends here regardless of the
            # ANGLE it went quiet at — this is the escape from a false
            # neutral, and without it the 8.1°-forever case cannot recover.
            if session is not None and steady:
                session.report(settings.BRIGHTNESS)
                base = settings.BRIGHTNESS
                rest_hat = g_hat     # whatever it settled at IS neutral now
                session = None
                quiet_since = None
                past_deadzone = 0
                print("   (set down at %.1f°, spread %.2f° — that"
                      " orientation is now neutral)\n" % (deg, spread))
                _render(target)
                if _settled(now):
                    outcome[0] = "hit"
                    break
                time.sleep_ms(POLL_MS)
                continue

            if deg < DEADZONE_DEG:
                # Idle and level: let neutral drift to wherever the bottle
                # actually sits. See BASELINE_ALPHA.
                if session is None:
                    rest_hat = _norm((
                        rest_hat[0] + (g_hat[0] - rest_hat[0]) * BASELINE_ALPHA,
                        rest_hat[1] + (g_hat[1] - rest_hat[1]) * BASELINE_ALPHA,
                        rest_hat[2] + (g_hat[2] - rest_hat[2]) * BASELINE_ALPHA,
                    ))[0]
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
            amount = expo(amount, curve) * along * sign

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
                # `rate` is the thing EXPO actually changes. Printing only
                # degrees and brightness meant the curve's effect had to be
                # inferred from how fast a number crept — which is why
                # "even 10 made no difference" was a reasonable reading of
                # a genuinely huge change.
                print("   %5.1f°  %s  rate %+.3f/s  %.2f  jitter %.2f°%s"
                      % (deg, "UP  " if amount > 0 else "DOWN",
                         RATE_PER_SEC * amount, settings.BRIGHTNESS,
                         spread if spread < 900 else 0.0, rail))

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


CURVES = (0.0, 0.6, 1.0)        # linear, the current default, pure cubic
TARGETS = (0.70, 0.20, 0.45)    # up, a long way down, then a middle value


def curve_test(curves=CURVES, targets=TARGETS):
    """Which EXPO lets you actually hit a number?

    For each curve, for each target: land the bar on the green marker and
    hold it. Time starts at your first tilt, not at the prompt. The
    summary at the end is the finding — if a higher curve does not make
    targets faster to acquire, expo is not earning its keep.

    ⚠ Read insights.md §8's methodology lesson before believing a result
    here: everything this project validated at small n came back smaller
    at scale. One pass of three targets is a HYPOTHESIS. Run it a few
    times, on different days, before changing EXPO on the strength of it.
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


ACTIVE = curve_test    # ← swap to curve_test, or call either from the REPL

if __name__ == "__main__":
    ACTIVE()
