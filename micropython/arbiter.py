# micropython/arbiter.py — eki-bin
#
# When a tap becomes real. The middle block of detect → arbiter → classify
# (docs/imu-interaction-plan.md §2 and Phase 2).
#
# Detect says "something happened" and classify says "it looked like a tap",
# but both judge the first moment, and the first moment of a grab looks like
# a tap. What tells them apart comes LATER: a finger leaves the bottle still,
# a hand doesn't. So a classified tap is a CLAIM, and the arbiter settles it:
#
#   t0 ── ring-down ──┬── quiet window ──┐
#   trigger    0-250ms │    250-600 ms    │
#                      │                  ├─ still → COMMIT (proved; nothing later undoes it)
#                      │                  └─ not still → still provisional:
#                      │                       sustained rotation / tilt → VETO "handled after"
#                      │                       nothing by SETTLE_MAX     → VETO "not still"
#   handling ended < LOOKBACK before t0 ──────────────────────────────► VETO "handled before"
#
# "Settle on evidence of stillness, not a timer" is the plan's own advice,
# and the guided session is why it's the only option: a hand-then-tilt
# starts rotating 0.46-1.37 s after the grab, while a tap-then-grab can grab
# as soon as 1.0 s after the tap. No fixed window separates those; stillness
# does (AUC 0.92).
#
# Like tilt.py this is the ONE implementation: scripts/sim.py drives it on
# recordings and live, and main.py will drive it when ARBITER_ENABLED is
# switched on. Pure: no I2C, no LEDs, times are ticks_ms values, compared
# with ticks_since so the 12.4-day wrap can't stall a candidate.
#
# THE COST, stated as the plan states it: nothing extra when the bottle is
# still (it settles at 600 ms, inside the 1.2 s capture classify already
# waits for). A tap made with a hand resting on the bottle never settles,
# and is vetoed. That is the trade, chosen on purpose.

import math

from primitives import ticks_since
from settings import (ARBITER_LOOKBACK_MS, ARBITER_QUIET_FROM_MS, ARBITER_QUIET_MG,
    ARBITER_QUIET_MS, ARBITER_RINGDOWN_MS, ARBITER_ROT_DPS, ARBITER_ROT_MS,
    ARBITER_SETTLE_MAX_MS)

COMMIT = "commit"
VETO = "veto"
REJECT = "reject"            # classify said no; the arbiter only passes it on

_ROT_TAU_MS = 25.0           # smoothing for the rotation rate (see tilt.py's alpha)


class _Claim:
    """One trigger on its way to a decision."""

    def __init__(self, t0):
        self.t0 = t0
        self.verdict = None      # None until classify answers; then (is_tap, why)
        self.veto = None         # the arbiter's reason, once it has one
        self.quiet = None        # None until the quiet window closes; then bool
        self.rms_mg = None
        self.n = 0
        self.ref = None          # the window's first sample: sums are taken about it
        self.s = [0.0, 0.0, 0.0]
        self.ss = [0.0, 0.0, 0.0]


class Arbiter:
    """Feed it every sample the loop (or a capture) reads, with update().
    Tell it about each trigger with claim() and about classify's answer with
    verdict(). update() returns the decisions that became final:
    [(COMMIT | VETO | REJECT, t0, reason)]."""

    def __init__(self, quiet_from_ms=ARBITER_QUIET_FROM_MS, quiet_ms=ARBITER_QUIET_MS,
                 quiet_mg=ARBITER_QUIET_MG, rot_dps=ARBITER_ROT_DPS, rot_ms=ARBITER_ROT_MS,
                 ringdown_ms=ARBITER_RINGDOWN_MS, lookback_ms=ARBITER_LOOKBACK_MS,
                 settle_max_ms=ARBITER_SETTLE_MAX_MS):
        self.quiet_from_ms, self.quiet_ms, self.quiet_mg = quiet_from_ms, quiet_ms, quiet_mg
        self.rot_dps, self.rot_ms = rot_dps, rot_ms
        self.ringdown_ms, self.lookback_ms = ringdown_ms, lookback_ms
        self.settle_max_ms = settle_max_ms
        self._rot = 0.0          # smoothed rotation rate, dps
        self._run_since = None   # when the current run above rot_dps began
        self._handled_at = None  # the last moment handling was in progress
        self._last_ms = None
        self.claims = []

    # ── the ledger: is a hand on it? ───────────────────────────────────
    def handling(self, now_ms):
        """Sustained rotation right now (the last update said so)."""
        return (self._run_since is not None
                and ticks_since(now_ms, self._run_since) >= self.rot_ms)

    def _track(self, now_ms, gyro_dps, tilting):
        dt = 0 if self._last_ms is None else ticks_since(now_ms, self._last_ms)
        self._last_ms = now_ms
        if gyro_dps is None:
            # No gyro baseline yet: no rotation evidence either way. The tilt
            # controller is still evidence on its own.
            self._run_since = None
        else:
            a = 1.0 - math.exp(-dt / _ROT_TAU_MS) if dt > 0 else 1.0
            self._rot += a * (gyro_dps - self._rot)
            if self._rot > self.rot_dps:
                if self._run_since is None:
                    self._run_since = now_ms
            else:
                self._run_since = None
        busy = self.handling(now_ms) or tilting
        if busy:
            self._handled_at = now_ms
        return busy

    # ── claims ────────────────────────────────────────────────────────
    def claim(self, t0):
        """A trigger at t0. Judged against what came BEFORE it straight
        away: a hand that was just on the bottle makes this the hand
        leaving it."""
        c = _Claim(t0)
        if (self._handled_at is not None
                and ticks_since(t0, self._handled_at) <= self.lookback_ms):
            c.veto = "handled before"
        self.claims.append(c)
        return c

    def verdict(self, t0, is_tap, why=None):
        for c in self.claims:
            if c.t0 == t0 and c.verdict is None:
                c.verdict = (bool(is_tap), why)
                return

    def update(self, now_ms, accel_mg, gyro_dps=None, tilting=False):
        """One sample: accel_mg (x, y, z) in mg, gyro_dps the rotation rate
        with the bias removed (None if there's no baseline yet).

        `tilting`: the tilt controller is ADJUSTING right now (its state is
        up/down). Not `engaged`: that means a tilt session is open, and one
        stays open until the bottle has been still for TILT_STILL_MS (6 s),
        on purpose — so in the guided session it read engaged 87% of the
        time, taps included, and vetoed nearly everything as handling."""
        busy = self._track(now_ms, gyro_dps, tilting)
        out = []
        keep = []
        for c in self.claims:
            age = ticks_since(now_ms, c.t0)
            if c.quiet is None:
                if self.quiet_from_ms <= age < self.quiet_from_ms + self.quiet_ms:
                    if c.ref is None:
                        c.ref = tuple(accel_mg)
                    c.n += 1
                    for k in range(3):
                        d = accel_mg[k] - c.ref[k]
                        c.s[k] += d
                        c.ss[k] += d * d
                elif age >= self.quiet_from_ms + self.quiet_ms:
                    c.rms_mg = _rms(c) if c.n >= 2 else None
                    c.quiet = c.rms_mg is not None and c.rms_mg <= self.quiet_mg
            # Proven still → nothing later counts against it: a tap, then a
            # grab a second later, is still a tap.
            if c.veto is None and not c.quiet and age >= self.ringdown_ms and busy:
                c.veto = "tilt" if tilting and not self.handling(now_ms) else "handled after"
            if c.veto is None and not c.quiet and age >= self.settle_max_ms:
                c.veto = "not still"
            decision = self._decide(c)
            if decision is None:
                keep.append(c)
            else:
                out.append(decision)
        self.claims = keep
        return out

    def _decide(self, c):
        if c.verdict is not None and not c.verdict[0]:
            return (REJECT, c.t0, c.verdict[1])
        if c.veto is not None:
            return (VETO, c.t0, c.veto)
        if c.verdict is not None and c.quiet:
            return (COMMIT, c.t0, None)
        return None


def _rms(c):
    """RMS distance from the window's own mean, mg: how much it moved, not
    where it points.

    ⚠ The sums are about the window's FIRST sample, not zero, and that is
    load-bearing on the device. MicroPython's floats here are 32-bit (~7
    digits). Summed raw, gravity makes x² ~ 1e6 mg², and E[x²] − E[x]²
    subtracts two numbers that big to find a variance of ~1 — the answer
    is lost in rounding. About a nearby reference the values are a few mg,
    and nothing cancels. (Host Python's 64-bit floats hide this, so a host
    test wouldn't catch it unless it forces float32.)"""
    var = 0.0
    for k in range(3):
        m = c.s[k] / c.n
        var += max(0.0, c.ss[k] / c.n - m * m)
    return math.sqrt(var)
