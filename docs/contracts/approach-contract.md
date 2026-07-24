# Contract: `ApproachContract` (positional / approach display)

**Status:** implemented on `feature/positional-display`, real-hardware bring-up
in progress on the 21-LED gift-jar strip. See `dev-status.md` for the active
dev plan and test sequence. This doc is the durable concept reference (the
*what and why*), kept separate from the dev plan (the *when and how*) per the
existing `display-contract.md` / `dev-status.md` split.

**Fits into:** the existing `time → LeaveSignal → DisplayContract → LEDs`
pipeline in `docs/contracts/display-contract.md`. `ApproachContract` is a new
Stage 2 strategy — Stage 1 (`LeaveSignal`, `ttls`) is unchanged. Register it in
`CONTRACTS` and select via `CONTRACT = "approach"` in `config.py`, same as any
other contract.

---

## The idea

Every existing contract (`SandTimerContract`, `BreathingContract`, `EchoContract`,
`ColorContract`) treats the strip as **one arc growing from a fixed origin** —
urgency is encoded as arc *length*. `ApproachContract` encodes a different
question: **where is the train, positionally, relative to the station?** A train
close to departure renders as an LED close to a fixed anchor point; a train far
out renders further away. Arriving trains visually *approach* the anchor over
time, rather than an arc visually *shrinking*.

This is the display paradigm eventually intended to **replace** arc-based
contracts for the "which train, how close" job — not an addition alongside them.
Arc contracts aren't being deleted yet; this is where that migration starts.

---

## Core mechanism (one code path, not two)

Single-direction and bidirectional layouts are **the same mechanism**, driven
by config, not two separate contracts:

| Config | Meaning |
|---|---|
| `ANCHOR_INDEX` | LED index of the anchor/station position on the strip |
| `ARM_A_LEN` | LEDs available outward from the anchor, direction A |
| `ARM_B_LEN` | LEDs available outward from the anchor, direction B |

- **Phase 1:** `ANCHOR_INDEX = 0`, `ARM_A_LEN = 20`, `ARM_B_LEN = 0` — single
  direction, arm B unused. Matches the 21-LED gift-jar strip (1 anchor + 20).
- **Phase 2:** `ANCHOR_INDEX = 10`, `ARM_A_LEN = 10`, `ARM_B_LEN = 10` —
  bidirectional. The index math genuinely is config-only, as originally
  promised — `_arm_target()` was written arm-generic from day one. What
  turned out **not** to be config-only: *which signals feed the two arms* is
  a real structural question (below), not just numbers.

**Uneven `NUM_LEDS` (no clean centre LED):** not a code problem — nothing
derives `ANCHOR_INDEX`/`ARM_A_LEN`/`ARM_B_LEN` from `NUM_LEDS`, they're
independent knobs. For an odd count (21, this build) they split evenly
(`10 | 1 | 10`). For an even count, just let the arms differ by one LED
(e.g. `ARM_A_LEN=10, ARM_B_LEN=9`) — imperceptible in practice. Deliberately
**not** building a multi-LED "wide anchor" mode for this: it would add real
render/index-math complexity (anchor-collision edge cases, a second anchor
width knob) to fix an asymmetry nobody would notice on a lit strip.

The anchor LED itself renders `ANCHOR_COLOR` at `ANCHOR_BRIGHTNESS` — always —
it never participates in train logic and is never overwritten by a train
position. `ANCHOR_BRIGHTNESS` is a multiplier *relative to* a normal "full"
position (`1.0`); real-hardware bring-up found colour alone wasn't a strong
enough visual cue for "this one is fixed" — `ANCHOR_BRIGHTNESS > 1.0` (default
`1.6`) makes it genuinely brighter than the ceiling everything else tops out
at, not just differently coloured. See the STATIC render path below for how
that's rendered without gamma reshaping.

## Position mapping

Reuses `LeaveSignal.ttls` as-is — no Stage 1 changes. New knob:

- `POSITION_MINUTES_PER_LED` — minutes-to-leave → LED offset from `ANCHOR_INDEX`
  along the relevant arm.
- A train whose computed offset exceeds its arm's length is **dropped** — same
  "uncatchable" precedent `time_to_leave` already establishes for trains inside
  `WALK_TO_STATION_MINS`. Just as an arc contract can't show a train further out
  than its geometry allows, an approach contract can't show one further out than
  the strip's physical arm length.

## Three independent brightness surfaces

**Terminology** (matches how this actually reads to a viewer, not an
arbitrary naming choice): **anchor** = the "0" reference point. **marker** =
every idle "tick" LED — the gaps on the thermometer, neither the anchor nor
the train. "Where the train is" isn't called a marker; it's just the train.

| Surface | Knob | Notes |
|---|---|---|
| The anchor (the "0") | `ANCHOR_BRIGHTNESS` | Multiplier *relative to* a normal "full" position (`1.0`) |
| The marker ticks (idle LEDs) | `MARKER_BRIGHTNESS` | Direct linear multiplier of `BRIGHTNESS` |
| Where the train is | *(none — see below)* | Renders at `BRIGHTNESS` directly, `mult=1.0`, once settled |

**The train deliberately has no brightness knob of its own.** An earlier
draft gave it one (`MARKER_BRIGHTNESS` meant something different then — the
train's own mult, independent of the idle-tick level, which was itself called
`FLOOR_BRIGHTNESS`). That was one axis too many: "where the train is" should
just mean "at `BRIGHTNESS`" — the same global ceiling everything else is
already scaled against. Three surfaces, three knobs (well, two — the train
reuses the existing one), not four.

The anchor LED renders `ANCHOR_COLOR` at `ANCHOR_BRIGHTNESS` — always — it
never participates in train logic and is never overwritten by a train
position. Real-hardware bring-up found colour alone wasn't a strong enough
visual cue for "this one is fixed" — `ANCHOR_BRIGHTNESS > 1.0` (default `1.6`)
makes it genuinely brighter than the ceiling everything else tops out at, not
just differently coloured. See the STATIC render path below for how that's
rendered without gamma reshaping.

## Marker ticks (idle state)

LEDs not currently representing a train (and not mid-crossfade) render at
`MARKER_BRIGHTNESS`, using a **separate `MARKER_COLOR`** — not a dimmed
version of the train's line color.

**Why a separate color, not dimming:** a dimmed *same*-color LED risks reading
as "a fainter, more-distant train" rather than "an empty slot" — the whole point
of positional encoding is that position *is* the distance signal, so brightness
must not also imply distance or the two axes fight each other. `MARKER_BRIGHTNESS`
is throwable to `0` for fully-off idle slots, independent of this color choice.

**The marker ticks are rendered STATIC, not through gamma+dither.** First
real-hardware bring-up on the 21-LED gift strip found the idle ticks
"sparkling" — visible multicolour flicker, not a smooth dim glow. Root cause:
at a low enough absolute brightness, each `MARKER_COLOR` channel lands under
one output code, so temporal dithering (which approximates a fractional value
by toggling between adjacent codes and averaging over time) has to toggle
*every frame* — and because each LED's R/G/B channels are deliberately
phase-staggered from each other (`_residual`'s decorrelation, so LEDs don't
flicker in lockstep), that toggling shows up as async per-channel colour
noise instead of a blended glow. Same root cause `docs/insights.md` §6
already hit with `EchoContract`'s dimmed secondary layer.

Dithering only pays for itself when a value is genuinely *changing*
frame-to-frame (it has something to average against). A marker tick never
changes — so it, the anchor, and a train (see the Chase transition below —
a train is now ALWAYS full-brightness or absent, never dim) all render
through `_write_frame`'s **STATIC** path: `level = BRIGHTNESS × mult`
directly, no `gamma()`, no dithering, plain truncation. Because
`MARKER_BRIGHTNESS` is a *linear* multiplier rather than gamma-shaped, it
needs to be picked so `MARKER_COLOR × BRIGHTNESS × MARKER_BRIGHTNESS` clears
at least ~1 output code per channel — too low and it truncates invisibly to
black instead of flickering.

## Chase transition between position updates

Position updates happen once per `LOOP_INTERVAL_SECS` tick (a train moves one
LED, or several, per update) — a hard cut between LED positions would read as
a "jump," not an approach. A moving highlight sweeps LED-by-LED from the old
position to the new one, one LED lit at a time — **always at full
brightness**, never dim. `_advance_arm(frame, arm, target, color, phase_ms)`
is the one place this lives; `render()` (phase 1) and `render_dual()`
(phase 2) both call it, once per arm.

**This replaced an earlier brightness/colour-blend crossfade** (fade the old
position down, the new position up, blending colour toward `MARKER_COLOR`
along the way). That design necessarily passed through low-brightness
intermediate values — and at low enough absolute brightness, temporal
dithering breaks down on this hardware (the *exact* failure mode the Marker
ticks section above already hit, and `docs/insights.md` §6 before that).
Real-hardware testing confirmed it: the transition's low point visibly
flickered — the same "withering" dithering artifact, now happening on a
genuinely animated pixel instead of a supposedly-static one, so it couldn't
be fixed the same way (rendering it STATIC would freeze the fade instead of
smoothing it). The fix wasn't a better fade curve; it was not fading
brightness at all. **CHASE never asks for anything between "off" and
"full"** — every touched LED is always a fully-populated 8-bit code, so
dithering is never *needed* during a transition, not just tuned to be less
visible.

- **One-LED hops (the common case — a train usually moves one LED per
  minute-tick) are a single sharp switch at the transition's midpoint:** the
  old position stays lit at full brightness for the first half of
  `TRANSITION_MS`, then the new position takes over for the second half. No
  overlap, no fade — binary, on the beat.
- **Multi-LED hops sweep through every intermediate LED in turn**, each
  getting an equal time-slice of `TRANSITION_MS`. A hop of `distance` LEDs
  gets `distance + 1` positions (including both endpoints), stepped via
  `step = min(distance, int(progress * (distance + 1)))` — this is what
  makes it read as *motion* rather than a colour change, and reuses the same
  chase-sequence idea `led_test.py`'s bring-up `chase()` already proved on
  this exact hardware.
- **Appearing from nothing or vanishing to nothing snaps instead of
  sweeping.** A train's first-ever tick has no prior LED to sweep *from*; a
  train that's no longer catchable has no target to sweep *to*. Both cases
  render immediately (`arm.sweep_from = None`) — there's no meaningful
  "motion" to represent when one endpoint doesn't exist.
- `progress` is driven off the **absolute `ticks_ms()` clock**, matching the
  seamless-breathing envelope pattern already established in
  `display-contract.md` (no per-interval snap-back).
- `TRANSITION_MS = 0` collapses every hop to a single-frame switch
  (`step` lands on the final position immediately) — useful for testing, or
  if the chase motion itself turns out not to be wanted.

---

## Relationship to existing primitives

Nothing here is new *math* — it's a new *arrangement* of existing primitives,
consistent with how `EchoContract` composed `hue_rotate` + `breathe_fn` rather
than inventing new render logic:

| Existing primitive | Reused for |
|---|---|
| `_write_frame()` (split off `_paint_layers`) | Compositing anchor + train position + marker ticks in one frame, one `np.write()`. Every ApproachContract entry uses the STATIC path — full brightness or off, never gamma/dither |
| `led_test.py`'s `chase()` idea | The sequential-LED-sweep pattern, already validated on this exact hardware during bring-up |
| absolute `ticks_ms()` phase pattern | Chase `progress`, same seamlessness guarantee as breathing envelopes |
| `_physical()` HAL seam | Untouched — `ApproachContract` only changes *what* index a train maps to, not how a logical index maps to a physical LED |

## Config additions

All `getattr`-defaulted, backward-compatible with existing `config.py`s that
don't set them (same pattern as every prior contract):

```
CONTRACT = "approach"
ANCHOR_INDEX = 0
ARM_A_LEN = 20
ARM_B_LEN = 0
ANCHOR_COLOR = (255, 200, 120)  # warm white/amber, distinct from LINE_COLOR + MARKER_COLOR
ANCHOR_BRIGHTNESS = 1.6         # >1.0 = brighter than a normal "full" position (STATIC, linear)
POSITION_MINUTES_PER_LED = 1
LINE_COLOR = (34, 139, 34)      # forest green — fixed, NOT urgency-banded (see below)
LINE_SATURATION = 1.0           # 1.0=unchanged; lower = a genuinely MUTED
#                                  (desaturated) LINE_COLOR — see below
MARKER_BRIGHTNESS = 0.15        # LINEAR multiplier (STATIC path) — idle ticks ONLY,
#                                  throwable to 0. NOT read by the chase transition —
#                                  a train is always full brightness or absent.
MARKER_COLOR = (80, 80, 80)     # dim neutral, NOT a dimmed LINE_COLOR
TRANSITION_MS = 4000            # chase duration, ms; 0 = instant single-frame switch
```

**`LINE_COLOR`, not urgency-banded `PALETTE`:** every other contract colours the
train by `classify(ttl)` (`URGENCY_THRESHOLDS` bands). `ApproachContract`
deliberately doesn't — distance-to-anchor already encodes urgency continuously,
so re-encoding the same signal in colour too would be the same "double
encoding" problem `MARKER_COLOR`-not-dimmed avoids above, just on the other
axis. Colour is freed up to mean something else: which line/train this is.
`LINE_COLOR` is a single fixed colour, not a per-line palette system (that's
still the deferred "line-color palettes" work below) — for the single-line
gift build this is one config constant.

**`LINE_SATURATION`: muted, not dimmed.** A request to make the train "a few
notches darker" turned out to already be available — mathematically, scaling
render brightness and scaling the base colour by the same factor are
identical under the STATIC path's linear `BRIGHTNESS × mult` — so a separate
"shade" knob operating the same way would be a redundant lever on the same
math, not a new capability. A genuinely **muted** colour (like real muted
signage greens) is a different transform: it reduces *saturation* — each
channel moves toward the colour's OWN max channel (toward grey), not toward
zero. `desaturate(color, saturation)` is the HSV-saturation counterpart to the
existing `hue_rotate(color, degrees)` (HSV-hue): same "shift one HSV axis,
hold the others" pattern `EchoContract`'s `hue_rotate` already established,
just the other axis. `LINE_SATURATION` is applied once, at
`ApproachContract.line_color`'s class-definition time (module load) — not
recomputed every frame, since it's a fixed transform of a fixed colour.

---

## Bidirectional (phase 2)

**Iteration 1 scope (this section):** one primary train per arm — two trains
showing simultaneously, one per direction. `N_TRAINS`-per-arm nesting (more
than one train per arm, on top of this) is iteration 2 — see "N trains per
arm" below; it composes with everything in this section unchanged, each arm
just gets a list of slots instead of a single one.

**What's genuinely new, not just config:**

1. **Two `LeaveSignal`s, not one.** `schedule.json` already has direction
   keys (e.g. `"a"`/`"b"`) for inbound/outbound — the natural feed for the
   two arms. New config: `DISPLAY_DIRECTION_B` — `None` (default) means
   single-direction, phase 1, completely unchanged. Set it to a second
   direction key and `main()`'s loop builds a second `LeaveSignal` (arm A
   still reads `DISPLAY_DIRECTION`, unchanged).
2. **Two independent chase state machines.** `_ArmState` (a small instance
   holding `index`/`color`/`sweep_from`/`transition_start`) replaced what
   used to be flat attributes directly on `ApproachContract`.
   `ApproachContract` now always holds two — `self._arm_a`, `self._arm_b` —
   so each direction's train chases on its own clock. `_advance_arm(frame,
   arm, target, color, phase_ms)` is the one place the chase logic lives;
   both `render()` (phase 1) and `render_dual()` (phase 2) call it, once per
   arm, so it exists exactly once regardless of how many arms are active.
3. **Two entry points, not one method with an optional argument.**
   `render(signal, phase_ms)` — phase 1, byte-identical to before.
   `render_dual(signal_a, signal_b, phase_ms)` — phase 2. Kept as two
   methods, not `render(signal, phase_ms, signal_b=None)`, so a phase-1
   config's code path can never be perturbed by phase-2 logic — there's
   nothing for it to accidentally touch. `render_for_interval()` picks
   which to call via `_render_dispatch()` (a small pure function, pulled out
   specifically so the *decision* is host-testable without touching the
   real-time frame loop, which isn't): `signal_b is not None and
   hasattr(contract, "render_dual")`. Every other contract, and phase-1
   ApproachContract configs, take the ordinary single-signal path — the
   `hasattr` check means passing `DISPLAY_DIRECTION_B` under a non-`approach`
   `CONTRACT` is silently ignored, not a crash.

**No index collision to resolve between arms.** Arm "a" only ever targets
`ANCHOR_INDEX + offset`; arm "b" only ever targets `ANCHOR_INDEX - offset`
(see `_arm_target`) — disjoint ranges by construction. Only the anchor index
itself could coincide with an arm's target, and the anchor is always painted
last regardless of how many arms are active, so it always wins.

## Physical orientation: which side is arm A vs arm B

Bidirectional raises a question single-direction never had to answer: given
the anchor sits in the middle, **which physical end of the strip is arm A
and which is arm B?** This is config *and wiring* dependent — not derivable
from the firmware alone.

**The one fact only your soldering determines:** physical LED index `0` is
whichever end you wired the data line (DIN) into. Nothing in software
changes this — `ANCHOR_INDEX`, `ARC_ORIGIN`, etc. all build on top of it,
none of them redefine it.

**What the firmware controls on top of that:** `_physical(logical)` maps a
*logical* index (what the render code computes) to that *physical* LED
number:

```python
def _physical(logical):
    if ARC_ORIGIN == "far":
        return NUM_LEDS - 1 - logical
    return logical
```

`ARC_ORIGIN` isn't "unused for a symmetric bidirectional layout" (an earlier
config comment claimed exactly that, and was wrong — corrected 2026-07-24)
— it decides which physical side each arm lands on. Worked example, matching
the actual gift-jar config (`NUM_LEDS=21`, `ANCHOR_INDEX=10`,
`ARM_A_LEN=ARM_B_LEN=10`, `ARC_ORIGIN="far"` → `physical = 20 - logical`):

| | Logical range | Physical range |
|---|---|---|
| Anchor | 10 | 10 (dead centre — self-symmetric, unaffected by `ARC_ORIGIN`) |
| Arm A (`DISPLAY_DIRECTION`) | 11–20 | **0–9 — the DIN end** |
| Arm B (`DISPLAY_DIRECTION_B`) | 0–9 | **11–20 — the far end** |

Flipping `ARC_ORIGIN` to `"near"` (`physical = logical`) swaps that
assignment — arm A moves to the far end, arm B to the DIN end. The anchor
never moves (its logical index is symmetric under the flip whenever
`ANCHOR_INDEX` is the strip's exact centre).

**Verify on the actual jar, don't just trust the arithmetic against your real
soldering:** power up with only one direction showing a catchable train and
watch which physical end lights — the console already prints `ring: …` (arm
A) and `ring B: …` (arm B) lines to correlate against what you see. Once
confirmed, it's worth recording the result as a comment next to
`ARC_ORIGIN` in whichever `config.py` you're using — this is config+wiring
knowledge that's easy to forget and impossible to re-derive from the code
alone.

---

## N trains per arm (iteration 2)

Reuses `N_TRAINS` — the same knob the arc contracts (`SandTimerContract`,
`BreathingContract`) already use for nested-arc rendering — rather than a
new dedicated knob. Same concept, extended to this paradigm: how many
upcoming departures render simultaneously, soonest-first. Default `1` keeps
iteration-1 behaviour (one train per arm) exactly as before.

**Each arm now holds a LIST of `N_TRAINS` `_TrainState`s**, not one — every
simultaneous marker gets its own independent CHASE transition, on its own
clock, exactly like arm A and arm B already didn't interfere with each
other in the bidirectional case. `_advance_arm(frame, slots, signal,
arm_len, direction, base_color, phase_ms)` maps `signal.ttls[:N_TRAINS]`
onto the slots (soonest-first → slot 0, 1, 2, …) and advances/paints each
via `_advance_train` — the exact function every single-train case already
used, called once per slot instead of once per arm.

**Differentiating multiple simultaneous markers: hue, never dimming.**
Every other contract that nests trains (`SandTimerContract`,
`BreathingContract`) dims secondary layers via `BACKGROUND_BRIGHTNESS` — but
`docs/insights.md` §6 already found that breaks at low absolute brightness
on this hardware, which is the exact reason `EchoContract` differentiates by
hue instead, and the exact reason the CHASE transition above exists (every
train is *always* full brightness — dimming a slot here would silently undo
that). So `ApproachContract` follows `EchoContract`'s precedent: slot 0 (the
primary) renders `LINE_COLOR` unshifted; every slot beyond it is hue-rotated
via `_layer_hue_shift(i)` (`SECONDARY_HUE_SHIFT_DEG` per index — the same
knob, same formula `EchoContract` already uses). All markers stay full
brightness regardless of rank.

**Index collisions between slots resolve the same way `_paint_layers`
already does:** slots are advanced/painted in *reverse* order (last slot
first) so slot 0 is painted last and wins any overlap — the closest train
always takes visual priority over a further-out one landing on the same LED.

**Accepted simplification: no cross-tick train identity.** Stage 1
(`LeaveSignal`) is deliberately ephemeral — rebuilt from scratch every tick,
no persistent identity for "this specific train" (see
`docs/contracts/display-contract.md`'s Stage 1 design). "Slot 0" means
"whichever train is currently closest," not a specific physical train. If
the current primary departs and the former rank-1 train becomes rank-0,
slot 0's CHASE animates from the old primary's position to wherever that
train already was, rather than continuing rank-1's own animation in place.
This only matters in the moment a train departs and ranks shift — real
per-train identity tracking (e.g. keying trains by scheduled departure time
across ticks) would be a bigger structural change than "N trains, set in
config" scoped for this iteration. Revisit if it reads as jarring on
hardware.

---

## Explicitly deferred (not this contract's job yet)

- Cross-tick train identity for N_TRAINS (see the simplification noted above)
- Line-color palettes / metro-line static color scheme
- IMU tap/shake interaction layer
- NFC / provisioning of any kind
