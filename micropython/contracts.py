# micropython/contracts.py — eki-bin
# STAGE 2 of the pipeline: signal → pixels. Every display strategy, the
# colour schemes they draw from, and the arc/anchor geometry they position
# against. Extracted verbatim from main.py by the V1.6 split.
#
# The main loop treats every contract identically, so a visual strategy is
# swapped by changing CONTRACT in config.py and nothing else. See
# docs/contracts/display-contract.md and approach-contract.md.
#
# Depends on leds (to paint) but NOT the reverse: contracts speak in logical
# positions and never learn how the strip is wired.

import math
from leds import (_layer_hue_shift, _layer_mult, _paint, _paint_layers,
    _write_frame, clear)
from primitives import (breathe, breathe_exponent, breathe_inverse,
    desaturate, hue_rotate)
from settings import (ANCHOR_BRIGHTNESS, ANCHOR_COLOR, ANCHOR_INDEX,
    ARM_A_LEN, ARM_B_LEN, BREATHE_FLOOR, BREATHE_PERIOD_MS, COLOR_SCHEME,
    CONTRACT_NAME, FRAME_MS, LINE_COLOR, LINE_SATURATION,
    MARKER_BRIGHTNESS, MARKER_COLOR, MINUTES_PER_LED, NUM_LEDS, N_TRAINS,
    POSITION_MINUTES_PER_LED, SECONDARY_BREATHE_FLOOR,
    SECONDARY_BREATHE_PERIOD_MS, TRANSITION_MS)
from signals import (HIDDEN, LEVEL_1, LEVEL_2, LEVEL_3)
# `import *` skips underscore names; contracts needs these by name.

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


def _arc_len(ttl):
    """time-to-leave (minutes) → number of lit LEDs, MINUTES_PER_LED minutes per
    LED, shrinking toward 1 as the deadline approaches and capped at NUM_LEDS.
    (ttl is guaranteed ≥0 — uncatchable was dropped.)"""
    lit = math.ceil(ttl / MINUTES_PER_LED)
    return max(1, min(lit, NUM_LEDS))


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


def geometry_problems(num_leds=None, anchor=None, arm_a=None, arm_b=None):
    """Reasons the anchor/arm geometry can't fit the strip; [] means it fits.

    _arm_target() bounds each offset against its ARM length but never
    against NUM_LEDS, so geometry tuned for one strip and run on a shorter
    one indexes off the end of the frame. On hardware that surfaced as a
    bare `IndexError: list index out of range` three call levels deep in the
    render loop — AFTER a clean boot, a correct clock and a correct
    timetable printout, which points nowhere near config.py.

    Parameterised (rather than reading the module constants directly) so
    tests can sweep combinations without re-importing main a dozen times."""
    n = NUM_LEDS if num_leds is None else num_leds
    a = ANCHOR_INDEX if anchor is None else anchor
    la = ARM_A_LEN if arm_a is None else arm_a
    lb = ARM_B_LEN if arm_b is None else arm_b
    out = []
    if n <= 0:
        return ["NUM_LEDS=%d must be positive" % n]
    if not 0 <= a < n:
        out.append("ANCHOR_INDEX=%d is off the strip (valid 0..%d)" % (a, n - 1))
        return out  # every arm message below would just restate this
    if la < 0:
        out.append("ARM_A_LEN=%d is negative" % la)
    elif a + la > n - 1:
        out.append("arm A reaches LED %d but the last is %d — set ARM_A_LEN "
                   "to %d or less" % (a + la, n - 1, n - 1 - a))
    if lb < 0:
        out.append("ARM_B_LEN=%d is negative" % lb)
    elif a - lb < 0:
        out.append("arm B reaches LED %d but the first is 0 — set ARM_B_LEN "
                   "to %d or less" % (a - lb, a))
    return out


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

    def set_line_color(self, color):
        """Point this contract at one line's colour. Shadows the class-level
        default with an instance attribute; passing None restores it.

        This is what makes a line identifiable **at a glance**, which is the
        whole requirement: the premise is looking over at a random moment, so
        identity has to live in the static view rather than in a cue that
        only fires when you cycle (gesture-envelope.md §11). The anchor stays
        neutral — set ANCHOR_COLOR to white — and the moving train dots carry
        the colour, exactly like a metro map.

        LINE_SATURATION still applies, so a per-enclosure desaturation
        setting keeps working across every line rather than being defeated by
        the schedule's nominal colours."""
        self.line_color = desaturate(color or LINE_COLOR, LINE_SATURATION)

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
