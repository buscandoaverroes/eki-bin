# micropython/signals.py — eki-bin
# STAGE 1 of the pipeline: time → abstract signal. Extracted verbatim from
# main.py by the V1.6 split (docs/v1.6-refactor.md) — MOVED, not rewritten.
#
# `Urgency` is a PURE ABSTRACT LEVEL: no colour, no animation, no LED. Those
# are rendering decisions belonging to contracts.py. That separation is the
# project's central design idea (docs/contracts/display-contract.md) —
# "what's the urgency?" is computed once per tick, independently of "how do
# we show it?".
#
# So this module must never import leds or contracts. If it ever needs to,
# the separation has been broken somewhere.
#
# [→ Rust] Urgency becomes a real `enum`, LeaveSignal a struct.

from settings import *  # noqa: F401,F403

# ═════════════════════════════════════════════════════════════
# STAGE 1 — time → abstract signal
# ═════════════════════════════════════════════════════════════


# Urgency is a *pure abstract level* — no colour, no animation. Those are
# rendering decisions and live on the contracts (Stage 2). V1 stand-in for a
# future Rust `enum Urgency`.
class Urgency:
    def __init__(self, name, level):
        self.name = name
        self.level = level  # 0 = hidden, 1 = most urgent … higher = more relaxed

    def __repr__(self):
        return self.name


# Singletons — compare with `is`, like enum variants. Band edges are configurable
# (URGENCY_THRESHOLDS); the comments show the defaults (2, 5).
HIDDEN = Urgency("HIDDEN", 0)
LEVEL_1 = Urgency("LEVEL 1", 1)  # below threshold[0] — go now
LEVEL_2 = Urgency("LEVEL 2", 2)  # threshold[0]–[1] — get ready
LEVEL_3 = Urgency("LEVEL 3", 3)  # above threshold[1] — plenty of time


def time_to_leave(minutes_until):
    """Departure (minutes away) → minutes until you must LEAVE the room.
    Returns None if uncatchable (you'd miss it even leaving now)."""
    if minutes_until is None:
        return None
    ttl = minutes_until - WALK_TO_STATION_MINS
    return ttl if ttl >= 0 else None  # drop trains you've already lost


def classify(ttl):
    """PURE: time-to-leave (minutes) → Urgency. Band edges from URGENCY_THRESHOLDS;
    no colour, no rendering."""
    if ttl is None:
        return HIDDEN
    near, mid = URGENCY_THRESHOLDS
    if ttl < near:
        return LEVEL_1
    if ttl < mid:
        return LEVEL_2
    return LEVEL_3


class LeaveSignal:
    """Per-tick snapshot of when to leave. Pure data, rebuilt every tick — owns
    no state and survives nothing, so there's no staleness to manage.

    ttls    : catchable times-to-leave, soonest first (continuous, minutes)
    primary : ttls[0] or None — drives the headline display
    urgency : classify(primary) — derived convenience for colour bands
    """

    def __init__(self, ttls):
        self.ttls = ttls
        self.primary = ttls[0] if ttls else None
        self.urgency = classify(self.primary)


def next_departures(schedule, now, count=3):
    """
    Return list of up to `count` minutes-until-departure values (ints).
    Empty list means no trains remain today.
    """
    return [m - now for m in schedule if m > now][:count]


def leave_signal(departures, now):
    """Build a LeaveSignal from a direction's schedule and the current time."""
    raw = next_departures(departures, now)  # minutes-until for the next few trains
    ttls = [t for t in (time_to_leave(m) for m in raw) if t is not None]
    return LeaveSignal(ttls)
