# micropython/horizon.py — eki-bin
#
# "There IS a train, it is just further out than the strip can show."
# insights.md §17.
#
# ⚠ THIS MODULE EXISTS BECAUSE OF A SEAM, not because of a bug in either
# side of it. Every piece was individually correct:
#
#   _arm_target()          returns None past the arm — and should. An
#                          approach contract genuinely cannot show a train
#                          further out than the strip reaches.
#   LeaveSignal.urgency    is LEVEL_3, not HIDDEN — and should be. Those
#                          are real, catchable trains.
#   _all_signals_hidden()  is therefore False, so the no-data ack never
#                          fires.
#
# Result: at 00:29 with the next train 305 minutes out, the strip shows an
# anchor and its markers and nothing else — mathematically perfect, and
# indistinguishable from a broken jar.
#
# The gap is that STAGE 1 DOES NOT KNOW STAGE 2's REACH. That reach is not
# hidden or hard: it is ARM_LEN × POSITION_MINUTES_PER_LED, two settings
# already in config. This module is stage 1 asking stage 2 how far it can
# see — the one question the two-stage split never gave it a way to ask.

import math

from settings import (ARM_A_LEN, ARM_B_LEN, CONTRACT_NAME, MINUTES_PER_LED,
    NUM_LEDS, POSITION_MINUTES_PER_LED)
from signals import HIDDEN


def horizon_minutes():
    """PURE: the largest time-to-leave this display can render.

    Derived from the SAME arithmetic the renderer uses, not a parallel
    estimate — `_position_offset` is `ceil(ttl / POSITION_MINUTES_PER_LED)`
    and `_arm_target` drops it when it exceeds the arm, so an arm of N LEDs
    reaches exactly N × POSITION_MINUTES_PER_LED minutes. Re-deriving it
    any other way would let the two drift apart silently."""
    if CONTRACT_NAME == "approach":
        return max(ARM_A_LEN, ARM_B_LEN) * POSITION_MINUTES_PER_LED
    return NUM_LEDS * MINUTES_PER_LED


def beyond_horizon(*signals):
    """PURE: True when there ARE trains and every one is out of reach.

    Deliberately distinct from HIDDEN. "Come back tomorrow" and "you have
    missed the last train" are different facts, and a jar that cannot tell
    them apart is a jar that says the same thing at 00:30 and at 23:59
    after the last service."""
    h = horizon_minutes()
    any_train = False
    for sig in signals:
        if sig is None or sig.urgency is HIDDEN:
            continue
        for ttl in sig.ttls:
            any_train = True
            if ttl <= h:
                return False        # at least one is showable
    return any_train


def minutes_until_visible(*signals):
    """PURE: minutes until the soonest train crosses INTO the horizon, or
    None if one is already visible (or there are none at all).

    This is the whole of the "good morning" feature. **The flower does not
    need to be animated** — a train crossing the horizon lights an arm's
    outermost LED and works inward, which is the existing renderer doing
    its ordinary job. Nobody has ever seen it because the display is
    asleep by then. So the question is not what to draw, it is when to be
    awake, and that is this number."""
    h = horizon_minutes()
    soonest = None
    for sig in signals:
        if sig is None or sig.urgency is HIDDEN:
            continue
        for ttl in sig.ttls:
            if ttl <= h:
                return None         # already showable
            if soonest is None or ttl < soonest:
                soonest = ttl
    if soonest is None:
        return None
    return int(math.ceil(soonest - h))
