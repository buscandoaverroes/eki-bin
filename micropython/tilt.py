# micropython/tilt.py — eki-bin
#
# Tilt-to-adjust, as a reusable controller. Design: light-language.md §6;
# the hardware findings that shaped every constant here: insights.md §15.
#
# This is the ONE implementation. tilt_sandbox.py drives it for data
# collection and main.py drives it in the real loop — duplicating it would
# be genuinely dangerous, because almost nothing in here is obvious and
# most of it is a correction to something that failed on real hardware.
#
# Feed it raw accelerometer samples; it returns a state string and mutates
# settings.BRIGHTNESS. No I2C, no LEDs, no printing — which is what makes
# the whole state machine host-testable from synthetic samples, unlike the
# sandbox it came from.

import math

import settings
from settings import (TILT_BASELINE_ALPHA, TILT_DEADZONE_DEG, TILT_ENGAGE_SAMPLES,
    TILT_EXPO, TILT_FIRST_MEANS, TILT_FULL_DEG, TILT_G_TOLERANCE,
    TILT_MAX_BRIGHT, TILT_MIN_BRIGHT, TILT_RAIL_REPEAT_MS, TILT_RATE_PER_SEC,
    TILT_SMOOTH_ALPHA, TILT_STILL_DEG, TILT_STILL_MS, TILT_STILL_WINDOW)

# ⚠ THE "3.5s TO REVERSE" BUDGET IS GONE, and its absence is a feature.
# The sandbox ended a session after a dwell inside the deadzone, which
# doubled as the window for turning around — so reversing slowly forgot the
# axis and the next tilt meant UP again. Once stillness became the release
# condition that whole conflict dissolves: returning to upright and holding
# it in your hand is NOT still, so the session survives and you can take as
# long as you like to reverse. The axis is forgotten only when the bottle
# is genuinely set down.

_G_LSB = 0.061 / 1000.0     # raw → g at ±2g, same scaling gestures.py assumes


def expo(x, amount=None):
    """PURE: blended linear/cubic expo. x in 0..1, returns 0..1.

    The form RC transmitters use, not a power curve. A power curve puts all
    its authority in the last few degrees before full tilt — which a bottle
    on a table rarely reaches — so across the band actually used every high
    exponent reads the same: "barely moving". insights.md §15.

      amount 0.0 → linear        amount 1.0 → pure cubic
    """
    if amount is None:
        amount = TILT_EXPO
    return amount * (x * x * x) + (1.0 - amount) * x


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n == 0:
        return (0.0, 0.0, 0.0), 0.0
    return (v[0] / n, v[1] / n, v[2] / n), n


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def tilt_from(g_hat, rest_hat):
    """PURE: (degrees from rest, unit direction of the lean).

    A bottle is radially symmetric and mounted arbitrarily, so there is no
    fixed "forward" to measure against — the reference has to be whatever
    upright was, which is what `rest_hat` carries.

    asin saturates at 90°, deliberately: past 90° a bottle is being poured,
    not adjusted, and a wrapped angle would silently reverse the control at
    the worst possible moment.
    """
    c = max(-1.0, min(1.0, _dot(g_hat, rest_hat)))
    perp = (g_hat[0] - rest_hat[0] * c,
            g_hat[1] - rest_hat[1] * c,
            g_hat[2] - rest_hat[2] * c)
    perp_hat, mag = _norm(perp)
    return math.degrees(math.asin(min(1.0, mag))), perp_hat


class TiltController:
    """Raw accel samples in, settings.BRIGHTNESS out.

    update() returns one of:
        "wait"      — sample rejected, or still learning the reference
        "idle"      — inside the deadzone, nothing happening
        "up"/"down" — actively adjusting
        "released"  — a session just ended and neutral was re-learned

    Everything below is a correction to a failure on real hardware. In
    order of how much grief each one caused:

    1. **The magnitude gate.** An accelerometer measures gravity PLUS
       whatever else is accelerating it, so a hard tap briefly points the
       normalised vector far from down — spoofing a 30-40° tilt about one
       time in five. Tilting preserves |a| = 1g; accelerating does not. So
       the magnitude is tested BEFORE the direction is believed. This is
       also what lets tap and tilt share one sensor: taps want |a| >> 1g,
       tilt wants |a| ≈ 1g, one stream split by magnitude.

    2. **Re-learning neutral.** Capturing the reference once at startup
       makes "upright" whatever was under the sensor at that instant —
       which produced a bottle flat on a table reading 8.1° forever, never
       releasing, brightness creeping down. Neutral has to be re-learned
       from where the bottle actually rests.

    3. **Stillness is about DURATION, not depth.** Measured: a table reads
       0.11° of jitter and a very steady hand reads 0.12° — they overlap,
       so no threshold on spread alone works. What separates them is that
       the longest hand-held quiet run is a couple of seconds and a table
       is quiet indefinitely. Hence a long TILT_STILL_MS rather than a
       tight TILT_STILL_DEG.
    """

    def __init__(self):
        self.rest = None        # unit gravity direction that means "upright"
        self.filt = None        # smoothed gravity direction
        self.axis = None        # direction of the current session's first lean
        self.engaged = False
        self.past_deadzone = 0
        self.still_win = []
        self.still_since = 0
        self.rejected = 0
        self.deg = 0.0
        self.jitter = None      # None until the stillness window fills
        self.rate = 0.0         # brightness units/sec right now — signed
        self.rail_bounce = None # "min"/"max" for exactly ONE update when a
        #   rail is freshly hit; None otherwise. See _note_rail.
        self._rail_at = None
        self._sign = 1.0 if TILT_FIRST_MEANS == "up" else -1.0

    def update(self, raw, now_ms, dt_ms):
        sample, mag_g = _norm((raw[0] * _G_LSB, raw[1] * _G_LSB, raw[2] * _G_LSB))

        # (1) magnitude gate — not gravity, so its direction means nothing
        if abs(mag_g - 1.0) > TILT_G_TOLERANCE:
            self.rejected += 1
            self.rate = 0.0
            return "wait"

        # smoothing catches glancing knocks that land inside the window
        if self.filt is None:
            self.filt = sample
        else:
            a = TILT_SMOOTH_ALPHA
            self.filt = _norm((
                self.filt[0] + (sample[0] - self.filt[0]) * a,
                self.filt[1] + (sample[1] - self.filt[1]) * a,
                self.filt[2] + (sample[2] - self.filt[2]) * a,
            ))[0]

        if self.rest is None:
            self.rest = self.filt
            self.still_since = now_ms
            return "wait"

        deg, perp = tilt_from(self.filt, self.rest)
        self.deg = deg

        # (3) stillness — on the RAW angle, because the smoothing above
        # removes exactly the tremor that distinguishes a hand from a table
        raw_deg, _u = tilt_from(sample, self.rest)
        self.still_win.append(raw_deg)
        if len(self.still_win) > TILT_STILL_WINDOW:
            self.still_win.pop(0)
        if len(self.still_win) >= TILT_STILL_WINDOW:
            self.jitter = max(self.still_win) - min(self.still_win)
        else:
            self.jitter = None
        if self.jitter is None or self.jitter > TILT_STILL_DEG:
            self.still_since = now_ms
        steady = _elapsed(now_ms, self.still_since) >= TILT_STILL_MS

        # A session that has gone quiet ends at WHATEVER ANGLE it went quiet
        # at — this is the escape from a false neutral, and without it the
        # 8.1°-forever case cannot recover.
        if self.engaged and steady:
            self.rest = self.filt        # (2) here IS neutral now
            self.engaged = False
            self.axis = None
            self.past_deadzone = 0
            self.rate = 0.0
            return "released"

        if deg < TILT_DEADZONE_DEG:
            self.past_deadzone = 0
            self.rate = 0.0
            if not self.engaged:
                # Idle and level: let neutral drift to where it actually
                # sits. The same auto-baselining a capacitive touch chip
                # does at power-on (surface-as-input.md §2). Gated on
                # not-engaged so it can never eat a deliberate slow tilt.
                b = TILT_BASELINE_ALPHA
                self.rest = _norm((
                    self.rest[0] + (self.filt[0] - self.rest[0]) * b,
                    self.rest[1] + (self.filt[1] - self.rest[1]) * b,
                    self.rest[2] + (self.filt[2] - self.rest[2]) * b,
                ))[0]
            return "idle"

        # One good sample past the deadzone is not a tilt; four in a row is.
        self.past_deadzone += 1
        if not self.engaged:
            if self.past_deadzone < TILT_ENGAGE_SAMPLES:
                self.rate = 0.0
                return "idle"
            self.engaged = True
            self.axis = perp          # the axis, defined on the fly

        along = _dot(perp, self.axis)
        span = max(1.0, TILT_FULL_DEG - TILT_DEADZONE_DEG)
        amount = max(0.0, min(1.0, (deg - TILT_DEADZONE_DEG) / span))
        amount = expo(amount) * along * self._sign

        self.rate = TILT_RATE_PER_SEC * amount
        wanted = settings.BRIGHTNESS + self.rate * (dt_ms / 1000.0)
        settings.BRIGHTNESS = max(TILT_MIN_BRIGHT, min(TILT_MAX_BRIGHT, wanted))
        self._note_rail(wanted, now_ms)
        return "up" if amount > 0 else "down"

    def _note_rail(self, wanted, now_ms):
        """Flag a FRESH arrival at a brightness rail, throttled.

        Reported because a rail is invisible: the display simply stops
        changing, and "already at maximum" looks exactly like "not
        working" — which is precisely how the first hardware session read
        it (insights.md §15). `wanted` rather than the clamped value is
        what makes this detectable at all: the clamp destroys the evidence
        that you were still asking for more.

        Throttled rather than edge-only, because holding a tilt past the
        rail is a continuous request and answering it once and then going
        silent for a minute is the same silence again."""
        self.rail_bounce = None
        hit = None
        if wanted > TILT_MAX_BRIGHT:
            hit = "max"
        elif wanted < TILT_MIN_BRIGHT:
            hit = "min"
        if hit is None:
            self._rail_at = None
            return
        if (self._rail_at is None
                or _elapsed(now_ms, self._rail_at) >= TILT_RAIL_REPEAT_MS):
            self.rail_bounce = hit
            self._rail_at = now_ms


def _elapsed(now_ms, since_ms):
    """ticks_diff without importing time — the controller never needs a
    clock of its own, only the difference between two stamps its caller
    already has."""
    d = now_ms - since_ms
    return d if d >= 0 else 0
