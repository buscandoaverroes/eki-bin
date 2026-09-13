# micropython/motion_sandbox.py — eki-bin
#
# The five words of the light language, on real glass.
# Design: docs/contracts/light-language.md. Nothing here is wired into
# main.py — this is where the vocabulary gets decided BEFORE it ships,
# the same way led_sandbox.py designed the ACK/CONFIRM jolt shapes before
# they were written into status.py and gestures.py.
#
# ⚠ WHY THIS ISN'T A led_sandbox.py SCENE. That file's unit is
# `(start, end, color, anim_fn)` where `anim_fn(phase_ms) -> mult` — a
# FIXED span whose BRIGHTNESS varies over time. Four of the five words
# here vary their POSITION over time, which that shape cannot express at
# all. Extending it would have meant changing the tuple every existing
# scene uses, to serve a primitive with no overlap. So: a different
# primitive gets a different file, and led_sandbox.py keeps doing the
# brightness-over-time job it is good at.
#
# The primitive here is:  word(phase_ms) -> [mult] * NUM_LEDS
# painted through leds._write_frame, i.e. the REAL gamma + dither +
# _physical pipeline. What looks right here looks the same in production.
#
# ⚠ `import leds` resolves against whatever is CURRENTLY ON THE DEVICE
# (from the last `make upload`), not your local repo copy — `mpremote run`
# transfers this one file only. Same trap led_sandbox.py documents.
#
#   make motion-sandbox          — the demo: all five, in order, labelled
#   Or edit ACTIVE at the bottom and re-run.

import time

import leds
import primitives
import settings
from settings import ANCHOR_INDEX, NUM_LEDS

# ANCHOR_INDEX defaults to 0 for every non-approach contract, which would
# make `outward` radiate from one END of the strip rather than from the
# station. Fall back to the middle in that case — and PRINT it in every
# runner header, so a real anchor of 0 (legal, if unusual) is visible as a
# deliberate value rather than silently overridden.
ANCHOR = ANCHOR_INDEX or NUM_LEDS // 2

# ── Per-unit physical constants ──────────────────────────────────
# SHAKE_BOUNDS is the pair of LEDs flanking the LABEL EDGE — the "no" is
# supposed to bounce against the one boundary the vessel actually has.
# This is a per-unit fact like ARC_ORIGIN and the arm A/B orientation:
# established with the bottle in hand, recorded in that unit's registry
# entry, NOT derivable from code. The default below is a placeholder that
# is wrong for every real bottle — finding the right pair is one of the
# things this sandbox is FOR (light-language.md §3).
SHAKE_BOUNDS = (NUM_LEDS // 2 - 3, NUM_LEDS // 2 + 3)

WORD_COLOR = settings.STARTUP_COLOR   # one colour throughout, deliberately:
#   the question is whether MOTION is legible through this glass. Varying
#   hue at the same time would confound the only variable being tested.

REST_MS = 900     # dark gap between repetitions. These are EVENTS, not
#   loops — without a gap you cannot see where one begins, and "does it
#   read as a discrete thing that happened" is half the question.


# ── Easing — the skeuomorphism test lives here ───────────────────
# light-language.md §5: a loading spinner is CONSTANT angular velocity and
# indefinite duration; physical rotation DECELERATES to a definite stop.
# Same path, opposite connotation. So easing is not decoration here, it is
# the variable under test — run `ab("around")` and watch which one reads
# as a machine thinking.
#
# If the words ship, these graduate to primitives.py alongside gamma() and
# breathe(). Kept local while they are still a hypothesis.


def linear(t):
    """Constant velocity. The spinner. Included to lose."""
    return t


def ease_out(t, power=2.0):
    """Decelerate to rest — fast in, settling. power=2 is gentle, 3 is a
    hard arrival. The physical one."""
    return 1.0 - (1.0 - t) ** power


def ease_in_out(t):
    """Accelerate then decelerate. A body with mass that also had to get
    moving — worth comparing against ease_out for `around`."""
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


# ── Painters ─────────────────────────────────────────────────────


def _blob(mults, pos, width=1.4, peak=1.0, wrap=False):
    """Add a soft blob centred on a FLOAT position, linear falloff.

    Sub-LED positioning matters more than it looks: at 21 LEDs a motion
    that snaps integer-to-integer reads as a chase of discrete dots, and
    the diffusion in a thick bottle does not smooth that out — it blurs
    each dot without connecting them. Interpolating across neighbours is
    what makes it read as one thing moving."""
    lo = int(pos - width) - 1
    hi = int(pos + width) + 2
    for i in range(lo, hi):
        d = abs(i - pos)
        idx = i % NUM_LEDS if wrap else i
        if idx < 0 or idx >= NUM_LEDS or d > width:
            continue
        v = peak * (1.0 - d / width)
        if v > mults[idx]:
            mults[idx] = v


def _comet(mults, pos, tail=4.0, peak=1.0, direction=1, wrap=True):
    """A blob with a trailing decay — reads as travel with a direction,
    which a symmetric blob does not. `direction` is +1/-1 along logical
    index; the tail is always BEHIND."""
    _blob(mults, pos, width=1.2, peak=peak, wrap=wrap)
    steps = int(tail) + 1
    for k in range(1, steps + 1):
        p = pos - direction * k
        v = peak * (1.0 - k / (tail + 1.0))
        if v <= 0:
            continue
        _blob(mults, p, width=1.0, peak=v, wrap=wrap)


def _empty():
    return [0.0] * NUM_LEDS


# ── The five words ───────────────────────────────────────────────
# Every one is the same physics: impulse in, energy propagates, energy
# decays. They differ only in the boundary conditions.


def inward(phase_ms, ms=1600, ease=ease_out, width=1.6):
    """Energy CONVERGING. What trains always do — both arms travelling
    toward the anchor, because distance from the anchor IS time.

    Included in the vocabulary mainly so the other four can be judged
    against it: this is the one word the object already speaks fluently,
    so anything that clashes with it is wrong, not interesting."""
    t = min(1.0, phase_ms / ms)
    f = ease(t)
    m = _empty()
    _blob(m, 0 + (ANCHOR - 0) * f, width)
    _blob(m, (NUM_LEDS - 1) + (ANCHOR - (NUM_LEDS - 1)) * f, width)
    return m


def outward(phase_ms, ms=900, ease=ease_out, width=1.6, peak=1.0):
    """Energy RADIATING FROM THE STRIKE POINT — the ACK. "I felt that."

    Radiates from the anchor, not from the strip's centre and not from
    STATUS_LED_INDEX: the anchor is the station, and the station is what
    the object is about.

    `peak` and `ms` are BOTH meant to scale with strike force — a harder
    tap rings brighter AND faster. That is not a feature bolted on, it is
    what glass does, which is the whole argument for the metaphor. See
    force_demo() below for the A/B.

    Amplitude decays across the travel: the energy is leaving."""
    t = min(1.0, phase_ms / ms)
    f = ease(t)
    amp = peak * (1.0 - t)
    m = _empty()
    _blob(m, ANCHOR + (0 - ANCHOR) * f, width, amp)
    _blob(m, ANCHOR + ((NUM_LEDS - 1) - ANCHOR) * f, width, amp)
    return m


def around(phase_ms, ms=1400, ease=ease_out, tail=4.0, laps=1.0):
    """Energy travelling the CIRCUMFERENCE, decelerating to rest — the
    transition. A station change, a line change: something arriving.

    ⚠ THE ONE TO TEST FIRST. `ease=linear` is a loading spinner and
    should feel like a machine waiting; `ease=ease_out` is a roulette
    wheel and should feel like an object moving. If that difference does
    NOT survive this glass, the whole deceleration rule (§5) is wrong and
    the doc needs correcting, not the code.

    Open, and this sandbox is how it gets answered: should `around` always
    travel the same way (legible as a signal) or take the shorter way to
    its destination (more physical)? light-language.md §8."""
    t = min(1.0, phase_ms / ms)
    f = ease(t)
    m = _empty()
    _comet(m, (f * laps * NUM_LEDS) % NUM_LEDS, tail=tail, direction=1)
    return m


def shake(phase_ms, ms=650, bounces=3, width=1.2, bounds=None):
    """Energy REFLECTING off a boundary and going nowhere — the "no".

    Bounces between the two LEDs flanking the label edge (SHAKE_BOUNDS).
    Motion that fails to complete is a better negative than a colour,
    because nobody has to have learned it first — it works the first time
    someone sees it.

    Amplitude decays over the bounces: the energy dissipates without
    having gone anywhere, which is exactly the message."""
    a, b = bounds or SHAKE_BOUNDS
    t = min(1.0, phase_ms / ms)
    u = (t * bounces) % 1.0
    tri = 2.0 * u if u < 0.5 else 2.0 * (1.0 - u)
    m = _empty()
    _blob(m, a + (b - a) * tri, width, peak=1.0 - t)
    return m


def breathe(phase_ms, ms=4000, floor=0.35):
    """Energy SUSTAINED, not decaying — which is precisely why it reads as
    unresolved, and why it is the error verb.

    ⚠ Don't spend this word on anything that should feel finished. It is
    the only one of the five whose energy never leaves."""
    v = primitives.breathe(phase_ms, ms, floor)
    return [v] * NUM_LEDS


# ── What to run ──────────────────────────────────────────────────
# (word fn, kwargs, total ms). Duration is per REPETITION, not per session.

WORDS = {
    "inward":        (inward, {}, 1600),
    "outward":       (outward, {}, 900),
    "around":        (around, {}, 1400),
    "around_linear": (around, {"ease": linear}, 1400),
    "around_inout":  (around, {"ease": ease_in_out}, 1400),
    "shake":         (shake, {}, 650),
    "breathe":       (breathe, {}, 4000),
}

# ⚠ These live here rather than being read off fn.__doc__, which is what
# this file did until it hit hardware: **MicroPython compiles docstrings
# away** unless the firmware was built with MICROPY_ENABLE_DOC_STRING, so
# `fn.__doc__` is not an empty string, the attribute does not exist at all
# — AttributeError at the first demo() label. The host suite cannot catch
# this class: pytest runs CPython, where __doc__ always exists. Anything
# read off a function object at runtime needs this treatment.
BLURB = {
    "inward":        "energy converging — what trains always do",
    "outward":       "energy radiating from the strike point — the ACK",
    "around":        "energy travelling the circumference — a transition",
    "around_linear": "...at constant velocity — the spinner, included to lose",
    "around_inout":  "...accelerating then decelerating — a body with mass",
    "shake":         "energy reflecting off a boundary, going nowhere — 'no'",
    "breathe":       "energy sustained, not decaying — unresolved",
}

DEMO_ORDER = ("outward", "inward", "around", "shake", "breathe")


def _header(title):
    print("\n== motion_sandbox: %s ==" % title)
    print("   NUM_LEDS=%d  ANCHOR=%d  SHAKE_BOUNDS=%s  BRIGHTNESS=%.2f"
          % (NUM_LEDS, ANCHOR, SHAKE_BOUNDS, settings.BRIGHTNESS))


def _play(fn, kwargs, ms, color=WORD_COLOR):
    """One repetition, then dark for REST_MS."""
    start = time.ticks_ms()
    while True:
        phase = time.ticks_diff(time.ticks_ms(), start)
        if phase >= ms:
            break
        mults = fn(phase, **kwargs)
        leds._write_frame(
            [(color, v) if v > 0.001 else None for v in mults]
        )
        time.sleep_ms(20)
    leds.clear()
    time.sleep_ms(REST_MS)


def run(name, repeats=None):
    """Repeat one word until Ctrl+C (or `repeats` times)."""
    fn, kwargs, ms = WORDS[name]
    _header(repr(name))
    print("   %d ms per repetition, %d ms dark between. Ctrl+C to stop.\n"
          % (ms, REST_MS))
    n = 0
    try:
        while repeats is None or n < repeats:
            _play(fn, kwargs, ms)
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


def ab(name="around", repeats=None):
    """THE deceleration test (light-language.md §5).

    Alternates eased and linear, announcing each BEFORE it plays so you
    can watch rather than read. Deliberately TEMPORAL A/B, not the
    left-half/right-half comparison led_sandbox.py uses for colour: these
    words travel the whole ring, and cutting the ring in half to compare
    them would destroy the circularity being tested."""
    fn, kwargs, ms = WORDS[name]
    variants = (("eased  (physical)", dict(kwargs, ease=ease_out)),
                ("linear (spinner) ", dict(kwargs, ease=linear)))
    _header("A/B %s" % name)
    print("   Which one reads as a machine waiting? Ctrl+C to stop.\n")
    n = 0
    try:
        while repeats is None or n < repeats:
            label, kw = variants[n % 2]
            print("   %s" % label)
            _play(fn, kw, ms)
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


def force_demo(repeats=None):
    """Is strike force legible through this glass, or does diffusion
    flatten it? (light-language.md §7 item 3.)

    Plays `outward` at three strengths. Both brightness AND speed scale,
    because that is the claim being tested — if only one of them survives
    the glass, that is worth knowing before _handle_tap is rewired to
    _tap_strength()."""
    levels = ((0.35, 1400, "light"), (0.65, 1100, "medium"), (1.0, 800, "hard"))
    _header("outward ∝ strike force")
    print("   brightness AND speed both scale. Ctrl+C to stop.\n")
    n = 0
    try:
        while repeats is None or n < repeats:
            peak, ms, label = levels[n % 3]
            print("   %-6s  peak=%.2f  %dms" % (label, peak, ms))
            _play(outward, {"peak": peak, "ms": ms}, ms)
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


def demo(repeats=None):
    """All five, in order, labelled — light-language.md §7 item 2.

    The question this answers is NOT "is each one nice". It is: are they
    DISTINGUISHABLE from each other through this glass, or does diffusion
    collapse them into one blur of moving light? A vocabulary whose words
    are not distinguishable is not a vocabulary."""
    _header("the five words")
    print("   Distinguishable through this glass? Ctrl+C to stop.\n")
    n = 0
    try:
        while repeats is None or n < repeats:
            for name in DEMO_ORDER:
                fn, kwargs, ms = WORDS[name]
                print("   %-8s %s" % (name, BLURB.get(name, "")))
                _play(fn, kwargs, ms)
            print("")
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        leds.clear()
        print("  cleared — bye")


ACTIVE = ab   # ← swap for run/ab/force_demo, or call them from the REPL

if __name__ == "__main__":
    ACTIVE()
