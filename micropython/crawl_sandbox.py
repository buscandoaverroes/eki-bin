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
#   make crawl-sandbox              both, labelled, in a loop
#   Or set ACTIVE at the bottom to hops / fades.
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
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()


ACTIVE = demo   # ← swap for hops / fades, or call either from the REPL

if __name__ == "__main__":
    ACTIVE()
