# Wake / sleep interaction layer (IMU tap gestures)

**Status:** design note — not yet implemented. No IMU is physically wired
yet, so there's nothing to test against regardless; written now per request,
ahead of the hardware. Extends the boot ceremony
(`docs/contracts/startup-sequence.md`) and continues the parked "IMU shake to
adjust brightness" idea (`docs/insights.md` §5).

**Motivated by real observations from Qi bring-up (2026-07-25), not
speculation:**

- **Thermal reality.** Hours of continuous full-power Qi transfer heats the
  glass enough that a Belkin charger's own thermal protection cuts out.
  Running the display for a bounded window instead of indefinitely reduces
  continuous draw — a genuine mitigation, not just a UX nicety.
- **"Off 80% of the time" is the actual desired aesthetic, not a
  compromise.** Placing the jar on a Qi pad is itself an intentional "I want
  this on" action — nobody accidentally sets a jar on a charging pad. Power
  arriving and a deliberate tap are equivalent wake triggers for exactly this
  reason.
- **The boot ceremony turned out to be something worth re-triggering on
  purpose**, not just a one-time technical formality — "lean into that"
  rather than treat repeated re-triggering as an accidental side effect of
  power-cycling.
- **A single tap can't carry two meanings on its own.** The first pass at
  this idea ("tap extends the window") turned out to be too simple on
  reflection — a tap while already awake should do something *else*
  (a quick secondary action), and *extending* needs its own gesture plus a
  confirmation, since silently extending with no feedback is indistinguishable
  from the tap not registering at all.

---

## The state machine

Two states: **AWAKE** (rendering normally, a countdown running) and
**ASLEEP** (all LEDs off, waiting for a wake trigger).

```
        power-on / boot ─────────────────┐
                                          ▼
   ┌─────────────────────────────────────────┐
   │                  AWAKE                    │◄──── double-tap: EXTEND
   │   ACTIVE_CONTRACT renders normally.        │        (reset the countdown +
   │   Countdown: WAKE_MINUTES since the        │         confirmation flash)
   │   last wake/extend trigger.                │
   └──────────────┬──────────────────────────┬─┘
                  │ countdown expires          │ single-tap: SECONDARY ACTION
                  ▼                            │  (e.g. cycle a brightness
   ┌─────────────────────────────┐             │   preset — does NOT touch
   │           ASLEEP             │             │   the countdown)
   │   all LEDs off, no render    │◄────────────┘
   └───────────────┬───────────────┘
                    │ tap (single or double — no ambiguity here, see below)
                    ▼
              Replay a wake ceremony (reuses _play_startup_burst as-is).
              Countdown = WAKE_MINUTES. → AWAKE
```

Boot always enters AWAKE directly — a fresh boot already *is* a wake trigger
for a Qi-placed device (see the motivation above), and the existing boot
ceremony (`run_startup_sequence()`) is unchanged.

## What each gesture does — state-dependent, not fixed

| State | Gesture | Effect |
|---|---|---|
| ASLEEP | tap (single or double) | Wake: replay the ceremony, countdown = `WAKE_MINUTES`, → AWAKE. No ambiguity to resolve here — there's no "current window" to extend while asleep, so both classify the same |
| AWAKE | single tap | Fire the **secondary action** (below) — does NOT touch the countdown |
| AWAKE | double tap | **Extend**: countdown = `WAKE_MINUTES` again + a confirmation flash |

The same physical gesture (a single tap) means different things depending on
current state — a common, reasonable pattern for a device with one input and
more than one thing it might mean.

## Tap classification: why single vs. double needs its own state machine

A single accelerometer spike isn't self-classifying. You can't know "was
that the whole gesture, or the first half of a double-tap" until either a
second spike arrives within a window, or the window elapses with nothing
else — the same logic behind mouse double-click detection. After tap #1:
wait up to `DOUBLE_TAP_WINDOW_MS`; a second tap inside that window →
**double**; the window elapsing with nothing else → **single**.

**Real cost, worth naming rather than hiding:** this means a single-tap
action can't fire until `DOUBLE_TAP_WINDOW_MS` after the physical tap — it
is *not* instant the way a bare "tap to wake" (no second gesture to
disambiguate against) would be. That earlier ~50ms "human-ish instant"
latency conversation assumed a single, unambiguous gesture; supporting two
gestures on one sensor trades away single-tap's instant feel in exchange for
having both. This is the direct cost of the richer design over the simpler
one, not a regression to fix.

## The secondary action — deliberately left pluggable

What a single tap should *do* while awake wasn't settled ("change station,
brightness cycle etc." were both floated) — and doesn't need to be, to build
the mechanism itself. Architecturally: single-tap-while-awake fires one
generic hook; *what that hook does* is a separate, swappable decision, same
spirit as `CONTRACTS`' registry pattern for display strategies.

**Proposed default for this pass** (concrete, useful today, low-risk):
cycle through `BRIGHTNESS_PRESETS` (e.g. `(0.15, 0.35, 0.6)`), wrapping
around. The visible brightness change *is* the confirmation — no separate
flash needed for this particular action, since the effect is the feedback.
Swapping in a different `SECONDARY_ACTION` later (cycle `CONTRACT`, cycle
`LINE_COLOR`, cycle which schedule direction is primary) shouldn't require
touching the tap-classification state machine at all.

## Confirmation flash (EXTEND only)

Silently extending the countdown with zero feedback is indistinguishable
from the double-tap not registering at all — worth a distinct, deliberate
cue: one quick bright pulse (reusing `pulse()`/`breathe()`, ANIMATED path,
since it's genuinely changing frame-to-frame) in `STARTUP_COLOR` — ties "more
time" back to the boot ceremony's own colour language rather than
introducing a fourth colour concept.

## Wake ceremony (ASLEEP → AWAKE) reuses the boot ceremony, doesn't rebuild it

`_play_startup_burst()` is already a generic "all LEDs, quick rise, slow
decay" primitive with no WiFi/NTP dependency baked into it — reusable as-is
for the wake-from-sleep cue. The loading-circle-spin stage doesn't apply
here (WiFi's already connected, nothing to wait on) — waking from sleep is
just the burst, not the full three-stage boot sequence.

## Architecture

Not a `DisplayContract` — same reasoning as the boot ceremony: this is
cross-cutting state that *gates* whichever contract is active, not a
rendering strategy itself. Composes with the existing `is_quiet()` gate at
the same decision point in `main()`'s loop: "should the display render right
now?" becomes `not is_quiet(now) and awake`. Two independent reasons to be
dark, unified at one check.

Requires the same restructuring the boot ceremony already needed: IMU
polling has to run on a fast, `FRAME_MS`-paced tick, independent of the slow
`LOOP_INTERVAL_SECS` schedule-refresh cadence — a cooperative super-loop
(elapsed-time-gated tasks in one loop), not an RTOS or threads, per the
concurrency discussion this design followed from. This doc doesn't introduce
a *new* concurrency requirement — it's the same fast tick the boot ceremony
and animated contracts already run on, now with a second consumer (tap
classification) reading from it.

## Reusable primitives (nothing new at the math layer, again)

| Need | Existing primitive |
|---|---|
| Wake-from-sleep cue | `_play_startup_burst()`, as-is |
| Confirmation pulse | `pulse()` / `breathe()` |
| "Should the display be dark right now" gate | Extends `is_quiet()`'s existing gate |
| Fast tick for IMU polling | The same `FRAME_MS`-paced loop `render_for_interval` already runs for animated contracts |

## Proposed config

```
WAKE_MINUTES = 30              # active-display window after any wake/extend trigger
DOUBLE_TAP_WINDOW_MS = 400     # max gap between two taps to count as a double-tap
                                #   — GUESS, needs tuning against the real sensor
TAP_THRESHOLD = ...            # accelerometer magnitude threshold for "a tap
                                #   happened" — cannot be sanely guessed without
                                #   the physical IMU; do not hardcode a default
                                #   until bench-tested
SECONDARY_ACTION = "brightness_cycle"   # pluggable — what a single tap while
                                          #   AWAKE does
BRIGHTNESS_PRESETS = (0.15, 0.35, 0.6)  # default SECONDARY_ACTION's levels
EXTEND_CONFIRM_COLOR = STARTUP_COLOR    # reuse — ties "more time" to the boot
                                          #   ceremony's own colour language
```

## Testability

Tap **classification** (single vs. double, given a stream of timestamped raw
tap events) is pure and host-testable — same "separate the decision logic
from the real-time loop" split `_render_dispatch`/`_startup_burst_mult`
already established. Wake-state transitions (AWAKE/ASLEEP, countdown expiry)
are similarly testable as a pure function of `(now, last_wake_at,
WAKE_MINUTES)`. Reading the actual IMU over I2C is **not** host-testable —
same hardware-I/O limitation every other real-time piece in this codebase
already has (`connect_wifi()`'s poll, `_play_startup_burst()`, etc.).

## Decisions (confirmed 2026-07-25)

1. ~~Quiet hours vs. a deliberate tap.~~ **Resolved, and grew into its own
   doc:** quiet hours always wins (the display never fully wakes during
   quiet hours), but a tap during quiet hours isn't ignored either — it gets
   a small, deliberate acknowledgment. This turned out to need a shared
   vocabulary alongside the existing WiFi-failure error state and a new
   "woke up to no data" case — see
   **`docs/contracts/led-status-messages.md`**, which this doc now defers to
   for anything that isn't the AWAKE/ASLEEP render itself.
2. **Going to sleep: instant cut to black**, matching `is_quiet()`'s existing
   behaviour. A "goodnight" fade was considered and explicitly deferred —
   parked as a future UX area, not because it's a bad idea, but because a
   naive brightness lerp risks the exact low-brightness-blend pattern CHASE
   was built to eliminate, and it doesn't block anything else here.
3. **`SECONDARY_ACTION` confirmed: cycle `BRIGHTNESS_PRESETS`.** No change
   from the proposed default.
4. **`TAP_THRESHOLD` / `DOUBLE_TAP_WINDOW_MS`** — still genuinely open, no
   sane default exists without the physical LSM6DSV16X in hand. Ship a
   clearly-flagged guess when implementation starts, same treatment
   `STARTUP_BURST_MS`/`STARTUP_FADE_MS` got.
