# Wake / sleep interaction layer (IMU tap gestures)

**Status:** implemented on `feature/wake-interaction-layer`, host-tested,
**not yet on real hardware and not yet enabled by default.** No IMU is
physically wired, so `_imu_tap_detected()` is a stub that always returns
`False` — every class/function around it is real, working, tested code;
only the actual sensor read is a placeholder. Gated behind
`WAKE_INTERACTION_ENABLED` (default `False`, see § Safety gate below) so
existing deployments (e.g. `config_friend1.py`, no IMU) are completely
unaffected. Extends the boot ceremony (`docs/contracts/startup-sequence.md`)
and continues the parked "IMU shake to adjust brightness" idea
(`docs/insights.md` §5).

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
cue in `EXTEND_CONFIRM_COLOR` (defaults to `STARTUP_COLOR` — ties "more time"
back to the boot ceremony's own colour language rather than introducing a
fourth colour concept).

**Implementation deviation from the original proposal, worth naming:** this
doc originally proposed an ANIMATED `pulse()`/`breathe()` envelope for the
confirmation. What actually got built is the same non-blocking `_StatusMessage`
overlay `led-status-messages.md`'s quiet-hours and no-data acknowledgments
use — a solid STATIC-path single LED held for `EXTEND_CONFIRM_MS`, not an
animated pulse. Two reasons: (1) one shared mechanism for every brief
acknowledgment (quiet-tap, no-data, extend) is simpler to reason about and
test than three; (2) a *blocking* animated pulse would stall tap
classification and the schedule-refresh check for its duration, the same
problem the boot burst already accepts (briefly, at boot/wake — a much
rarer event) but not worth accepting on every double-tap. `EXTEND_CONFIRM_MS`
(default `600`) is a new config knob this introduced, not in the original
proposal below.

## Wake ceremony (ASLEEP → AWAKE) reuses the boot ceremony, doesn't rebuild it

`_play_startup_burst()` is already a generic "all LEDs, quick rise, slow
decay" primitive with no WiFi/NTP dependency baked into it — reusable as-is
for the wake-from-sleep cue. The loading-circle-spin stage doesn't apply
here (WiFi's already connected, nothing to wait on) — waking from sleep is
just the burst, not the full three-stage boot sequence.

## Architecture

Not a `DisplayContract` — same reasoning as the boot ceremony: this is
cross-cutting state that *gates* whichever contract is active, not a
rendering strategy itself.

**Implemented as a second, separate main-loop function, not a modification of
the existing one.** `main()` now branches on `WAKE_INTERACTION_ENABLED`:
`False` (default) runs `_run_classic_loop()` — the *original* loop, moved
but byte-for-byte unchanged; `True` runs the new `_run_interactive_loop()`.
This was a deliberate safety choice beyond what this doc originally
specified — see § Safety gate below.

`_run_interactive_loop()` is the cooperative super-loop the concurrency
discussion settled on: one `FRAME_MS`-paced tick drives a slow, elapsed-time-
gated schedule refresh (~`LOOP_INTERVAL_SECS`) AND tap classification AND
rendering, all in the same loop — no RTOS, no threads. "Should the display
render right now?" composes `is_quiet()`'s existing gate with the new
`_WakeState.awake` flag: quiet hours and asleep are two independent reasons
to render dark, checked together each tick.

## Implemented pieces

| Concept (from this doc) | Actual name in `main.py` |
|---|---|
| Tap classifier | `_TapClassifier` (class; `.advance(now_ms, tap_edge)` → `"single"`/`"double"`/`None`) |
| Wake state | `_WakeState` (class; `.wake()`, `.sleep()`, `.is_expired()`) |
| Status-message overlay (shared with `led-status-messages.md`) | `_StatusMessage` (class; `.show()`, `.active()`) |
| Precedence dispatch | `_classify_wake_response(is_quiet_now, tap_event, currently_awake)` |
| No-data check | `_all_signals_hidden(signal, signal_b)` |
| Secondary action (default) | `_cycle_brightness()`, dispatched via `_run_secondary_action()` |
| Real sensor read | `_imu_tap_detected()` — **stub, always returns `False`** |

## Safety gate: `WAKE_INTERACTION_ENABLED`

Not in the original design — added during implementation once it became
clear this feature can make things *worse* than doing nothing, unlike the
boot ceremony (which was explicitly decided not to need a toggle). With
`_imu_tap_detected()` stubbed to always return `False`, enabling this
unconditionally would mean: boot wakes the display as designed, the
`WAKE_MINUTES` countdown runs down exactly as designed, and then the display
goes `ASLEEP` **forever**, because nothing can ever wake it again. For
`config_friend1.py` (no IMU wired), that's a real regression — a jar that
goes permanently dark after 30 minutes with no recourse but a power-cycle.
`WAKE_INTERACTION_ENABLED` (default `False`) keeps every existing deployment
on the untouched classic loop until a real sensor read exists to back it up.

## Reusable primitives (nothing new at the math layer, again)

| Need | Existing primitive |
|---|---|
| Wake-from-sleep cue | `_play_startup_burst()`, as-is (blocking, ~2.3s) |
| Brief acknowledgments (extend, and the two in `led-status-messages.md`) | `_StatusMessage` — one shared, non-blocking mechanism (see the Confirmation flash section's deviation note above) |
| "Should the display be dark right now" gate | `is_quiet()` composed with `_WakeState.awake` |
| Fast tick for IMU polling + rendering | `_run_interactive_loop()`'s own `FRAME_MS`-paced loop |

## Implemented config

```
WAKE_INTERACTION_ENABLED = False        # safety gate — see above; must be
                                          #   True to use any of this at all
WAKE_MINUTES = 30              # active-display window after any wake/extend trigger
DOUBLE_TAP_WINDOW_MS = 400     # max gap between two taps to count as a double-tap
                                #   — GUESS, needs tuning against the real sensor
TAP_THRESHOLD = 2.0            # accelerometer magnitude threshold for "a tap
                                #   happened" — UNTESTED GUESS; _imu_tap_detected()
                                #   doesn't even read this yet (still stubbed)
SECONDARY_ACTION = "brightness_cycle"   # pluggable — what a single tap while
                                          #   AWAKE does
BRIGHTNESS_PRESETS = (0.15, 0.35, 0.6)  # default SECONDARY_ACTION's levels
EXTEND_CONFIRM_COLOR = STARTUP_COLOR    # reuse — ties "more time" to the boot
                                          #   ceremony's own colour language
EXTEND_CONFIRM_MS = 600                 # new — see the deviation note above
```

## Testability

`_TapClassifier`, `_WakeState`, `_StatusMessage`, `_classify_wake_response`,
`_all_signals_hidden`, and `_cycle_brightness`/`_run_secondary_action` are
all pure and host-tested (27 tests, `tests/test_wake_interaction.py`) — same
"separate the decision logic from the real-time loop" split
`_render_dispatch`/`_startup_burst_mult` already established. Reading the
actual IMU over I2C is **not** host-testable — same hardware-I/O limitation
every other real-time piece in this codebase already has (`connect_wifi()`'s
poll, `_play_startup_burst()`, etc.) — and neither is
`_run_interactive_loop()` itself, for the same reason.

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
