# main.py — eki-bin, V1
# MicroPython on Raspberry Pi Pico 2W
# Reads schedule from schedule.json on device filesystem.
# See docs/contracts/schedule-json.md, config.md, display-contract.md
#
# Display architecture (Step 2):
#   time → LeaveSignal (abstract snapshot) → DisplayContract (renderer) → LEDs
# "What's the urgency?" is computed once per tick and is independent of "how do
# we show it?" — swap visual strategies by changing CONTRACT in config.py.

import json
import math
import time

import config
import network
import ntptime
from machine import Pin
from neopixel import NeoPixel

# ─────────────────────────────────────────────────────────────
# Settings (from config.py)
# ─────────────────────────────────────────────────────────────
# WiFi creds are *required* for V1 — import directly so a missing value fails
# loudly rather than silently defaulting to nonsense.
WIFI_SSID = config.WIFI_SSID
WIFI_PASS = config.WIFI_PASS

# Everything else is optional with a default. getattr(config, "NAME", default)
# returns the default when the field is absent, so a config.py written before a
# knob existed keeps working — you only add the lines you want to override.
UTC_OFFSET_HOURS = getattr(config, "UTC_OFFSET_HOURS", 9)
LOOP_INTERVAL_SECS = getattr(config, "LOOP_INTERVAL_SECS", 30)
SCHEDULE_FILE = getattr(config, "SCHEDULE_FILE", "schedule.json")

# Which trains
DISPLAY_DIRECTION = getattr(config, "DISPLAY_DIRECTION", "b")
DISPLAY_DIRECTION_B = getattr(config, "DISPLAY_DIRECTION_B", None)  # phase 2 —
#   bidirectional ApproachContract only. Set to a SECOND schedule.json
#   direction key (DISPLAY_DIRECTION feeds arm "a", this feeds arm "b") to show
#   one train per arm. None (default) = single-direction, phase 1 unchanged.
#   Ignored entirely by every other contract (see render_for_interval()).
WALK_TO_STATION_MINS = getattr(config, "WALK_TO_STATION_MINS", 2.5)
# [→ NFC] WALK could later be read from the station card, not config.

# Display — hardware (changes with the physical strip: stick=8, ring=12)
LED_PIN = getattr(config, "LED_PIN", 6)
NUM_LEDS = getattr(config, "NUM_LEDS", 8)
ARC_ORIGIN = getattr(config, "ARC_ORIGIN", "near")  # "near" = DIN end (index 0) is
#   the arc origin; "far" = the other end. Logical, not physical — flip this when
#   the strip ends up mounted upside-down, without touching any rendering code.

# Display — look & feel
BRIGHTNESS = getattr(config, "BRIGHTNESS", 0.15)
CONTRACT_NAME = getattr(config, "CONTRACT", "sandtimer")
COLOR_SCHEME = getattr(config, "COLOR_SCHEME", "default")
MINUTES_PER_LED = getattr(config, "MINUTES_PER_LED", 1)
URGENCY_THRESHOLDS = getattr(config, "URGENCY_THRESHOLDS", (2, 5))
GAMMA = getattr(config, "GAMMA", 2.2)  # perceptual brightness curve (see gamma())
BREATHE_PERIOD_MS = getattr(config, "BREATHE_PERIOD_MS", 8000)  # one breath, ms
BREATHE_FLOOR = getattr(config, "BREATHE_FLOOR", 0.2)  # dim end of the breath (0..1)
DITHER = getattr(config, "DITHER", True)  # temporal dithering for smooth dim fades
FRAME_MS = getattr(config, "FRAME_MS", 16)  # frame duration, ms
N_TRAINS = getattr(config, "N_TRAINS", 1)  # how many upcoming departures to show
#   as nested arcs (1 = just the primary — the original behaviour). >1 shows
#   further-out trains as a dimmer band beyond the primary's arc.
BACKGROUND_BRIGHTNESS = getattr(config, "BACKGROUND_BRIGHTNESS", 0.35)  # 0..1;
#   relative brightness of the 2nd train; the 3rd gets this squared, etc.
#   (geometric falloff — one knob regardless of how many trains you show).
#   Used by SandTimerContract/BreathingContract's uniform per-layer dimming.

# EchoContract only (see docs/insights.md §6 for why brightness-only dimming
# didn't work): trains beyond the primary differentiate by HUE + a brightness
# that stays high the whole time — no low-brightness dip to flicker/lose
# diffusion. Tuned empirically via led_sandbox.py.
SECONDARY_HUE_SHIFT_DEG = getattr(config, "SECONDARY_HUE_SHIFT_DEG", 20)  # per
#   train index beyond the primary (2nd = ×1, 3rd = ×2, ...)
SECONDARY_BREATHE_PERIOD_MS = getattr(config, "SECONDARY_BREATHE_PERIOD_MS", 3000)
SECONDARY_BREATHE_FLOOR = getattr(config, "SECONDARY_BREATHE_FLOOR", 0.7)  # high —
#   this is a subtle differentiation pulse, not the urgency-signalling breath
#   BreathingContract's own BREATHE_FLOOR drives; deliberately separate knobs
#   so tuning one doesn't fight the other.

# ApproachContract only — positional paradigm, see docs/contracts/approach-contract.md.
# ANCHOR_INDEX/ARM_*_LEN are one arm-generic mechanism: phase 1 (this build) sets
# ARM_B_LEN=0 for a single direction; phase 2 (bidirectional) is the same code
# path with different config, not a second contract.
ANCHOR_INDEX = getattr(config, "ANCHOR_INDEX", 0)
ARM_A_LEN = getattr(config, "ARM_A_LEN", NUM_LEDS - 1)
ARM_B_LEN = getattr(config, "ARM_B_LEN", 0)
ANCHOR_COLOR = getattr(config, "ANCHOR_COLOR", (255, 200, 120))  # warm white/amber —
#   distinct from both LINE_COLOR and MARKER_COLOR so the anchor never
#   reads as "a very close train" or "an empty tick".
ANCHOR_BRIGHTNESS = getattr(config, "ANCHOR_BRIGHTNESS", 1.6)  # relative to a normal
#   "full" position (mult=1.0) — >1.0 makes the anchor genuinely brighter than
#   the BRIGHTNESS ceiling everything else tops out at, not just relying on
#   colour alone to read as "the fixed one". Rendered via the STATIC path (see
#   _write_frame), so this scales BRIGHTNESS LINEARLY — no gamma reshaping.
POSITION_MINUTES_PER_LED = getattr(config, "POSITION_MINUTES_PER_LED", 1)
# The train's own colour is fixed, NOT urgency-banded like PALETTE: in this
# paradigm distance-to-anchor already encodes urgency continuously, so colour
# is freed up to mean "this line" instead of re-encoding the same signal a
# second way (same reasoning MARKER_COLOR-not-dimmed already uses below).
LINE_COLOR = getattr(config, "LINE_COLOR", (34, 139, 34))  # forest green
LINE_SATURATION = getattr(config, "LINE_SATURATION", 1.0)  # 1.0=unchanged;
#   lower = a genuinely MUTED (desaturated) LINE_COLOR, not just a dimmer one
#   — see desaturate()'s docstring for why those are different transforms.
#   Applied once at class-definition time (ApproachContract.line_color).
# Where the train currently is renders at BRIGHTNESS directly (mult=1.0,
# STATIC path, always — see the CHASE transition below, which never dims a
# train at all). Two independent brightness surfaces total:
# ANCHOR_BRIGHTNESS (the "0") and MARKER_BRIGHTNESS (the idle ticks, below) —
# BRIGHTNESS itself is the train's, with no separate scalar on top.
MARKER_BRIGHTNESS = getattr(config, "MARKER_BRIGHTNESS", 0.15)  # LINEAR multiplier
#   of BRIGHTNESS for the idle "tick" LEDs — every position that ISN'T the
#   anchor or the train right now (the gaps on the thermometer). Rendered via
#   the STATIC path (see _write_frame) — direct linear, no gamma. Needs to
#   clear ~1 output code per MARKER_COLOR channel or it truncates invisibly
#   to black. 0 = idle LEDs fully off.
MARKER_COLOR = getattr(config, "MARKER_COLOR", (80, 80, 80))  # dim neutral — NOT a
#   dimmed LINE_COLOR (see docs/contracts/approach-contract.md § Marker ticks)
TRANSITION_MS = getattr(config, "TRANSITION_MS", 4000)  # crossfade duration; 0 = instant

# Boot ceremony — see docs/contracts/startup-sequence.md. Runs once at power-on,
# before the main loop starts; never recurs during normal operation.
STARTUP_COLOR = getattr(config, "STARTUP_COLOR", (255, 255, 255))  # loading-
#   circle + success-burst colour. All LEDs together, contract-agnostic — the
#   startup sequence runs before any CONTRACT is "current".
STARTUP_SPIN_HZ = getattr(config, "STARTUP_SPIN_HZ", 0.4)  # loading-circle
#   revolutions/sec while connecting (WiFi + NTP)
STARTUP_BURST_MS = getattr(config, "STARTUP_BURST_MS", 800)  # success burst:
#   rise duration, ms
STARTUP_FADE_MS = getattr(config, "STARTUP_FADE_MS", 1500)  # success burst:
#   decay duration, ms, after which the main loop takes over
ERROR_COLOR = getattr(config, "ERROR_COLOR", (255, 0, 0))  # persistent
#   failure state — see run_startup_sequence(). All LEDs, forever, until reset.
ERROR_BREATHE_PERIOD_MS = getattr(config, "ERROR_BREATHE_PERIOD_MS", 4000)  #
#   deliberately separate from BREATHE_PERIOD_MS — retuning a contract's
#   breathing feel should never touch the failure state's.

# Status heartbeat LED — board-specific, unlike the WS2812B data line above.
# "LED" is a Pico-2W-only alias (routed through the CYW43 WiFi chip, not a plain
# GPIO). Other boards have no such alias: set this to a GPIO number for that
# board's onboard LED (see pinouts/<board>.md), or None to disable the heartbeat
# entirely — the console heartbeat (●/○) still prints either way.
HEARTBEAT_PIN = getattr(config, "HEARTBEAT_PIN", "LED")

# Quiet hours (strip dark). Stored as hours in config; minutes internally.
QUIET_START = getattr(config, "QUIET_START_HOUR", 23) * 60
QUIET_END = getattr(config, "QUIET_END_HOUR", 6) * 60

np = NeoPixel(Pin(LED_PIN, Pin.OUT), NUM_LEDS)


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


def leave_signal(departures, now):
    """Build a LeaveSignal from a direction's schedule and the current time."""
    raw = next_departures(departures, now)  # minutes-until for the next few trains
    ttls = [t for t in (time_to_leave(m) for m in raw) if t is not None]
    return LeaveSignal(ttls)


# ═════════════════════════════════════════════════════════════
# STAGE 2 — signal → pixels (display contracts)
# ═════════════════════════════════════════════════════════════

# Named urgency→colour schemes. Pick one via COLOR_SCHEME in config.py; add your
# own here. HIDDEN never appears (handled by clear()).
#   default — calm blue (relaxed) → amber (urgent)
#   sunset  — warm amber → magenta
#   mono    — one hue for every level; urgency shows only via arc length
SCHEMES = {
    "default": {LEVEL_1: (255, 100, 0), LEVEL_2: (200, 180, 0), LEVEL_3: (0, 100, 255)},
    "sunset": {LEVEL_1: (255, 40, 0), LEVEL_2: (255, 120, 0), LEVEL_3: (180, 0, 120)},
    "mono": {LEVEL_1: (255, 90, 0), LEVEL_2: (255, 90, 0), LEVEL_3: (255, 90, 0)},
}
PALETTE = SCHEMES.get(COLOR_SCHEME, SCHEMES["default"])


def clear():
    """All LEDs off."""
    for i in range(NUM_LEDS):
        np[i] = (0, 0, 0)
    np.write()


def _arc_len(ttl):
    """time-to-leave (minutes) → number of lit LEDs, MINUTES_PER_LED minutes per
    LED, shrinking toward 1 as the deadline approaches and capped at NUM_LEDS.
    (ttl is guaranteed ≥0 — uncatchable was dropped.)"""
    lit = math.ceil(ttl / MINUTES_PER_LED)
    return max(1, min(lit, NUM_LEDS))


def _physical(logical):
    """Map a *logical* arc position (0 = the arc's origin) to a *physical* LED
    index, honouring ARC_ORIGIN. This is the seam a future per-hardware driver
    would own (reversed strips, ring wrap-around, dead-pixel gaps, …) — contracts
    stay blissfully unaware of the wiring."""
    if ARC_ORIGIN == "far":
        return NUM_LEDS - 1 - logical
    return logical  # "near" (default): logical index == physical index


def _position_offset(ttl):
    """time-to-leave (minutes) → integer offset from the anchor (always ≥1),
    POSITION_MINUTES_PER_LED minutes per LED — the ApproachContract analogue of
    _arc_len, but a single step count rather than a growing arc length. (ttl is
    guaranteed ≥0 — uncatchable was already dropped in Stage 1.)"""
    return max(1, math.ceil(ttl / POSITION_MINUTES_PER_LED))


def _arm_target(ttl, arm_len, direction):
    """time-to-leave → a logical strip index along one arm of ApproachContract's
    anchor/arm geometry, or None if the offset exceeds that arm's length —
    dropped, the same "uncatchable" precedent time_to_leave() already applies
    for trains inside WALK_TO_STATION_MINS: an approach contract can't show a
    train further out than the strip's physical arm reaches, just like an arc
    contract can't grow an arc past NUM_LEDS.

    direction: "a" walks outward with increasing indices (ANCHOR_INDEX + offset,
    phase 1's only active arm); "b" walks the other way (ANCHOR_INDEX - offset,
    phase 2 / bidirectional). Same function either way — arm choice is a config
    question (ARM_A_LEN vs ARM_B_LEN), not a code fork."""
    offset = _position_offset(ttl)
    if offset > arm_len:
        return None
    return ANCHOR_INDEX + offset if direction == "a" else ANCHOR_INDEX - offset


def _heartbeat_pin(name):
    """Construct the status-heartbeat Pin, or None if disabled. Pulled out as its
    own function (rather than inline in main()) purely so it's host-testable
    without pulling in WiFi/NTP/the live loop."""
    return Pin(name, Pin.OUT) if name else None


# Temporal-dither state: one carried rounding-error per (physical LED, channel).
# It PERSISTS across frames — that's the whole point (sigma-delta), so a sub-integer
# brightness like 1.4 averages to 1.4 over time instead of truncating to 1. The
# staggered init decorrelates the pattern across LEDs so they don't flicker in
# lockstep (spatial + temporal averaging → a smooth glow).
_residual = [[((i * 3 + ch) % 5) / 5.0 for ch in range(3)] for i in range(NUM_LEDS)]


def _quantize(value, res, ch):
    """Round `value` (float 0..255) to an int, carrying the error to the next
    frame via res[ch]. Over many frames, mean(output) == value. Integer inputs
    stay exact (no flicker); only fractional values dither."""
    v = value + res[ch]
    q = int(v + 0.5)
    if q < 0:
        q = 0
    elif q > 255:
        q = 255
    res[ch] = v - q
    return q


def _clamp255(value):
    """Clip a float channel value into the valid 0..255 output range, then
    truncate to int. `_quantize` does its own clamping for the dithered path;
    this covers the two plain-truncation paths (DITHER off, and the STATIC
    path in _write_frame) — both matter now that `mult` isn't guaranteed to
    stay within 0..1 (e.g. ANCHOR_BRIGHTNESS > 1.0 to render brighter than a
    normal "full" position)."""
    if value < 0:
        return 0
    if value > 255:
        return 255
    return int(value)


def _layer_mult(index):
    """Relative brightness (0..1) for the `index`-th train layer. index 0 (the
    primary) is always full-relative (1.0); each layer beyond it is dimmer by
    another factor of BACKGROUND_BRIGHTNESS — geometric falloff, so N_TRAINS can
    grow (2, 3, ...) without needing a config knob per layer."""
    return 1.0 if index == 0 else BACKGROUND_BRIGHTNESS ** index


def _layer_hue_shift(index):
    """Hue-rotation degrees for the `index`-th train layer, for EchoContract.
    index 0 (the primary) gets none; each layer beyond it rotates further
    (2nd = ×1, 3rd = ×2, ...) — same per-index scaling idea as _layer_mult, but
    linear rather than geometric: hue is an angle, so "further back → further
    rotated" is the natural analogue of "further back → dimmer" for a hue
    differentiator, not a diminishing-returns curve."""
    return 0 if index == 0 else SECONDARY_HUE_SHIFT_DEG * index


def _write_frame(frame):
    """Composite a resolved frame onto the physical strip in ONE np.write().
    This is the shared tail every render path converges on, and honours the
    `_physical()` HAL seam either way. `_paint_layers` builds `frame` from
    arc-shaped layers; a contract with different geometry (e.g.
    ApproachContract's single positions, not arcs) can build `frame` directly
    and call this instead.

    Each entry in `frame` is one of:
      None                    — LED off
      (color, mult)           — ANIMATED: gamma-corrects `mult`, then dithers
                                 (if DITHER) — for a pixel whose value is
                                 genuinely changing frame-to-frame (a mid-
                                 crossfade position, a breathing arc). Dithering
                                 approximates a fractional brightness by
                                 averaging across frames — it has something to
                                 average *because the target is moving*.
      (color, mult, "static") — STATIC: `level = BRIGHTNESS * mult` directly
                                 (no gamma, no dither) for a pixel whose target
                                 does NOT change between frames (an idle/floor
                                 LED, the always-on anchor, a train position
                                 that's finished crossfading and is just
                                 sitting there). Dithering a CONSTANT value
                                 has nothing to average against — it just
                                 toggles the same one-or-two codes forever,
                                 which at low absolute brightness (few output
                                 codes to work with) reads as visible flicker,
                                 and because each of R/G/B is deliberately
                                 phase-staggered per-LED (see `_residual` below
                                 — decorrelation so LEDs don't flicker in
                                 lockstep), that flicker shows up as
                                 asynchronous per-channel noise: a "sparkling
                                 rgb" idle LED instead of a smooth dim glow.
                                 Same root cause docs/insights.md §6 already
                                 hit with EchoContract's dimmed secondary layer
                                 — see docs/contracts/approach-contract.md."""
    for logical in range(NUM_LEDS):
        phys = _physical(logical)
        entry = frame[logical]
        if entry is None:
            np[phys] = (0, 0, 0)
            continue
        color, mult = entry[0], entry[1]
        if len(entry) > 2 and entry[2] == "static":
            level = BRIGHTNESS * mult
            np[phys] = tuple(_clamp255(color[ch] * level) for ch in range(3))
            continue
        level = BRIGHTNESS * gamma(mult)
        if DITHER:
            res = _residual[phys]
            np[phys] = tuple(_quantize(color[ch] * level, res, ch) for ch in range(3))
        else:
            np[phys] = tuple(_clamp255(color[ch] * level) for ch in range(3))
    np.write()


def _paint_layers(layers):
    """Composite multiple (color, lit, mult) arcs into a frame — the
    paradigm-independent primitive `_paint` is built on. Each layer is a
    logical-position count (`lit`) exactly like `_paint` takes; this is what
    makes "N trains" work identically for a bar, a ring, or a randomized layout:
    none of this function's geometry knowledge is paradigm-specific — that all
    lives in `_physical()`, which every layer still goes through.

    Layers are composited back-to-front: entries LATER in `layers` are painted
    FIRST, so entries EARLIER in the list win where arcs overlap. In practice
    `layers` is ordered primary-first (brightest, usually shortest), so the
    primary always wins the overlap — this holds even in the edge case where two
    trains happen to produce the same arc length."""
    frame = [None] * NUM_LEDS  # logical position → (color, mult) or None (dark)
    for color, lit, mult in layers[::-1]:  # slicing, not reversed() — some
        # MicroPython builds omit the reversed() builtin; slicing is universal
        for logical in range(lit):
            frame[logical] = (color, mult)
    _write_frame(frame)


def _paint(color, lit, mult=1.0):
    """Light the first `lit` LEDs along the arc (logical 0 = origin) in `color`,
    scaled by the global BRIGHTNESS ceiling × `mult`. (`mult` lets animations dim
    the whole arc without touching the palette.) Dark LEDs off. One np.write().

    A single-layer call to _paint_layers() — kept as its own function since most
    contracts only ever need one layer, and this reads more directly than
    wrapping every call site in a one-element list."""
    _paint_layers([(color, lit, mult)])


# ─────────────────────────────────────────────────────────────
# Animation primitives  ←  YOUR PART (reusable building blocks)
# ─────────────────────────────────────────────────────────────
# Pure, LED-free helpers that contracts compose into motion. Keeping them pure
# means they're host-testable (no hardware) and reused across every contract,
# instead of each one re-deriving wave math. Three layers:
#   A. phase / shape — turn elapsed time into a 0.0–1.0 wave
#   B. envelopes     — named brightness multipliers (breathe / blink / pulse)
#   C. colour        — interpolate / dim (r, g, b) tuples
# Candidates to extract into a separate animations.py once they settle.
#
# `dim` and `lerp_color` are worked examples — they set the pattern; you draft
# the rest. None are wired into a contract yet, so stubs are safe to leave.


# ── A. phase / shape (all take/return 0.0–1.0) ──────────────────
def phase_sawtooth(elapsed_ms, period_ms):
    """Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return elapsed_ms % period_ms / period_ms


def phase_exp_sawtooth(elapsed_ms, period_ms):
    """Exponential/surved Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return ((elapsed_ms % period_ms) / period_ms) ** 2


def phase_inv_parabola(elapsed_ms, period_ms):
    """inverse parabolic Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return 1 - ((elapsed_ms % period_ms) / period_ms) ** 2


def tri01(p):
    """Triangle from a 0..1 phase: 0 → 1 (at p=0.5) → 0."""
    return 1 - abs(2 * p - 1)


def sine01(p):
    """Smooth sine from a 0..1 phase, starting at 0: 0 → 1 → 0."""
    return 0.5 * (1 - math.cos(2 * math.pi * p))


def square01(p, duty=0.5):
    """Hard gate from a 0..1 phase: 1.0 while p < duty, else 0.0."""
    return 1.0 if p < duty else 0.0


# ── B. brightness envelopes (elapsed_ms → 0.0–1.0 multiplier) ───
# Each composes layer A and maps into [floor, ceiling] so the arc never fully
# dies (floor) and — new — never needs to reach full-static brightness either
# (ceiling). Default ceiling=1.0 keeps every existing call byte-identical;
# pass a lower ceiling for a layer that should never be mistaken for a
# fully-lit primary at its peak (e.g. a breathing 2nd-train band — see
# docs/insights.md §6: "don't want to mistake bright mode for all lit").
def breathe(elapsed_ms, period_ms=8000, floor=0.2, ceiling=1.0):
    """Smooth in/out glow."""
    return floor + (ceiling - floor) * sine01(phase_sawtooth(elapsed_ms, period_ms))


def breathe_exponent(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """exponential build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_exp_sawtooth(elapsed_ms, period_ms))


def breathe_inverse(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """inverse build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_inv_parabola(elapsed_ms, period_ms))


def blink(elapsed_ms, period_ms=600, duty=0.5, floor=0.2, ceiling=1.0):
    """Hard on/off between `floor` and `ceiling` (`duty` = fraction of the cycle 'on')."""
    return floor + (ceiling - floor) * square01(phase_sawtooth(elapsed_ms, period_ms), duty)


def pulse(elapsed_ms, period_ms=1000, floor=0.1, ceiling=1.0):
    """Sharp triangular ramp up/down, mapped into [floor, ceiling]."""
    return floor + (ceiling - floor) * tri01(phase_sawtooth(elapsed_ms, period_ms))


# ── C. colour helpers ───────────────────────────────────────────
def dim(color, mult):
    """Scale an (r, g, b) by mult (0.0–1.0). Worked example — the pattern."""
    return tuple(int(c * mult) for c in color)


def lerp_color(c0, c1, t):
    """Blend c0 → c1 as t goes 0 → 1 (per-channel linear). Worked example.
    Lets a contract *fade* between urgency colours instead of snapping bands."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def _rgb_to_hsv(r, g, b):
    """(r,g,b) each 0..1 → (h,s,v) each 0..1. Standard reference algorithm
    (same one CPython's colorsys uses — not reinvented, just inlined since
    MicroPython doesn't ship that module)."""
    maxc, minc = max(r, g, b), min(r, g, b)
    v = maxc
    if maxc == minc:
        return 0.0, 0.0, v
    s = (maxc - minc) / maxc
    rc = (maxc - r) / (maxc - minc)
    gc = (maxc - g) / (maxc - minc)
    bc = (maxc - b) / (maxc - minc)
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    return (h / 6.0) % 1.0, s, v


def _hsv_to_rgb(h, s, v):
    """(h,s,v) each 0..1 → (r,g,b) each 0..1. Inverse of _rgb_to_hsv."""
    if s == 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    return v, p, q


def hue_rotate(color, degrees):
    """Shift a colour's HUE by `degrees` (can be any number, wraps mod 360),
    keeping saturation and brightness the same — a "similar yet distinguishable"
    variant, e.g. for a 2nd train's colour instead of dimming it (dimming alone
    doesn't work well on bare-strip hardware — see docs/insights.md §6: at low
    brightness, dithering runs out of headroom and diffusion runs out of light).
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r, g, b = _hsv_to_rgb(h, s, v)
    # round, not truncate — a 360° round-trip should be a lossless identity,
    # not off-by-one from floating-point drift through the hsv conversion.
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def desaturate(color, saturation):
    """Scale a colour's SATURATION by `saturation` (0.0 = fully gray, 1.0 =
    unchanged), keeping hue and value the same — a genuinely MUTED variant of
    a colour, not just a dimmer one. `hue_rotate()`'s counterpart on the other
    HSV axis: hue_rotate keeps the same brightness/vividness and shifts which
    colour it is; desaturate keeps the same colour/brightness and shifts how
    vivid it is.

    Distinct from just lowering a render `mult` (brightness): scaling
    brightness scales R/G/B by the same factor, which is mathematically
    identical to picking a *dimmer* version of the same colour — it can't
    produce a *muted* (desaturated, toward-gray) version, since that requires
    each channel to move toward the colour's own maximum channel value, not
    toward zero. Used for ApproachContract's LINE_COLOR (LINE_SATURATION) —
    see docs/contracts/approach-contract.md.
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    s *= max(0.0, saturation)
    r, g, b = _hsv_to_rgb(h, s, v)
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


# ── D. perceptual correction  ←  YOUR PART ──────────────────────
def gamma(mult, g=GAMMA):
    """Perceptual-brightness correction for an animation multiplier (0..1 → 0..1).

    Why: the eye responds ~logarithmically but WS2812B PWM is linear, so a linear
    fade looks steppy/uneven — worst at the dim end. Raising the multiplier to a
    power `g` (≈2.2–2.8) spreads the visible steps to match perception. This is
    the single biggest smoothness win for the breath — bigger than frame rate.

    Contract: monotonic; endpoints fixed (gamma(0)=0, gamma(1)=1); stays in [0,1].
    Applied to `mult` in _paint (not the base colour), so static contracts — which
    pass mult=1.0 → gamma(1.0)=1.0 — are unaffected.

    TODO(you): return mult ** g   (that's the whole thing; g comes from config).
    Currently a no-op pass-through so the display keeps working until you fill it.

    ⚠ Interaction to watch: gamma pushes the dim end *down* (0.2 ** 2.2 ≈ 0.03), so
    after you enable it the breath will dip closer to black — you may want to raise
    BREATHE_FLOOR to keep it visible through the jar.
    """
    return mult ** g


class DisplayContract:
    """A rendering strategy. The main loop treats every contract identically:
    it calls render(signal, phase_ms) and honours frame_ms for timing.

      frame_ms = None  → static: draw one frame, then sleep the interval
                         (deep-sleep-friendly — the V2 power path)
      frame_ms = int   → animated: redraw every frame_ms across the interval
                         (cannot deep-sleep while animating)
    """

    frame_ms = None

    def render(self, signal, phase_ms):
        """Draw a single frame. `phase_ms` is a monotonic ms clock (absolute
        `time.ticks_ms()`; `0` for static contracts, which ignore it). Animated
        contracts feed it to the phase functions, which reduce it mod their period
        — so it flows continuously across intervals."""
        raise NotImplementedError


class SandTimerContract(DisplayContract):
    """Shrinking arc, colour by urgency band, no pulse. The default.

    Shows up to N_TRAINS departures as nested arcs: the primary lights up
    bright out to its own length; each further-out train (same colour, always
    equal-or-longer since it's further away) extends a dimmer band beyond
    that — "and if you miss this one, you've got until here for the next."
    """

    frame_ms = None
    COLOR = PALETTE

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        color = self.COLOR[signal.urgency]  # one colour for every layer, per spec
        layers = [
            (color, _arc_len(ttl), _layer_mult(i))
            for i, ttl in enumerate(signal.ttls[:N_TRAINS])
        ]
        _paint_layers(layers)


class ColorContract(DisplayContract):
    """Full bar always; only the COLOUR changes with urgency. No shrinking arc,
    no pulse — the calmest, most abstract strategy.

    Deliberately ignores N_TRAINS: it has no arc/length axis to hang a second
    train on (the whole strip is always lit) — not every contract needs to
    consume every signal field.
    """

    frame_ms = None
    COLOR = PALETTE

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        _paint(self.COLOR[signal.urgency], NUM_LEDS)


class BreathingContract(DisplayContract):
    """Arc that breathes — with configurable envelope function.

    Same N_TRAINS nesting as SandTimerContract; the breath multiplier is
    combined with each layer's falloff (_layer_mult(i) * breath), so every
    train's band breathes together rather than independently."""

    frame_ms = FRAME_MS
    COLOR = PALETTE
    # staticmethod so a plain function stored as a class attr doesn't bind `self`
    # (otherwise self.breathe_fn(phase_ms) would call breathe(self, phase_ms)).
    breathe_fn = staticmethod(breathe)

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        breath = self.breathe_fn(phase_ms, BREATHE_PERIOD_MS, BREATHE_FLOOR)
        color = self.COLOR[signal.urgency]
        layers = [
            (color, _arc_len(ttl), _layer_mult(i) * breath)
            for i, ttl in enumerate(signal.ttls[:N_TRAINS])
        ]
        _paint_layers(layers)


class BreathingExponentContract(BreathingContract):
    """Same as Breathing, but with exponential curve."""

    breathe_fn = staticmethod(breathe_exponent)


class BreathingInverseContract(BreathingContract):
    """Same as Breathing, but inverted."""

    breathe_fn = staticmethod(breathe_inverse)


class EchoContract(DisplayContract):
    """Primary train: static, full brightness (SandTimer's treatment). Every
    train beyond it: hue-shifted + gently breathing (never dipping below
    SECONDARY_BREATHE_FLOOR) — "echoes" the primary rather than dimming it.

    This exists because brightness-only differentiation didn't hold up on
    real hardware (docs/insights.md §6: at low absolute brightness, dithering
    runs out of headroom and diffusion runs out of light — flicker + visible
    LED die instead of ambient glow). Colour + subtle motion sidesteps both
    problems by keeping every layer near full brightness.

    Composes existing primitives rather than reinventing them: _arc_len for
    geometry (same as SandTimer/Breathing), breathe_fn for motion (same
    envelope functions Breathing uses, just with its own period/floor so
    tuning one doesn't fight the other), hue_rotate for colour.
    """

    frame_ms = FRAME_MS  # animated — secondary layers breathe
    COLOR = PALETTE
    breathe_fn = staticmethod(breathe)  # overridable per subclass, like Breathing*

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        base_color = self.COLOR[signal.urgency]
        layers = []
        for i, ttl in enumerate(signal.ttls[:N_TRAINS]):
            if i == 0:
                color, mult = base_color, 1.0  # primary: static, full brightness
            else:
                color = hue_rotate(base_color, _layer_hue_shift(i))
                mult = self.breathe_fn(
                    phase_ms, SECONDARY_BREATHE_PERIOD_MS, SECONDARY_BREATHE_FLOOR
                )
            layers.append((color, _arc_len(ttl), mult))
        _paint_layers(layers)


class _TrainState:
    """CHASE-transition state for ONE train marker. Phase 1/2 (single train
    per arm) needed exactly one of these per arm; N_TRAINS>1 (iteration 2)
    keeps a LIST of these per arm — one per rank (closest, 2nd-closest, …) —
    so every simultaneous marker animates independently, on its own clock,
    without interfering with any other slot's."""

    def __init__(self):
        self.index = None  # current/incoming train position, or None
        self.color = None
        self.sweep_from = None  # index a sweep is currently animating FROM,
        #   or None if settled (or nothing to sweep between — see below)
        self.transition_start = None  # phase_ms the current sweep began


def _advance_train(frame, train, target, color, phase_ms):
    """Advance one train's CHASE transition given this tick's target index
    (or None), and paint its contribution into `frame` (mutated in place,
    NOT returned). The one place the transition logic lives — every call
    site (single train, N_TRAINS>1, bidirectional) goes through this, once
    per train slot, so the logic exists exactly once regardless of how many
    are active.

    A moving highlight sweeps LED-by-LED from the old position to the new
    one, one LED lit at a time, always at FULL brightness (mult=1.0,
    STATIC). This deliberately replaced an earlier brightness/colour-blend
    crossfade: that design necessarily passed through low-brightness
    intermediate values, and at low enough absolute brightness temporal
    dithering breaks down on this hardware (visible flicker — the exact
    failure mode docs/insights.md §6 and the marker-tick fix both already
    hit). CHASE never asks for anything between "off" and "full" — every
    touched LED is always a fully-populated 8-bit code, so dithering is
    never needed at all during a transition, not just tuned to be less
    visible. See docs/contracts/approach-contract.md § Chase transition."""
    if target != train.index:
        # A sweep only makes sense between two KNOWN positions. Appearing
        # from nothing (a train's first tick) or vanishing to nothing (no
        # longer catchable) has no LED to sweep from/to — snap instead, no
        # animation possible or needed.
        if target is not None and train.index is not None:
            train.sweep_from = train.index
        else:
            train.sweep_from = None
        train.index = target
        train.color = color
        train.transition_start = phase_ms

    if train.index is None:
        return  # nothing to show for this slot right now

    if train.sweep_from is None:
        # Settled (or just snapped in/out with nothing to sweep between) —
        # identical every frame until the position next changes.
        frame[train.index] = (train.color, 1.0, "static")
        return

    progress = 1.0
    if TRANSITION_MS > 0 and train.transition_start is not None:
        elapsed = phase_ms - train.transition_start  # phase_ms: absolute
        #   ticks_ms(), same "no snap-back across intervals" pattern the
        #   breathing envelopes use — see render_for_interval().
        progress = min(1.0, max(0.0, elapsed / TRANSITION_MS))

    # Divide the sweep into `distance` equal LED-to-LED steps (distance=1 for
    # the common one-LED-per-tick hop → a single sharp switch at the
    # halfway point; larger jumps sweep through every LED in between, each
    # getting an equal time-slice). `min(distance, ...)` clamps the final
    # step to land exactly on `train.index` at progress=1.0.
    distance = abs(train.index - train.sweep_from)
    sign = 1 if train.index > train.sweep_from else -1
    step = min(distance, int(progress * (distance + 1)))
    frame[train.sweep_from + sign * step] = (train.color, 1.0, "static")

    if progress >= 1.0:
        train.sweep_from = None  # sweep finished — future frames render settled


def _advance_arm(frame, slots, signal, arm_len, direction, base_color, phase_ms):
    """Advance every train slot for ONE arm (up to len(slots) == N_TRAINS,
    soonest-first, same rank convention as _paint_layers' N_TRAINS handling
    elsewhere) and paint each into `frame`.

    Slot 0 (the primary/closest train) renders `base_color` unshifted; every
    slot beyond it is hue-rotated (_layer_hue_shift — the same per-index
    scaling EchoContract already uses) so multiple simultaneous markers stay
    visually distinguishable WITHOUT dimming. Dimming a secondary layer is
    exactly the failure mode docs/insights.md §6 already ruled out (breaks
    at low absolute brightness on this hardware) — hue doesn't have that
    problem, and every CHASE-rendered train is full brightness anyway (see
    _advance_train), so dimming a slot would also silently undo that.

    Slots are advanced/painted in REVERSE order (last slot first) so slot 0
    is painted LAST and wins any index collision — same convention
    _paint_layers uses for arc-based contracts.

    Note on identity: Stage 1 (LeaveSignal) is deliberately ephemeral and
    tracks no train identity across ticks — "slot 0" means "whichever train
    is currently closest," not a specific physical train. If the current
    primary departs and the former rank-1 train becomes rank-0, slot 0's
    CHASE will animate from the old primary's position to wherever that
    train already was, rather than continuing rank-1's own animation. This
    is an accepted simplification consistent with Stage 1's existing
    "ephemeral, rebuilt every tick, no identity" design — true per-train
    identity tracking would be a bigger structural change than "N trains,
    set in config" scoped for this iteration."""
    ttls = signal.ttls if signal.urgency is not HIDDEN else []
    n = len(slots)
    targets = [None] * n
    for i, ttl in enumerate(ttls[:n]):
        targets[i] = _arm_target(ttl, arm_len, direction)

    for i in range(n - 1, -1, -1):
        color = base_color if i == 0 else hue_rotate(base_color, _layer_hue_shift(i))
        _advance_train(frame, slots[i], targets[i], color, phase_ms)


class ApproachContract(DisplayContract):
    """Positional/approach paradigm: each train renders as a SINGLE LED that
    moves toward ANCHOR_INDEX as its time-to-leave shrinks, rather than an
    arc that grows/shrinks from a fixed origin. See
    docs/contracts/approach-contract.md for the full design rationale.

    Phase 1: ARM_B_LEN=0, single direction — call render(signal, phase_ms),
    exactly as before. Phase 2 (bidirectional, DISPLAY_DIRECTION_B configured):
    call render_dual(signal_a, signal_b, phase_ms) instead — one arm's worth
    of trains per direction. main()'s loop picks the entry point;
    ApproachContract itself doesn't know which mode it's in beyond which
    method got called.

    N_TRAINS (iteration 2, reusing the same knob the arc contracts use)
    controls how many simultaneous markers each arm shows, soonest-first —
    default 1, phase 1/2's original single-train-per-arm behaviour unchanged.

    Two independent brightness surfaces, matching how this actually reads to
    a viewer: ANCHOR_BRIGHTNESS (the "0") and MARKER_BRIGHTNESS/MARKER_COLOR
    (the idle "tick" LEDs — every position that isn't the anchor or a train
    right now). A train is never dimmer than BRIGHTNESS itself — no separate
    knob, and (since the CHASE transition below) no dim intermediate state
    either. MARKER_COLOR is deliberately a different colour from LINE_COLOR,
    not a dimmed version of it, so an idle tick can't be mistaken for "a
    very distant train" (see the concept doc's Marker ticks section).
    """

    frame_ms = FRAME_MS
    line_color = desaturate(LINE_COLOR, LINE_SATURATION)  # computed once at
    #   module load — LINE_SATURATION=1.0 (default) is a no-op identity

    def __init__(self):
        # Instance state, not class state: tracks the *last actually rendered*
        # position across calls, so a change in position can be detected and
        # crossfaded — unlike every other contract here, this one is not a
        # pure function of (signal, phase_ms) alone. Two arms' worth of slots
        # always exist; phase 1 (render()) simply never touches _arm_b.
        self._arm_a = [_TrainState() for _ in range(N_TRAINS)]
        self._arm_b = [_TrainState() for _ in range(N_TRAINS)]

    def render(self, signal, phase_ms):
        """Phase 1 — single direction. Kept as its own method (not
        render_dual with a None second signal) so a phase-1 config's
        behaviour can never be perturbed by phase-2 code."""
        frame = [(MARKER_COLOR, MARKER_BRIGHTNESS, "static")] * NUM_LEDS
        _advance_arm(frame, self._arm_a, signal, ARM_A_LEN, "a", self.line_color, phase_ms)

        # Anchor is painted last so it always wins, even the instant a train
        # lands on ANCHOR_INDEX itself — it never participates in train logic.
        # Always STATIC: it's a fixed brightness forever, never animated.
        frame[ANCHOR_INDEX] = (ANCHOR_COLOR, ANCHOR_BRIGHTNESS, "static")
        _write_frame(frame)

    def render_dual(self, signal_a, signal_b, phase_ms):
        """Phase 2 — bidirectional: one arm's worth of trains per direction,
        each with its own independent CHASE transition, composited into the
        same frame. Arm "a" and arm "b" occupy disjoint index ranges
        (ANCHOR_INDEX+offset vs ANCHOR_INDEX-offset — see _arm_target), so
        there's no overlap to resolve between them; only the anchor itself
        can coincide, and it's painted last regardless."""
        frame = [(MARKER_COLOR, MARKER_BRIGHTNESS, "static")] * NUM_LEDS
        _advance_arm(frame, self._arm_a, signal_a, ARM_A_LEN, "a", self.line_color, phase_ms)
        _advance_arm(frame, self._arm_b, signal_b, ARM_B_LEN, "b", self.line_color, phase_ms)
        frame[ANCHOR_INDEX] = (ANCHOR_COLOR, ANCHOR_BRIGHTNESS, "static")
        _write_frame(frame)


# Registry: config's CONTRACT name → class. Add new contracts here so they're
# selectable from config.py without touching the main loop.
CONTRACTS = {
    "sandtimer": SandTimerContract,
    "color": ColorContract,
    "breathing": BreathingContract,
    "breathing_exponent": BreathingExponentContract,
    "breathing_inverse": BreathingInverseContract,
    "echo": EchoContract,
    "approach": ApproachContract,
}
ACTIVE_CONTRACT = CONTRACTS.get(CONTRACT_NAME, SandTimerContract)()


def is_quiet(now):
    """True during the configured quiet hours. The window can wrap past midnight
    (e.g. 23:00 → 06:00), so we test the gap with OR, not a simple range."""
    return now >= QUIET_START or now < QUIET_END


# ─────────────────────────────────────────────────────────────
# Schedule loading
# [→ Rust] build.rs reads schedule.json at compile time and emits
#          const arrays — zero runtime parsing cost on device.
# ─────────────────────────────────────────────────────────────
def load_schedule(filename):
    """
    Load schedule.json from device filesystem.
    Returns the full parsed dict (station, weekday, weekend).
    Halts with a clear message if file is missing or malformed.
    """
    try:
        with open(filename) as f:
            return json.load(f)
    except OSError:
        print(f"✗ Schedule file not found: {filename}")
        print("  Upload it with: make upload")
        raise


# ─────────────────────────────────────────────────────────────
# Time helpers
# [→ Rust] read_rtc() reads DS3231 over I2C → (hours, minutes, weekday)
# ─────────────────────────────────────────────────────────────
def local_time():
    """
    Return (minutes_since_midnight, weekday) in local time.
    weekday: 0=Monday … 6=Sunday (MicroPython convention)

    NTP sets the Pico RTC to UTC. We add UTC_OFFSET_HOURS to get local
    time — and also account for the day boundary, so the correct weekday
    is used when UTC and local time are on different calendar days.
    (e.g. UTC 22:00 Thursday = JST 07:00 Friday)
    """
    utc = time.localtime()  # (year, mon, mday, hour, min, sec, weekday, yearday)
    utc_minutes = utc[3] * 60 + utc[4]
    local_minutes_abs = utc_minutes + UTC_OFFSET_HOURS * 60

    day_overflow = local_minutes_abs // (24 * 60)  # 0 or 1
    local_minutes = local_minutes_abs % (24 * 60)
    local_weekday = (utc[6] + day_overflow) % 7

    return local_minutes, local_weekday


def current_period(weekday):
    """Return 'weekday' or 'weekend' for the given weekday index."""
    return "weekend" if weekday >= 5 else "weekday"


def fmt_time(minutes):
    """Format minutes-since-midnight as HH:MM."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ─────────────────────────────────────────────────────────────
# Schedule logic
# [→ Rust] Iterator::filter().take(n) on a sorted &[u16]
# ─────────────────────────────────────────────────────────────
def next_departures(schedule, now, count=3):
    """
    Return list of up to `count` minutes-until-departure values (ints).
    Empty list means no trains remain today.
    """
    return [m - now for m in schedule if m > now][:count]


# ─────────────────────────────────────────────────────────────
# Startup sequence ("boot ceremony") — docs/contracts/startup-sequence.md
# Runs once at power-on, before the main loop; never recurs during normal
# operation. Not a DisplayContract — at boot there's no LeaveSignal yet (no
# WiFi, no NTP time, schedule not even loaded), so this is boot-time
# procedural code that observes LIVE connection state, not a pure render of
# an already-known value.
# ─────────────────────────────────────────────────────────────
def _startup_circle_index(elapsed_ms):
    """PURE: elapsed ms of the loading-circle spin → which LED is lit, at
    STARTUP_SPIN_HZ revolutions/sec. Host-testable in isolation from the real
    connect_wifi() poll loop below, which isn't (real time.ticks_ms())."""
    period_ms = 1000.0 / STARTUP_SPIN_HZ
    return int(phase_sawtooth(elapsed_ms, period_ms) * NUM_LEDS) % NUM_LEDS


def _draw_startup_circle(elapsed_ms):
    """One frame of the loading-circle spin: a single lit LED, everything
    else off. No dim intermediate value at all (fully on or fully off) —
    STATIC path (see _write_frame), no dithering needed."""
    frame = [None] * NUM_LEDS
    frame[_startup_circle_index(elapsed_ms)] = (STARTUP_COLOR, 1.0, "static")
    _write_frame(frame)


def _startup_burst_mult(elapsed_ms):
    """PURE: elapsed ms into the success burst → brightness mult (0..1).
    Rises linearly over STARTUP_BURST_MS, then decays linearly over
    STARTUP_FADE_MS. Host-testable; the real-time loop that calls this
    (_play_startup_burst) isn't — same split render_for_interval/
    _render_dispatch already established."""
    if STARTUP_BURST_MS > 0 and elapsed_ms < STARTUP_BURST_MS:
        return elapsed_ms / STARTUP_BURST_MS
    decay_elapsed = elapsed_ms - STARTUP_BURST_MS
    if STARTUP_FADE_MS <= 0 or decay_elapsed >= STARTUP_FADE_MS:
        return 0.0
    return 1.0 - (decay_elapsed / STARTUP_FADE_MS)


def _play_startup_burst():
    """The 'hanabi' success cue: all LEDs together (contract-agnostic — no
    CONTRACT is "current" yet), a quick bright rise then a slow decay. This
    genuinely changes every frame, unlike a settled/idle pixel, so the
    ANIMATED path (gamma + dither, via a 2-tuple frame entry) is the right
    one here — dithering only causes trouble on a value that ISN'T changing
    (see docs/contracts/approach-contract.md § Marker ticks); a decaying
    pulse has something to average against. Ends by clearing the strip —
    the main loop's first real frame follows immediately after."""
    start = time.ticks_ms()
    total_ms = STARTUP_BURST_MS + STARTUP_FADE_MS
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= total_ms:
            break
        mult = _startup_burst_mult(elapsed)
        _write_frame([(STARTUP_COLOR, mult)] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _startup_error_mult(elapsed_ms):
    """PURE: elapsed ms → brightness mult for the persistent failure breathe.
    Thin wrapper over the existing breathe() envelope, its own dedicated
    period (ERROR_BREATHE_PERIOD_MS, not BREATHE_PERIOD_MS)."""
    return breathe(elapsed_ms, ERROR_BREATHE_PERIOD_MS, floor=0.15)


def _run_startup_failure_forever():
    """Persistent red breathe — a genuine DEAD END, not a retry loop, by
    design (see docs/contracts/startup-sequence.md § Failure recovery).
    Distinguishes "broken, needs help" from every other state at a glance,
    and doesn't pretend to work when it can't. Needs a physical reset/
    power-cycle to leave this state; never returns on its own."""
    print("  ✗ Startup failed — check config.py / WiFi. Reset to retry.")
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _write_frame([(ERROR_COLOR, _startup_error_mult(elapsed))] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)


def run_startup_sequence():
    """The whole boot ceremony. On success: connecting spin, then the
    success burst, then returns — the main loop takes over immediately
    after. On WiFi failure: _run_startup_failure_forever(), which NEVER
    RETURNS (see its docstring) — this function correspondingly never
    returns either, in that case."""
    if not connect_wifi():
        _run_startup_failure_forever()
    if not sync_ntp():
        print("  Warning: time may be wrong.")
    _play_startup_burst()


# ─────────────────────────────────────────────────────────────
# WiFi + NTP
# [→ Rust] embassy_net + CYW43 driver / replaced entirely by DS3231 in V2
# ─────────────────────────────────────────────────────────────
def connect_wifi():
    """Connect to WiFi, animating the loading-circle spin (see
    _draw_startup_circle) while polling — replaced a blocking `sleep(1)`
    poll loop that drew nothing at all, the main piece of real engineering
    the boot ceremony needed (the animation math itself was nothing new)."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("  Connecting to WiFi", end="")
    start = time.ticks_ms()
    dots_printed = 0
    while time.ticks_diff(time.ticks_ms(), start) < 20000:  # same ~20s budget
        if wlan.isconnected():                              # the old 20x sleep(1) had
            break
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _draw_startup_circle(elapsed)
        whole_seconds = elapsed // 1000
        if whole_seconds > dots_printed:
            dots_printed = whole_seconds
            print(".", end="")
        time.sleep_ms(FRAME_MS)
    print()
    if wlan.isconnected():
        print(f"  ✓ Connected  IP: {wlan.ifconfig()[0]}")
        return True
    print("  ✗ WiFi failed — check config.py")
    return False


def sync_ntp():
    try:
        ntptime.settime()
        print("  ✓ NTP sync OK")
        return True
    except Exception as e:
        print(f"  ✗ NTP failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────
def _render_dispatch(contract, signal, signal_b):
    """Pick render() vs render_dual() based on whether signal_b is given AND
    the contract actually implements render_dual — phase-2 bidirectional
    support (ApproachContract only, see DISPLAY_DIRECTION_B). Every other
    contract, and phase-1 ApproachContract configs (DISPLAY_DIRECTION_B
    unset, signal_b is None), fall through to the ordinary single-signal path
    unaffected. Pulled out as its own pure function — no clock involved — so
    this decision is host-testable in isolation from render_for_interval's
    real-time frame loop below, which isn't (it uses actual time.ticks_ms())."""
    if signal_b is not None and hasattr(contract, "render_dual"):
        return lambda phase_ms: contract.render_dual(signal, signal_b, phase_ms)
    return lambda phase_ms: contract.render(signal, phase_ms)


def render_for_interval(contract, signal, seconds, signal_b=None):
    """Hand the signal(s) to the contract for ~`seconds`. Static contracts draw
    once and return immediately (the caller sleeps). Animated contracts get a
    frame loop, fed the **absolute** ms clock so their phase is continuous
    across intervals — no snap-back to the floor every LOOP_INTERVAL_SECS. The
    signal(s) are fixed for the interval; only the clock advances (update/
    render split).

    Safe with the huge absolute value because the envelopes do `(clock % period)`
    — the modulo runs in integer space before the divide, so no float precision is
    lost. `ticks_ms()` wraps ~every 12 days → one harmless single-frame hitch."""
    render = _render_dispatch(contract, signal, signal_b)
    if contract.frame_ms is None:
        render(0)
        return  # caller sleeps the interval
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
        render(time.ticks_ms())
        time.sleep_ms(contract.frame_ms)


def main():
    led = _heartbeat_pin(HEARTBEAT_PIN)  # None on boards with no onboard-LED alias
    heartbeat = False

    print("\n══ eki-bin ═══════════════════════════════════════")

    schedule_data = load_schedule(SCHEDULE_FILE)
    print(
        f"  Station: {schedule_data['station']}   Ring: {DISPLAY_DIRECTION!r}\n"
        f"  Contract: {type(ACTIVE_CONTRACT).__name__}   Scheme: {COLOR_SCHEME!r}   "

        f"  N trains: {N_TRAINS} "
        f"LEDs: {NUM_LEDS} on GP{LED_PIN}"
    )

    try:
        run_startup_sequence()  # boot ceremony — never returns on WiFi
        #   failure (persistent red breathe instead), so everything below
        #   only ever runs after a successful connect + burst.

        print(f"  Loop interval: {LOOP_INTERVAL_SECS}s  |  Ctrl+C to stop\n")

        DIVIDER = "─" * 50
        loop_count = 0

        while True:
            heartbeat = not heartbeat
            if led:
                led.value(heartbeat)
            loop_count += 1
            hb = "●" if heartbeat else "○"

            now, weekday = local_time()
            period = current_period(weekday)
            directions = schedule_data.get(period, {})

            print(DIVIDER)
            print(
                f"  {hb}  {fmt_time(now)} JST   {period}   {schedule_data['station']}   #{loop_count}"
            )
            print(DIVIDER)

            if not directions:
                print(
                    f"  No schedule for {period!r} — run: make schedule && make upload"
                )
            else:
                for direction, departures in directions.items():
                    upcoming = next_departures(departures, now)
                    marker = "  ← ring" if direction == DISPLAY_DIRECTION else ""
                    print(f"\n  {direction}{marker}")
                    if not upcoming:
                        print("    —  no more trains today")
                        continue
                    for i, until in enumerate(upcoming):
                        arrow = "→" if i == 0 else " "
                        print(
                            f"    {arrow}  {fmt_time(now + until)}   in {until:2d} min"
                        )

            # ── Drive the LED ring ───────────────────────────────────
            # One ring → one direction (no magnetometer in V1) — or two, for
            # phase-2 bidirectional ApproachContract (DISPLAY_DIRECTION_B).
            # Build the abstract signal(s), then let whichever contract is
            # active interpret them.
            signal = leave_signal(directions.get(DISPLAY_DIRECTION, []), now)
            if signal.ttls:
                leaves = ", ".join("{:.1f}".format(t) for t in signal.ttls)
                print(f"\n  ring: leave in [{leaves}] min  →  {signal.urgency.name}")
            else:
                print(f"\n  ring: {signal.urgency.name}  (no catchable trains)")

            signal_b = None
            if DISPLAY_DIRECTION_B is not None:
                signal_b = leave_signal(directions.get(DISPLAY_DIRECTION_B, []), now)
                if signal_b.ttls:
                    leaves_b = ", ".join("{:.1f}".format(t) for t in signal_b.ttls)
                    print(f"  ring B: leave in [{leaves_b}] min  →  {signal_b.urgency.name}")
                else:
                    print(f"  ring B: {signal_b.urgency.name}  (no catchable trains)")

            # Night → dark + sleep. Otherwise the contract renders for the interval
            # (static returns at once → we sleep; animated runs its own frame loop).
            if is_quiet(now):
                print("  (quiet hours — display off)")
                clear()
                time.sleep(LOOP_INTERVAL_SECS)
            else:
                render_for_interval(ACTIVE_CONTRACT, signal, LOOP_INTERVAL_SECS, signal_b)
                if ACTIVE_CONTRACT.frame_ms is None:
                    time.sleep(LOOP_INTERVAL_SECS)
    except KeyboardInterrupt:
        pass
    finally:
        clear()  # leave the strip dark on exit, like led_test.py
        print("\n  cleared — bye")


# `mpremote run main.py` and the device boot both execute this as __main__, so
# the loop still starts normally. But `import main` in the REPL does NOT — which
# lets you poke a contract live while iterating, no WiFi needed:
#     import main
#     sig = main.LeaveSignal([3.0])              # a 3-min-to-leave snapshot
#     main.ACTIVE_CONTRACT.render(sig, 0)        # draw it
#     main.clear()
if __name__ == "__main__":
    main()
