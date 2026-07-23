# Contract: `ApproachContract` (positional / approach display)

**Status:** design note — not yet implemented. Phase 1 build in progress on
`feature/positional-display`; see `dev-status.md` for the active dev plan and
test sequence. This doc is the durable concept reference (the *what and why*),
kept separate from the dev plan (the *when and how*) per the existing
`display-contract.md` / `dev-status.md` split.

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

The anchor LED itself renders `ANCHOR_COLOR` at full brightness, always — it
never participates in train logic and is never overwritten by a train position.

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

## Crossfade between position updates

Position updates happen once per `LOOP_INTERVAL_SECS` tick (a train moves one
LED, or several, per update) — a hard cut between LED positions would read as a
"jump," not an approach. `_transition(from_idx, to_idx, progress)` is a new
primitive, composing with the existing `_paint_layers` render seam rather than
a bespoke one-off path.

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
| `_paint_layers` | Compositing anchor + train positions + floor LEDs in one frame |
| `gamma()` | Perceptual shaping of the crossfade ramp |
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
ANCHOR_COLOR = ...              # distinct from train color
POSITION_MINUTES_PER_LED = 1
FLOOR_BRIGHTNESS = 0.05         # throwable to 0
FLOOR_COLOR = ...               # dim neutral, NOT a dimmed line color
TRANSITION_MS = ...             # crossfade duration
```

---

## Explicitly deferred (not this contract's job yet)

- Line-color palettes / metro-line static color scheme
- IMU tap/shake interaction layer
- NFC / provisioning of any kind
- Dual-train interaction tuning on the bidirectional (phase 2) layout
