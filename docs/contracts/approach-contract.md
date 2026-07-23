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

## Floor / idle state

LEDs not currently representing a train (and not mid-crossfade) render at
`FLOOR_BRIGHTNESS`, using a **separate `FLOOR_COLOR`** — not a dimmed version of
the train's line color.

**Why a separate color, not dimming:** a dimmed *same*-color LED risks reading
as "a fainter, more-distant train" rather than "an empty slot" — the whole point
of positional encoding is that position *is* the distance signal, so brightness
must not also imply distance or the two axes fight each other. `FLOOR_BRIGHTNESS`
is throwable to `0` for fully-off idle slots, independent of this color choice.

**The floor is rendered STATIC, not through gamma+dither.** First real-hardware
bring-up on the 21-LED gift strip found the floor "sparkling" — visible
multicolour flicker, not a smooth dim glow. Root cause: at a low enough
absolute brightness, each `FLOOR_COLOR` channel lands under one output code,
so temporal dithering (which approximates a fractional value by toggling
between adjacent codes and averaging over time) has to toggle *every frame* —
and because each LED's R/G/B channels are deliberately phase-staggered from
each other (`_residual`'s decorrelation, so LEDs don't flicker in lockstep),
that toggling shows up as async per-channel colour noise instead of a blended
glow. Same root cause `docs/insights.md` §6 already hit with `EchoContract`'s
dimmed secondary layer.

Dithering only pays for itself when a value is genuinely *changing*
frame-to-frame (it has something to average against). The floor never
changes — so it, the anchor, and a train position that's finished crossfading
all render through `_write_frame`'s **STATIC** path instead: `level =
BRIGHTNESS × mult` directly, no `gamma()`, no dithering, plain truncation.
Only a pixel mid-crossfade (genuinely animating this frame) uses the
**ANIMATED** path (`gamma()` + dithering). Because `FLOOR_BRIGHTNESS` is now a
*linear* multiplier rather than gamma-shaped, it needs to be picked so
`FLOOR_COLOR × BRIGHTNESS × FLOOR_BRIGHTNESS` clears at least ~1 output code
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

- Old position ramps toward `FLOOR_BRIGHTNESS`/`FLOOR_COLOR` while the new
  position ramps up to full, both driven by the same `progress` value on
  inverse curves — one linear interpolation, two directions.
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
| `_write_frame()` (split off `_paint_layers`) | Compositing anchor + train positions + floor LEDs in one frame, one `np.write()` |
| `gamma()` | Perceptual shaping of the crossfade brightness ramp — ANIMATED path only, see Floor section above |
| `lerp_color()` | Colour half of the crossfade (train color ↔ `FLOOR_COLOR`) |
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
ANCHOR_COLOR = (255, 200, 120)  # warm white/amber, distinct from LINE_COLOR + FLOOR_COLOR
ANCHOR_BRIGHTNESS = 1.6         # >1.0 = brighter than a normal "full" position (STATIC, linear)
POSITION_MINUTES_PER_LED = 1
LINE_COLOR = (34, 139, 34)      # forest green — fixed, NOT urgency-banded (see below)
FLOOR_BRIGHTNESS = 0.15         # LINEAR multiplier (STATIC path) — throwable to 0
FLOOR_COLOR = (80, 80, 80)      # dim neutral, NOT a dimmed LINE_COLOR
TRANSITION_MS = 4000            # crossfade duration, ms; 0 = instant jump
```

**`LINE_COLOR`, not urgency-banded `PALETTE`:** every other contract colours the
train by `classify(ttl)` (`URGENCY_THRESHOLDS` bands). `ApproachContract`
deliberately doesn't — distance-to-anchor already encodes urgency continuously,
so re-encoding the same signal in colour too would be the same "double
encoding" problem `FLOOR_COLOR`-not-dimmed avoids above, just on the other
axis. Colour is freed up to mean something else: which line/train this is.
`LINE_COLOR` is a single fixed colour, not a per-line palette system (that's
still the deferred "line-color palettes" work below) — for the single-line
gift build this is one config constant.

---

## Explicitly deferred (not this contract's job yet)

- Line-color palettes / metro-line static color scheme
- IMU tap/shake interaction layer
- NFC / provisioning of any kind
- Dual-train interaction tuning on the bidirectional (phase 2) layout
