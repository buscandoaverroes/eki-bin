# micropython/motion.py — eki-bin
#
# The five words of the light language. Design: light-language.md §3.
# Bench findings that set every constant: insights.md §15.
#
# One implementation, like tilt.py: motion_sandbox.py drives these for
# comparison and gestures.py/main.py drive them for real.
#
# THE PREMISE, because it explains every choice below: a glass bottle
# already answers a tap — it rings, and the ring decays. So the LEDs are
# not a new interaction, they are an augmentation of one every person who
# will ever hold this already knows. Every word here is that same physics
# under a different boundary condition:
#
#     impulse in  →  energy propagates  →  energy decays
#
# A resonance, not a notification. A struck bell doesn't blink.
#
# ⚠ MOTION, NOT MORE COLOUR, and that is measured rather than aesthetic.
# Of the four expressive channels, three are already spent: position
# carries time-to-leave, hue carries line identity — and §12 found thick
# brown glass supports only 2-3 hues AT ALL — and brightness carries
# urgency, anchor, marker and now day/night. Motion is the one left. It
# also survives the enclosure best: thick glass blurs position and filters
# hue, but change-over-time passes through diffusion intact.

import time

import leds
import primitives
from settings import (MOTION_AROUND_MS, MOTION_INWARD_MS, MOTION_OUTWARD_MS,
    MOTION_SHAKE_BOUNCES, MOTION_SHAKE_MS, NUM_LEDS, SHAKE_BOUNDS)

# ANCHOR_INDEX defaults to 0 for every non-approach contract, which would
# make `outward` radiate from one END of the strip rather than from the
# station. Fall back to the middle there — the strike point should be the
# thing the object is about.
from settings import ANCHOR_INDEX
ANCHOR = ANCHOR_INDEX or NUM_LEDS // 2


def ease_out(t, power=2.0):
    """Decelerate to rest — the difference between an object and a spinner.

    light-language.md §5: a loading spinner runs at CONSTANT angular
    velocity for an INDEFINITE duration; physical rotation decelerates and
    stops somewhere specific. Same path, opposite connotation, and easing
    plus a definite end is the whole of it. This is why no word here runs
    at constant velocity."""
    return 1.0 - (1.0 - t) ** power


def _blob(mults, pos, width=1.4, peak=1.0, wrap=False):
    """Add a soft blob at a FLOAT position, linear falloff.

    Sub-LED positioning is not polish: at 21 LEDs a motion that snaps
    integer-to-integer reads as a chase of discrete dots, and thick glass
    blurs each dot WITHOUT connecting them — so the enclosure cannot fix
    it later."""
    for i in range(int(pos - width) - 1, int(pos + width) + 2):
        d = abs(i - pos)
        idx = i % NUM_LEDS if wrap else i
        if idx < 0 or idx >= NUM_LEDS or d > width:
            continue
        v = peak * (1.0 - d / width)
        if v > mults[idx]:
            mults[idx] = v


def _comet(mults, pos, tail=4.0, peak=1.0, direction=1):
    """A blob with a trailing decay — reads as travel WITH A DIRECTION,
    which a symmetric blob does not."""
    _blob(mults, pos, width=1.2, peak=peak, wrap=True)
    for k in range(1, int(tail) + 2):
        v = peak * (1.0 - k / (tail + 1.0))
        if v > 0:
            _blob(mults, pos - direction * k, width=1.0, peak=v, wrap=True)


def _empty():
    return [0.0] * NUM_LEDS


# ── The words ────────────────────────────────────────────────────


def inward(phase_ms, ms=None, width=1.6):
    """Energy CONVERGING — what trains always do. Both arms travel toward
    the anchor, because distance from the anchor IS time."""
    ms = ms or MOTION_INWARD_MS
    f = ease_out(min(1.0, phase_ms / ms))
    m = _empty()
    _blob(m, 0 + (ANCHOR - 0) * f, width)
    _blob(m, (NUM_LEDS - 1) + (ANCHOR - (NUM_LEDS - 1)) * f, width)
    return m


def outward(phase_ms, ms=None, width=1.6, peak=1.0):
    """Energy RADIATING FROM THE STRIKE POINT — "I felt that".

    Radiates from the ANCHOR, not the strip's centre: the anchor is the
    station, and the station is what the object is about.

    `peak` and `ms` both scale with strike force — a harder tap rings
    brighter AND faster — which is not a feature bolted on, it is what
    glass does. Amplitude decays across the travel: the energy is leaving."""
    ms = ms or MOTION_OUTWARD_MS
    t = min(1.0, phase_ms / ms)
    f = ease_out(t)
    amp = peak * (1.0 - t)
    m = _empty()
    _blob(m, ANCHOR + (0 - ANCHOR) * f, width, amp)
    _blob(m, ANCHOR + ((NUM_LEDS - 1) - ANCHOR) * f, width, amp)
    return m


def around(phase_ms, ms=None, tail=4.0, laps=1.0):
    """Energy travelling the CIRCUMFERENCE, decelerating to rest — the
    transition. Not an announcement that something is about to change: the
    motion IS the change arriving."""
    ms = ms or MOTION_AROUND_MS
    f = ease_out(min(1.0, phase_ms / ms))
    m = _empty()
    _comet(m, (f * laps * NUM_LEDS) % NUM_LEDS, tail=tail, direction=1)
    return m


def shake(phase_ms, ms=None, bounces=None, width=1.2):
    """Energy REFLECTING off a boundary and going nowhere — the "no".

    Bounces between the two LEDs flanking the label edge. Motion that
    fails to complete is a better negative than a colour, because nobody
    has to have learned it first — it works the first time someone sees
    it. Amplitude decays over the bounces: energy dissipating without
    having gone anywhere, which is exactly the message.

    ⚠ WIDTH IS LOAD-BEARING, measured 2026-09-14: at ±5 LEDs this reads as
    a short lap of `around` and the two words stop being distinguishable.
    ±3 is a head-shake. See SHAKE_HALF_WIDTH — it is a property of the
    vocabulary, not a per-bottle preference."""
    ms = ms or MOTION_SHAKE_MS
    bounces = bounces or MOTION_SHAKE_BOUNCES
    a, b = SHAKE_BOUNDS
    t = min(1.0, phase_ms / ms)
    u = (t * bounces) % 1.0
    tri = 2.0 * u if u < 0.5 else 2.0 * (1.0 - u)
    m = _empty()
    _blob(m, a + (b - a) * tri, width, peak=1.0 - t)
    return m


def breathe(phase_ms, ms=4000, floor=0.35):
    """Energy SUSTAINED, not decaying — which is precisely why it reads as
    unresolved, and why it is the error verb.

    ⚠ Don't spend this word on anything that should feel FINISHED. It is
    the only one of the five whose energy never leaves."""
    return [primitives.breathe(phase_ms, ms, floor)] * NUM_LEDS


WORDS = {"inward": inward, "outward": outward, "around": around,
         "shake": shake, "breathe": breathe}


def slow_out(t):
    """The station's curve, chosen on glass 2026-09-14 (insights §19).

    Lingers near the top and leaves quickly at the end. For a fade-OUT
    that is a station holding on rather than a dimmer being turned down —
    which is the whole difference between an object settling and a switch
    being thrown.

    ⚠ Already perceptually shaped. The animated path applies gamma, so
    output ∝ mult**2.2 and perception ∝ mult — a LINEAR mult ramp is
    perceptually even, and this deliberately bends away from even."""
    return t ** 0.55


def fade(color, ms, index=None, rising=False, curve=None, frame_ms=16):
    """Fade ONE LED — by default the station — in or out. BLOCKING.

    Animated path (a 2-tuple, not "static"), which is gamma-corrected and
    dithered. **Both matter here**: gamma is what makes the ramp
    perceptually even, and dithering is what keeps it from stepping at the
    bottom, where there are few output codes left. If this looks like a
    staircase on hardware, DITHER is off."""
    index = ANCHOR if index is None else index
    curve = slow_out if curve is None else curve
    start = time.ticks_ms()
    while True:
        phase = time.ticks_diff(time.ticks_ms(), start)
        if phase >= ms:
            break
        t = phase / ms
        v = curve(t if rising else 1.0 - t)
        frame = [None] * NUM_LEDS
        if v > 0.001:
            frame[index] = (color, min(1.0, max(0.0, v)))
        leds._write_frame(frame)
        time.sleep_ms(frame_ms)
    leds.clear()


def recoil(color, ms=140, depth=0.35, frame_ms=15):
    """A brief dip and return, whole strip. **NOT a sixth word.**

    Words say something. This is a physical reaction — the same category
    as the ACK flash, which is also not a word. A bottle tilted past what
    the table allows does not communicate; it stops, and you feel it stop.

    ⚠ Deliberately a BRIGHTNESS dip and not a positional bounce, which was
    the first instinct. At a brightness rail the whole ring is lit, so a
    blob moving a couple of LEDs is invisible against it — whereas the
    object recoiling reads at any lit state. The physical metaphor agrees:
    the thing that bounces is the bottle, not a spot on it."""
    start = time.ticks_ms()
    while True:
        phase = time.ticks_diff(time.ticks_ms(), start)
        if phase >= ms:
            break
        t = phase / ms
        # down fast, back up slower — a bounce is asymmetric
        mult = (1.0 - depth * (t / 0.3) if t < 0.3
                else 1.0 - depth * (1.0 - (t - 0.3) / 0.7))
        leds._write_frame([(color, max(0.0, min(1.0, mult)))] * NUM_LEDS)
        time.sleep_ms(frame_ms)
    leds.clear()


def play_sequence(waves, word="outward", gap_ms=0, frame_ms=20):
    """Play several waves back to back. Each is (color, ms, peak).

    Exists because one wave is a gesture and three are a CEREMONY — the
    difference is not decoration. A single `outward` is an ACK; the same
    word three times, each slower and dimmer, is a thing ending. Duration
    and decay carry that on their own, which matters in a vessel that
    filters hue (insights.md §12): the colour drift is the part a clear
    bottle gets and an opaque brown one mostly does not, so it is never
    the only thing saying it."""
    for color, ms, peak in waves:
        play(word, color, ms, frame_ms=frame_ms, peak=peak)
        if gap_ms:
            time.sleep_ms(gap_ms)


def play(word, color, ms, frame_ms=20, **kwargs):
    """Run one word to completion, then clear. BLOCKING.

    Blocking is right here and not a shortcut: these are responses to a
    gesture, and the loop has just spent ~1.2s in a capture window anyway
    — the same reason _play_confirm_jolt blocks. Nothing else needs to
    render while the object is answering you."""
    fn = WORDS[word] if isinstance(word, str) else word
    start = time.ticks_ms()
    while True:
        phase = time.ticks_diff(time.ticks_ms(), start)
        if phase >= ms:
            break
        mults = fn(phase, ms=ms, **kwargs)
        leds._write_frame([(color, v) if v > 0.001 else None for v in mults])
        time.sleep_ms(frame_ms)
    leds.clear()
