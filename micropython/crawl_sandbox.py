# micropython/crawl_sandbox.py — eki-bin
#
# How does a train MOVE, and how does the station ARRIVE and LEAVE?
#
# These are the two animations the light language never specified, and the
# reason it didn't is interesting: every other word was derived from what
# glass does when you strike it (light-language.md §1). **There is no
# bottle-equivalent for a light moving inside glass.** Nothing in the
# physical object tells you whether that light is a thing with mass or a
# thing with intent.
#
# So this is the one place the metaphor does not decide for us, and the
# fork is real:
#
#   PHYSICS   — the light has mass. It slides, it eases, it settles. A
#               consistent extension of everything already built.
#   AGENCY    — the light is alive. It hops, it blinks, it vanishes and
#               reappears somewhere else. A firefly in a jar.
#
# Those are different objects, not different settings, and no amount of
# reasoning picks between them — which is why this file exists rather than
# a design doc. Run it, and see which one the bottle wants to be.
#
#   make crawl-sandbox              the full scene arriving and leaving
#   Or set ACTIVE at the bottom to demo / hops / fades.
#
# THREE QUESTIONS, and they are separable on purpose:
#   fades()     one LED, in and out — the CURVE, isolated
#   hops()      a train crawling an arm — the HANDOFF, isolated
#   arrivals()  station AND trains together — the SEQUENCING, which is the
#               one that actually happens after a tap and at timeout
#
# ⚠ Everything renders through leds._write_frame on the ANIMATED path
# (a 2-tuple, not "static"), which is gamma-corrected AND dithered. That is
# deliberate and it is half the experiment: DITHER exists precisely to make
# a low-brightness fade smooth instead of stepped, and the static/animated
# split means turning it on costs the idle LEDs nothing. If a fade below
# looks like a staircase, check DITHER before blaming the curve.

import time

import leds
import settings
from settings import ANCHOR_COLOR, ANCHOR_INDEX, LINE_COLOR, NUM_LEDS

ANCHOR = ANCHOR_INDEX or NUM_LEDS // 2
REST_MS = 700          # dark gap between demonstrations
STEP_MS = 900          # time for ONE hop, outer LED → next LED inward
FADE_MS = 3000         # a full station fade. Long on purpose — see fades()


def _empty():
    return [0.0] * NUM_LEDS


def _clamp(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


# ── HOW A TRAIN MOVES ────────────────────────────────────────────
# Each takes t in 0..1 for one step and returns (mult_at_old, mult_at_new).
# Keeping them to that signature is what makes them comparable: every
# style moves the same distance in the same time, so the only variable is
# the SHAPE of the handoff.


def cut(t):
    """Instant switch at the midpoint. The baseline — what "blink over"
    looks like, and the thing to beat."""
    return (0.0, 1.0) if t >= 0.5 else (1.0, 0.0)


def crossfade(t):
    """PHYSICS. One dims as the other brightens — a thing sliding between
    two positions, seen through glass that blurs the gap."""
    return (1.0 - t, t)


def ease_slide(t):
    """PHYSICS, with mass. Same crossfade, decelerating into the new
    position — it arrives rather than crosses."""
    e = 1.0 - (1.0 - t) ** 2
    return (1.0 - e, e)


def blink_hop(t):
    """AGENCY, and the one that was asked for: a quick 1-2 blink at the
    old position, then it is simply somewhere else.

    The blink is what makes it read as a decision rather than a slide —
    something gathering itself before it goes."""
    if t < 0.16:
        return (1.0, 0.0)
    if t < 0.26:
        return (0.15, 0.0)     # blink 1
    if t < 0.40:
        return (1.0, 0.0)
    if t < 0.50:
        return (0.15, 0.0)     # blink 2
    if t < 0.62:
        return (1.0, 0.0)
    return (0.0, 1.0)          # gone — and there


def arc_hop(t):
    """AGENCY with physics underneath: it leaves, is briefly BRIGHTER in
    transit (a thing passing close to you), and lands with a small
    overshoot. A hop has an apex."""
    if t < 0.45:
        u = t / 0.45
        return (1.0 - u, 0.35 * u)          # leaving, the new one glowing
    u = (t - 0.45) / 0.55
    land = 1.0 + 0.45 * (1.0 - u) if u < 0.4 else 1.0
    return (0.0, _clamp(0.35 + 0.65 * u) * land)


def firefly(t):
    """AGENCY, fully. It goes OUT, there is a real gap of nothing, and
    then it is alight somewhere else.

    ⚠ The gap is the whole idea and also the risk: for a fraction of a
    second the display says nothing at all, which is the one thing a
    clock is not supposed to do. Watch whether that reads as alive or as
    broken — that is the question this style exists to answer."""
    if t < 0.30:
        return (1.0 - t / 0.30, 0.0)
    if t < 0.58:
        return (0.0, 0.0)                   # the gap
    u = (t - 0.58) / 0.42
    return (0.0, u * u)                     # comes up from nothing


HOPS = (("cut          (baseline)", cut),
        ("crossfade    (physics)", crossfade),
        ("ease_slide   (physics, mass)", ease_slide),
        ("blink_hop    (agency)", blink_hop),
        ("arc_hop      (agency + apex)", arc_hop),
        ("firefly      (agency, with a gap)", firefly))


# ── HOW THE STATION ARRIVES AND LEAVES ───────────────────────────
# Each takes t in 0..1 and returns a mult. Used forwards to fade in and
# backwards to fade out, so a style that feels right in one direction can
# be checked in the other — they are not always the same.


def linear(t):
    """Perceptually linear ALREADY, which is the non-obvious part: the
    animated path applies gamma, so output ∝ mult**2.2 and perception ∝
    output**(1/2.2) ∝ mult. Ramping mult linearly is the correct default,
    not the naive one."""
    return t


def slow_out(t):
    """Lingers at the top, leaves quickly. For a fade-OUT this is a
    station that holds on."""
    return t ** 0.55


def slow_in(t):
    """Creeps up from nothing, then arrives. For a fade-IN this is a
    station resolving out of the dark."""
    return t ** 2.2


def breath(t):
    """Not monotonic: rises, dips slightly, settles. A thing catching its
    breath rather than a dimmer being turned."""
    base = 1.0 - (1.0 - t) ** 2
    if 0.55 < t < 0.85:
        base -= 0.12 * (1.0 - abs(t - 0.70) / 0.15)
    return _clamp(base)


def flicker_settle(t):
    """AGENCY again — it gutters on the way, like something lighting.
    The counterpart to firefly() above: if one of them feels right, the
    other probably does too, and the object has a personality."""
    base = 1.0 - (1.0 - t) ** 1.6
    if t < 0.5:
        for at in (0.14, 0.27, 0.41):
            if abs(t - at) < 0.022:
                return _clamp(base * 0.3)
    return _clamp(base)


FADES = (("linear       (perceptually even)", linear),
         ("slow_out     (holds on)", slow_out),
         ("slow_in      (resolves out of the dark)", slow_in),
         ("breath       (settles)", breath),
         ("flicker_settle (agency)", flicker_settle))


# ── HOW THE WHOLE SCENE ARRIVES AND LEAVES ───────────────────────
# The fades above test ONE LED. This tests the composite, which is a
# different question and the one that actually happens: after a tap the
# station AND every train have to appear, and at timeout they all have to
# go. Whether they move together or in sequence changes what the object
# seems to be doing.
#
# ⚠ NEITHER HALF IS IMPLEMENTED YET. A wake currently snaps the display on
# after the `outward` wave, and the sleep unwind fades only the station —
# the trains just vanish. So this is designing both, not tuning one.
#
# Each spec is (label, station_curve, train_curve, stagger_ms, order).
# `order` decides what the trains do among THEMSELVES:
#
#   together    neutral; says nothing
#   far_first   the world fills in from the horizon inward — the same
#               direction the approach paradigm already means by `inward`
#   near_first  the most urgent thing resolves first, then context
#
# Direction is handled automatically and is NOT symmetric: arriving, the
# station leads and the trains follow; leaving, the trains go first and the
# station is last to let go. That ordering was already chosen on hardware —
# this is about the timing and the curves inside it.

ARRIVALS = (
    ("together        (baseline)", linear, linear, 0, "together"),
    ("station leads   (1.0s, together)", slow_out, slow_out, 1000, "together"),
    ("far first       (1.0s, horizon inward)", slow_out, slow_out, 1000, "far_first"),
    ("near first      (1.0s, urgent first)", slow_out, slow_out, 1000, "near_first"),
    ("slow bloom      (1.6s, far first, slow_in trains)", slow_out, slow_in, 1600, "far_first"),
)

SCENE_OFFSETS = (3, 7)     # train distances from the anchor, both arms
SCENE_HOLD_MS = 1500       # lit, between the fade in and the fade out


def _scene_trains():
    """(index, rank) for each train — rank 0 is nearest the anchor.

    Both arms, because a one-armed scene cannot show whether a stagger
    reads as symmetric or as a sweep across the strip."""
    out = []
    for rank, off in enumerate(SCENE_OFFSETS):
        for idx in (ANCHOR + off, ANCHOR - off):
            if 0 <= idx < NUM_LEDS:
                out.append((idx, rank))
    return out


def _delays(spec, rising, trains, total_ms):
    """When each element starts, in ms. The whole design is in here."""
    _lbl, _sc, _tc, stagger, order = spec
    n_ranks = max((r for _i, r in trains), default=0) + 1
    sub = stagger // 2 if order != "together" else 0
    station = 0 if rising else stagger + sub * max(0, n_ranks - 1)
    delays = {}
    for idx, rank in trains:
        if order == "far_first":
            k = (n_ranks - 1 - rank)
        elif order == "near_first":
            k = rank
        else:
            k = 0
        # Reverse the RANK order on the way out too: whatever arrived
        # first should not also leave first, or the scene pivots around
        # one end instead of dispersing.
        if not rising:
            k = (n_ranks - 1 - k) if order != "together" else 0
        delays[idx] = (stagger + sub * k) if rising else (sub * k)
    return station, delays


def _local_t(elapsed, delay, span):
    return _clamp((elapsed - delay) / span) if span > 0 else 1.0


def arrivals(repeats=None):
    """The full sequence: fade in, hold, fade out — once per spec.

    Watch the OUT half as carefully as the IN half. A stagger that feels
    considered on arrival can feel like the display falling over on the
    way out, because the same order means something different when things
    are disappearing."""
    _header("how the whole scene arrives and leaves")
    print("   station + %d trains. Ctrl+C to stop.\n" % len(_scene_trains()))
    trains = _scene_trains()
    n = 0
    try:
        while repeats is None or n < repeats:
            for spec in ARRIVALS:
                label, st_curve, tr_curve, stagger, _order = spec
                print("   %s" % label)
                for rising in (True, False):
                    st_delay, delays = _delays(spec, rising, trains, FADE_MS)
                    span = FADE_MS
                    total = span + max([st_delay] + list(delays.values()))
                    start = time.ticks_ms()
                    while True:
                        el = time.ticks_diff(time.ticks_ms(), start)
                        if el >= total:
                            break
                        frame = [None] * NUM_LEDS
                        sv = st_curve(_local_t(el, st_delay, span)
                                      if rising else
                                      1.0 - _local_t(el, st_delay, span))
                        if sv > 0.001:
                            frame[ANCHOR] = (ANCHOR_COLOR, _clamp(sv))
                        for idx, _rank in trains:
                            lt = _local_t(el, delays[idx], span)
                            tv = tr_curve(lt if rising else 1.0 - lt)
                            if tv > 0.001:
                                frame[idx] = (LINE_COLOR, _clamp(tv))
                        leds._write_frame(frame)
                        time.sleep_ms(16)
                    if rising:
                        time.sleep_ms(SCENE_HOLD_MS)
                leds.clear()
                time.sleep_ms(REST_MS)
            print("")
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


# ── Runners ──────────────────────────────────────────────────────


def _paint(mults, color=LINE_COLOR, anchor_on=True):
    frame = [(color, v) if v > 0.001 else None for v in mults]
    if anchor_on:
        frame[ANCHOR] = (ANCHOR_COLOR, 1.0)   # animated path — see header
    leds._write_frame(frame)


def _header(title):
    print("\n== crawl_sandbox: %s ==" % title)
    print("   NUM_LEDS=%d  ANCHOR=%d  BRIGHTNESS=%.2f  DITHER=%s"
          % (NUM_LEDS, ANCHOR, settings.BRIGHTNESS, settings.DITHER))
    print("   ⚠ If a fade looks like a staircase, try DITHER = True first.")


def hops(repeats=None):
    """A train crawling from the outer end of arm A in to the station,
    once per style. The arm, not a single step: how a hop reads depends on
    seeing several in a row — one in isolation always looks fine."""
    _header("how a train moves")
    print("   Ctrl+C to stop.\n")
    n = 0
    try:
        while repeats is None or n < repeats:
            for label, fn in HOPS:
                print("   %s" % label)
                for pos in range(NUM_LEDS - 1, ANCHOR, -1):
                    start = time.ticks_ms()
                    while True:
                        ph = time.ticks_diff(time.ticks_ms(), start)
                        if ph >= STEP_MS:
                            break
                        old_m, new_m = fn(ph / STEP_MS)
                        m = _empty()
                        m[pos] = _clamp(old_m)
                        m[pos - 1] = max(m[pos - 1], _clamp(new_m))
                        _paint(m)
                        time.sleep_ms(16)
                leds.clear()
                time.sleep_ms(REST_MS)
            print("")
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


def fades(repeats=None):
    """The station alone, fading in and then out, once per style.

    Deliberately the ANCHOR by itself: it is the one LED that is supposed
    to be permanent, so how it arrives and leaves sets whether the object
    reads as switching on or as waking up."""
    _header("how the station arrives and leaves")
    print("   %dms each way. Ctrl+C to stop.\n" % FADE_MS)
    n = 0
    try:
        while repeats is None or n < repeats:
            for label, fn in FADES:
                print("   %s" % label)
                for direction in (1, -1):
                    start = time.ticks_ms()
                    while True:
                        ph = time.ticks_diff(time.ticks_ms(), start)
                        if ph >= FADE_MS:
                            break
                        t = ph / FADE_MS
                        v = fn(t if direction > 0 else 1.0 - t)
                        m = _empty()
                        m[ANCHOR] = _clamp(v)
                        _paint(m, color=ANCHOR_COLOR, anchor_on=False)
                        time.sleep_ms(16)
                    time.sleep_ms(400)
                leds.clear()
                time.sleep_ms(REST_MS)
            print("")
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


def demo(repeats=None):
    n = 0
    try:
        while repeats is None or n < repeats:
            fades(repeats=1)
            hops(repeats=1)
            arrivals(repeats=1)
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()


ACTIVE = arrivals   # ← or demo / hops / fades, or call from the REPL

if __name__ == "__main__":
    ACTIVE()
