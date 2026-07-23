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
- **Phase 2 (later):** `ANCHOR_INDEX = 10`, `ARM_A_LEN = 10`, `ARM_B_LEN = 10` —
  bidirectional, same render logic, just different config. This is why the
  mechanism must be arm-generic from the start: phase 2 should require zero
  contract-logic changes, only a config edit — same portability property the
  existing multi-train (`N_TRAINS`) and board-portability (`LED_PIN`) work
  established elsewhere in this codebase.

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
changes — so it, the anchor, and a train position that's finished crossfading
all render through `_write_frame`'s **STATIC** path instead: `level =
BRIGHTNESS × mult` directly, no `gamma()`, no dithering, plain truncation.
Only a pixel mid-crossfade (genuinely animating this frame) uses the
**ANIMATED** path (`gamma()` + dithering). Because `MARKER_BRIGHTNESS` is now
a *linear* multiplier rather than gamma-shaped, it needs to be picked so
`MARKER_COLOR × BRIGHTNESS × MARKER_BRIGHTNESS` clears at least ~1 output code
per channel — too low and it truncates invisibly to black instead of flickering.

## Crossfade between position updates

Position updates happen once per `LOOP_INTERVAL_SECS` tick (a train moves one
LED, or several, per update) — a hard cut between LED positions would read as a
"jump," not an approach. Implemented as instance state on `ApproachContract`
(the last-rendered index + when it changed), not a bespoke one-off: `_paint_layers`
was refactored to split off `_write_frame(frame)` — the shared gamma/dither/
`np.write()` tail — so `ApproachContract` can build a frame directly (per-LED
positions, not arc lengths) and still go through the same render seam every
other contract uses.

- Old position ramps toward `LINE_FADE_FLOOR` while the new position ramps up
  to `1.0` (full `BRIGHTNESS`, the same "settled" level a train always renders
  at), both driven by the same `progress` value on inverse curves — one linear
  interpolation, two directions. Colour still lerps toward `MARKER_COLOR` (so
  a disappearing train visually "sinks into" the idle look), but the
  **brightness** endpoints are `LINE_FADE_FLOOR`/`1.0` — a fully separate axis
  from `MARKER_BRIGHTNESS`.
  **This wasn't the original design** — an earlier draft reused one shared
  constant as both the idle-tick level AND the crossfade's dim endpoint, and
  real-hardware tuning found that coupling actively fighting itself: retuning
  the ambient tick level for the right idle look also dragged the train's
  fade dynamic range along with it, with no way to adjust one without the
  other. Splitting them was the fix — `MARKER_BRIGHTNESS` now *only* governs
  genuinely idle ticks (the `_write_frame` STATIC baseline); the train's own
  fade never reads it.
  - One side effect worth knowing: because the colour lerp (gray `MARKER_COLOR`
    → whatever hue `LINE_COLOR` is) runs independently of the brightness
    ramp, a single R/G/B channel isn't guaranteed to rise/fall monotonically
    mid-fade if that channel happens to be brighter in `MARKER_COLOR` than in
    `LINE_COLOR` (e.g. forest green's R and B are dimmer than a neutral gray
    marker's) — *total* brightness still ramps monotonically, just not
    necessarily every channel in isolation. In practice this is a small,
    brief overshoot on one or two channels near the end of the fade, not a
    visible colour flash — flag it if it ever reads as one on hardware.
- `progress` is driven off the **absolute `ticks_ms()` clock**, matching the
  seamless-breathing envelope pattern already established in
  `display-contract.md` (no per-interval snap-back).
- Runs the existing perceptual `gamma()` curve over the fade, not a linear
  ramp — this is what makes the motion read as organic rather than mechanical,
  same rationale as `gamma()`'s existing role smoothing dim-end banding.
- No timing pressure (updates are once-per-minute-tick), so `TRANSITION_MS` can
  run several seconds — prioritize smoothness over speed.

---

## Relationship to existing primitives

Nothing here is new *math* — it's a new *arrangement* of existing primitives,
consistent with how `EchoContract` composed `hue_rotate` + `breathe_fn` rather
than inventing new render logic:

| Existing primitive | Reused for |
|---|---|
| `_write_frame()` (split off `_paint_layers`) | Compositing anchor + train position + marker ticks in one frame, one `np.write()` |
| `gamma()` | Perceptual shaping of the crossfade brightness ramp — ANIMATED path only, see Marker ticks section above |
| `lerp_color()` | Colour half of the crossfade (train color ↔ `MARKER_COLOR`) |
| absolute `ticks_ms()` phase pattern | Crossfade `progress`, same seamlessness guarantee as breathing envelopes |
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
LINE_FADE_FLOOR = 0.3           # dim end of the train's OWN crossfade — independent
#                                  of MARKER_BRIGHTNESS, see "Crossfade" above
MARKER_BRIGHTNESS = 0.15        # LINEAR multiplier (STATIC path) — idle ticks ONLY,
#                                  throwable to 0. NOT read by the train's crossfade.
MARKER_COLOR = (80, 80, 80)     # dim neutral, NOT a dimmed LINE_COLOR
TRANSITION_MS = 4000            # crossfade duration, ms; 0 = instant jump
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

## Explicitly deferred (not this contract's job yet)

- Line-color palettes / metro-line static color scheme
- IMU tap/shake interaction layer
- NFC / provisioning of any kind
- Dual-train interaction tuning on the bidirectional (phase 2) layout
