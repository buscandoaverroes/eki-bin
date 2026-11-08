# Gesture envelope & interaction contract (IMU-driven)

**Status: Implemented (Layers 1-4 + terminal debug loop), mechanically
validated on real hardware.** `GESTURE_DEBUG_ENABLED` runs the whole
envelope — HAL, feature extraction, recognizer, scrollwheel — via
`make screen`, printing state transitions instead of touching LEDs; see
§10 for the confirmed-working gesture mapping. Evidence-based throughout —
every threshold is backed by real data in `docs/insights.md` §8-9, gathered
via the sandbox toolchain (`micropython/vibration_sandbox.py` /
`imu_test.py` / `handling_test.py` / `orientation_test.py` /
`gesture_sandbox.py`), not assumed.
**Not yet done:** real menu content (still placeholder), LED-wired
integration into the ambient display loop.

**Scope pivot (2026-08-05):** live testing exposed that every open problem
in §9/§10 (position disambiguation, flick-vs-handling) is *additional*
discrimination on top of tap-vs-noise — the one thing that was never
actually unreliable (95-98%, and 98.4% for tap-vs-all-pooled-handling-noise
via `energy` alone, see §11). This branch's actual goal was a minimal
working input (change the station display), not the full multi-gesture
envelope — §11 specifies that minimal contract as a deliberate
*specialization* of the architecture below, not a replacement for it, so
position/flip/flick stay available to re-enable later without a rewrite.

**Supersedes part of `docs/contracts/wake-interaction.md`, reuses the rest.**
That doc's tap-*count* axis (single vs. double tap, `TAP_THRESHOLD` /
`DOUBLE_TAP_WINDOW_MS`) turned out to be the wrong physical signal — §8/§9
found position and gesture-*type* far more reliable than counting taps.
Its state-machine architecture, the `WAKE_INTERACTION_ENABLED` safety-gate
pattern, `_StatusMessage` reuse, and bounded-window philosophy all remain
correct and are reused here, unchanged in spirit.

---

## 1. The core idea: gestures are abstracted, same pattern this project
   already trusts for output

`docs/insights.md` §2 established this project's central abstraction for
the *display* pipeline: `time → LeaveSignal (abstract) → DisplayContract
(render) → LEDs`. "What's the urgency?" is decoupled from "how do we show
it?" — swap the display strategy without touching the urgency logic, and
vice versa.

This doc applies the identical pattern to *input*:

```
raw IMU registers → Signal HAL → Feature extraction → Gesture Recognizer → GestureEvent (abstract) → Interaction State Machine → Action
```

**Gesture A doesn't mean "change the color."** It means `SELECT`, or
`SCROLL`, or `WAKE` — an abstract event. What that event *does* depends on
the current interaction state, exactly as `wake-interaction.md` already
established for its own single-tap ("the same physical gesture means
different things depending on current state"). This doc generalizes that
principle from one gesture to the whole envelope.

---

## 2. Layer 1 — tiny HAL (raw sensor access)

Mirrors the LED side's existing HAL seam (`docs/insights.md` §4: "the only
code touching `np[i]` today is `_paint`/`clear`"). On the input side, the
equivalent boundary is: **one function is the only code that touches
`i2c.readfrom_mem` for gesture purposes** — everything above it works with
plain `(t, x, y, z)` sample tuples, not registers.

This boundary already exists *informally*, duplicated four times, in the
sandbox scripts' `_read_accel_raw()` / `_read_accel_mg()`. Formalizing it
for the real firmware means one shared implementation instead of four
copies — the same consolidation the sandbox tools never needed (they're
deliberately standalone bring-up scripts, per their own headers), but the
real firmware does.

If the IMU chip ever changes, only this layer needs to.

## 3. Layer 2 — feature extraction (pure, host-testable)

Mirrors the `_render_dispatch` / `_classify_wake_response` split already
established: pure functions, given a fixed sample buffer, host-testable
without hardware. Given a raw sample window, compute the same engineered
features already validated in `scripts/prepare_tap_dataset.py` —
`peak_deviation_mg`, `ring_down_ms`, `energy`, `duration_ms`,
`num_crossings`, `spacing_mean_ms`, `spacing_stdev_ms`, `dominant_axis` —
but ported to MicroPython, running on-device from a live buffer instead of
post-hoc on the host. No numpy needed; every one of these is plain
arithmetic already proven dependency-free on the host side.

**Orientation is a separate, simpler path, not forced through this
machinery.** It's a steady-state axis+sign read (`orientation_test.py`'s
`_classify()`), not a windowed transient — no capture-and-classify step,
no hysteresis, no feature vector. Keep it its own code path.

## 4. Layer 3 — gesture recognizer, chosen per gesture by evidence, not dogma

This is the direct answer to "random forest or a light model or hardcoded"
— the honest answer is **it depends on the gesture, and §8/§9 already
measured which**:

| Gesture | Recognizer | Why |
|---|---|---|
| Flip/orientation | Hardcoded: dominant axis + sign | Visually unambiguous; nothing to learn |
| Tap presence @ base/shoulder | Hardcoded: magnitude threshold | 95-98%; simple and sufficient |
| Flick vs. soft tap | Hardcoded: magnitude threshold | 91-94%; simple and sufficient |
| Flick vs. hard handling | Hardcoded threshold, on `spacing_stdev_ms` | Magnitude alone capped ~80% — the fix was the *right feature*, not a fancier model |
| Position: shoulder vs. base | Hardcoded threshold (classifier tested, tied at ~81% either way) | Same finding as muji: a clean signal doesn't benefit from ML |

**Governing principle, already earned the hard way in §8/§9:** default to
a hardcoded threshold. Reach for a trained model only when a threshold
*measurably* fails **and** a specific feature combination is shown to fix
it — the one case that happened (rocking-bottle tap-count, 55%→91% via a
random forest on `spacing_mean_ms`/`spacing_stdev_ms`/`energy`) earned its
complexity by evidence, not by default. Every other gesture tested a
classifier and found it tied or worse than the simple threshold.

**If a future gesture genuinely needs a trained model on-device:** it must
be exported as something MicroPython can run cheaply — a hand-encoded
decision tree (a handful of `if`/`elif` on 2-3 features, taken from an
sklearn tree's learned splits), not a live scikit-learn dependency. No
gesture has needed this yet; noted so the constraint isn't discovered late.

## 5. Hardware capability flags — gestures tied to what's actually wired

Directly answers "Qi models don't get flip, some bottles may not get the
shoulder/base disaggregation." Same `getattr(config, "NAME", default)`
pattern every other knob in this project already uses, and the same
safety-gate precedent `WAKE_INTERACTION_ENABLED` set — a capability is off
by default until something concrete backs it up:

```python
GESTURE_FLIP_ENABLED = False       # requires wired (USB) power — flipping a
                                     #   Qi-mounted jar breaks inductive coupling
GESTURE_POSITION_ENABLED = False   # shoulder-vs-base disaggregation — ~81%
                                     #   even on a bottle it's tuned for; off by
                                     #   default, opt-in per physical unit
GESTURE_FLICK_ENABLED = True       # best-validated signal after tap presence —
                                     #   on by default
```

**Per-bottle calibrated thresholds belong in `config.py` too, not
hardcoded in `main.py`.** This is the concrete answer to §8's open
question ("where does calibration happen"): dev-time, via the same
sandbox tooling already built, baked into that physical unit's own
`config.py` at flash/gift time — matching the project's existing ~19-knob
philosophy, zero runtime complexity.

```python
TAP_TRIGGER_THRESHOLD_MG = 50             # cheap gate only, see §10
FLICK_MAGNITUDE_THRESHOLD_MG = 140
FLICK_SPACING_STDEV_THRESHOLD_MS = 5      # per-bottle
POSITION_THRESHOLD_MG = 151               # per-bottle, only read if
                                            #   GESTURE_POSITION_ENABLED
```

These are now real, derived-from-data values (chianti bottle, pooled
sandbox sessions) — not placeholders. Still per-bottle, though: re-derive
with `vibration_sandbox.py` + `scripts/analyze_taps.py` before flashing a
different physical unit, the same way display knobs get hand-tuned per jar.

## 6. Abstract gesture vocabulary — the events, not the actions

What the recognizer layer can emit, independent of what any of it *does*:

| Event | Source | Notes |
|---|---|---|
| `WAKE` | tap presence (base/shoulder) or flick | Momentary |
| `SELECT` | flick | Momentary — highest-confidence signal, used for the highest-stakes action (§8's risk-tiering finding) |
| `SCROLL(direction)` | tap-shoulder / tap-base, if `GESTURE_POSITION_ENABLED` | Momentary; direction only populated when the capability is on — otherwise `SCROLL` fires with no direction |
| `ORIENTATION_CHANGED(state)` | flip detector | **State, not a momentary event** — upright / horizontal / upside-down, read continuously |

## 7. Layer 4 — interaction paradigm (the "scrollwheel")

Sketch, not a spec — matches how `wake-interaction.md` deliberately left
its own secondary action open ("doesn't need to be [settled], to build the
mechanism itself"). Old-MP3-player-menu shape, per the original proposal:

```
ASLEEP ──WAKE──► GESTURE_MODE ──timeout──► back to ambient (no change)
                     │  ▲
              SCROLL │  │ SCROLL
                     ▼  │
              [cursor over option N]
                     │
                  SELECT
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     leaf action           submenu (repeat)
   (execute, then      (e.g. "brightness" →
    return to ambient)   a sub-list of levels)
```

LED position indicates cursor position in the option list (origin +
offset = selected index), mirroring the existing arc-position language the
display pipeline already uses elsewhere. `GESTURE_MODE` entry/exit needs
its own acknowledgment cues — extends `led-status-messages.md`'s existing
"acknowledge, don't stay silent" vocabulary rather than inventing a new
one. Bounded timeout back to ambient matches `WAKE_MINUTES`'s existing
bounded-window philosophy — `GESTURE_MODE` should not be a state you can
get stuck in.

**Deliberately unresolved here, same as wake-interaction.md's secondary
action was:** the real option list, submenu depth, and exact LED-position
mapping. Settling the mechanism doesn't require settling the menu content.

## 8. Relationship to existing docs

- **Supersedes** `wake-interaction.md`'s tap-count axis specifically
  (`TAP_THRESHOLD`, `DOUBLE_TAP_WINDOW_MS`, single-vs-double classification)
  — replaced by tap-position and gesture-type.
- **Reuses, unchanged**, from `wake-interaction.md`: the AWAKE/ASLEEP
  state machine shape, the `WAKE_INTERACTION_ENABLED` safety-gate pattern
  (generalized into the per-gesture capability flags in §5 above),
  `_StatusMessage` for brief acknowledgments, and the bounded-window
  philosophy.
- **Extends** `led-status-messages.md`'s confirmation vocabulary for
  `GESTURE_MODE` entry/exit cues.

## 9. Open items

- `grab_and_tap` is parked per `docs/insights.md` §9 — not in this
  envelope until its session-to-session inconsistency is understood.
- The menu/scrollwheel option list (§7/§10) is still placeholder
  (`("Item 1", "Item 2", "Item 3")`) — a product decision, not a hardware
  one, deliberately unresolved so the mechanism could be validated first.
- LED wiring: `GESTURE_MODE`'s cursor position, entry/exit
  acknowledgments, etc. aren't rendered anywhere yet — `main.py` only
  prints them today (§10). Integrating with the ambient display loop
  (`_run_interactive_loop` or a successor) is the next real step.
- The capture window (`_capture_gesture_window`) is a fixed
  `_GESTURE_WINDOW_MS` duration, not adaptive settling-detection like the
  sandbox tools' human-gated stop — a known simplification, revisit if
  recognizer accuracy in practice doesn't match the sandbox numbers.

**Resolved since the design was first written:** real threshold values now
exist (derived from the pooled chianti sandbox data, §5/§10 — no longer a
placeholder); feature extraction (§3) is ported to MicroPython and
cross-checked for numerical parity against real capture files; the whole
envelope is implemented and mechanically confirmed working via
`GESTURE_DEBUG_ENABLED`.

## 10. Implemented mapping (current, terminal-tested)

Two tools now exist for exercising this, with different purposes.
`GESTURE_DEBUG_ENABLED` + `make screen` runs the exact shipped code path in
`main.py` — the thing that matters is that this works, not that it's fast
to iterate on. `micropython/gesture_sandbox.py` (`import main`, same
led_sandbox.py pattern) reuses the real recognizer functions but keeps
trigger/capture *timing* locally tunable and prints the full feature dict
on every capture, not just the final classification — built specifically
because tuning timing by repeatedly editing `main.py` risks reintroducing
bugs into code that's supposed to be stable (see the dropped `return`
bug two rounds ago), and because `main.py`'s validated recognizer numbers
were never actually measured against its own trigger's timing — only
against the sandbox tools' human-armed, 240Hz-sampled captures.

Confirmed working via `GESTURE_DEBUG_ENABLED` + `make screen`, Pico 2W +
IMU only, no LEDs or WiFi:

| Your gesture | Gesture mode state | Result |
|---|---|---|
| **Tap** (shoulder or base) | inactive | **WAKE** — enters gesture mode, cursor → first item |
| **Flick** (hard strike) | inactive | **WAKE** — same as tap, either gesture works |
| **Tap at shoulder** | active | **SCROLL forward** (+1) |
| **Tap at base** | active | **SCROLL backward** (−1) |
| **Flick** | active | **SELECT** — confirms the item under the cursor, exits gesture mode |
| *(idle for `GESTURE_MODE_TIMEOUT_MS`)* | active | **TIMEOUT** — exits gesture mode, nothing selected |

Orientation runs on its own track, independent of the menu — it just
prints whenever the resting state changes (upright/horizontal/upside_down)
per §6's `ORIENTATION_CHANGED`, and doesn't wake, scroll, or select
anything today. If `GESTURE_POSITION_ENABLED` is off, every tap scrolls
forward regardless of where you tap (`_scroll_direction`'s stated fallback
in §6 already covered this).

**Timeout refreshes on scroll, found and fixed during real-hardware
testing.** The first implementation only set the idle-timeout clock at
`WAKE` and never touched it again — a long browsing session (several
scrolls, taking your time between them) could time out mid-browse purely
because the *session* ran past `GESTURE_MODE_TIMEOUT_MS`, not because the
*user* went idle. Fixed so `scroll()` refreshes the clock on every valid
interaction. Deliberately different from `_WakeState`'s `WAKE_MINUTES`
countdown, which does **not** auto-refresh — that's a power-budget
decision (the ambient display shouldn't silently stay lit indefinitely),
and extending it needs its own deliberate gesture (double-tap = EXTEND).
`GESTURE_MODE_TIMEOUT_MS` is an idle timeout on an active interaction, not
a power budget — the two timers look similar but answer different
questions, and conflating them was the bug.

**Second real-hardware bug, more consequential: `classify_tap_or_flick`
was silently rejecting almost every hard tap/flick, and position always
read "base" as a downstream symptom of the same bug, not a separate
problem.** Live testing (`gesture_sandbox.py`) showed shoulder taps never
scrolling — every hard hit came back `→ rejected as noise`. Root cause:
`spacing_stdev_ms` needs >= 3 crossings to compute at all, and the
original code treated "can't compute it" as automatic rejection. Checked
against the pooled handling-test data: **70% of real flicks and ~25% of
hard-handling events have fewer than 3 crossings** — the feature that
worked beautifully in the original statistical comparison (insights.md
§9's 100% figure) was implicitly computed only on the subset where it
*was* available, which turns out to be the minority case for flicks. In
practice this meant almost every hard event over `FLICK_MAGNITUDE_
THRESHOLD_MG` got killed before `classify_position` ever ran on it — only
weak, sub-threshold taps (which can only ever be "base," since they're
also below `POSITION_THRESHOLD_MG`) survived to be classified at all. One
bug explained both symptoms.

**Fix, and the honest ceiling found along the way:** when spacing_stdev
isn't computable, fall back to `num_crossings` (1 leans flick, 2+ leans
hard-handling) — the single best available feature in that regime, but
only ~80% on its own. Before shipping that as "good enough," checked
whether a classifier could do better: a random forest on every available
feature (peak magnitude, energy, crossings, ring-down, duration) scored
**80.7%** on the same pooled data — statistically the same as the single
feature. Unlike the rocking-bottle tap-count case (55%→91% by combining
features), this is a genuine ceiling with the current feature set, not a
"needs a smarter model" gap — confirmed by testing, not assumed. Also
recalibrated `FLICK_MAGNITUDE_THRESHOLD_MG` from 140 (calibrated against
body taps, median 50mg) to **328** (95.2%, calibrated against shoulder+base
taps specifically, median 128mg — where taps actually happen in this
envelope). The original number wasn't wrong on its own terms, it was
measured against the wrong comparison group.

## 11. V1 minimal contract — tap-or-noise, wake + cycle

**A specialization of Layers 1-4 above, not a different architecture.**
Same HAL (§2), same feature extraction (§3) — what narrows is Layer 3 (one
binary recognizer instead of the tap/flick/position table) and Layer 4
(one linear state instead of a cursor over a menu). `GESTURE_POSITION_
ENABLED` / `GESTURE_FLIP_ENABLED` / `GESTURE_FLICK_ENABLED` already exist
as capability flags for exactly this reason — v1 ships with all three
`False`, and re-enabling any of them later is a config change, not a
redesign. The abstract-event vocabulary (§6) and hardcoded-vs-model
principle (§4) both carry over unchanged.

**Why this scope, not the full envelope (§9's open problems):** every
open problem so far — position disambiguation, flick-vs-handling — is
*additional* discrimination layered on top of tap-vs-noise, which was
never actually the unreliable part (95-98% since the very first sandbox
sessions). This branch's actual goal is a minimal working input (change
the station display), matching a light switch's reliability bar: near-100%
for the one binary decision that matters, occasional misses acceptable,
false triggers not. A proper on-device ML classifier for richer,
multi-gesture input is a real idea worth pursuing — parked as future scope
(§9), not this branch's job.

**Recognizer — one function, one threshold, no model:**

```python
def classify_valid_input(features):
    """Deliberate touch vs. ambient handling — the ONLY distinction v1
    needs. energy alone: 98.4% (5/310 errors — 3 missed taps, 2 false
    triggers) across pooled tap sessions vs. pooled handling-noise sessions
    (pickup/carry/setdown/bump), not a single-session number. Does NOT
    distinguish tap from flick or classify position — GESTURE_POSITION_
    ENABLED/GESTURE_FLICK_ENABLED stay False for v1; classify_tap_or_flick/
    classify_position remain defined and tested, just unused here."""
    return features["energy"] < TAP_ENERGY_THRESHOLD
```

`TAP_ENERGY_THRESHOLD` ≈ 138000 (chianti-bottle value, same per-bottle
recalibration caveat as every other threshold in this doc).

**Latency forced a real design decision, not just a tuning knob.** The
recognizer needs the *full* capture window before `classify_valid_input`
can answer — truncating it to feel more instant was tried and rejected
with data, not assumed:

| Window | Accuracy |
|---|---|
| 1200ms (full) | ~94-98% |
| 300ms | 83.9% |
| 150ms | 80.6% |
| 50ms | 69.7% |

Degrades gracefully, not a cliff, but there's no short window that's both
fast and "light switch" accurate — a tap and the start of a handling event
look the same for their first ~100-150ms; what actually distinguishes them
is whether the signal *keeps going* (handling) or *settles* (tap), which
by definition takes time to observe. Confirmed this is a real tradeoff, not
a threshold to tune away.

**Resolved as two phases, not a compromise between speed and accuracy:**
an immediate, cheap **ACKNOWLEDGE** the instant the trigger fires (no
verdict yet, just "felt contact") followed by **CONFIRM** once the full
window's `classify_valid_input` verdict lands. If it turns out to be noise,
the acknowledgment just fades back out — a quiet "false start," which is
honest feedback, not a failure to hide. Same shape as a phone's fingerprint
sensor: instant tactile response, confirmation a beat later.

```
                    trigger (any state, ASLEEP or AWAKE)
                              │
                              ▼
                  ACKNOWLEDGE (instant flash — no
                   state change yet, capture window
                   running in the background)
                              │
                 classify_valid_input() resolves
                    │                       │
                  valid                   noise
                    │                       │
                    ▼                       ▼
         was it ASLEEP or AWAKE?    fade out, back to
             │            │          whatever state you
             ▼            ▼          were already in
          WAKING       CYCLING
        (jolt, no      (flash, hard
         input) │       cut to next
             ▼   │      station)
         SETTLING│           │
        (debounce,│          │
         no input)│          │
             │     │         │
             ▼     ▼         │
            AWAKE ◄──────────┘
              │
         timeout (AWAKE_MINUTES,
          no extend — deliberately
          simpler than WAKE_MINUTES'
          EXTEND gesture)
              │
              ▼
           ASLEEP
```

**Parked research note** (ties back to §4's hardcoded-vs-model principle):
this latency/accuracy tradeoff is a genuine candidate for where a model
might eventually earn its complexity — not to replace `classify_valid_input`,
but to make the *ACKNOWLEDGE* phase itself smarter, e.g. a lightweight
classifier trained to make an earlier, still-reasonably-confident call from
a partial window, rather than either waiting the full window or guessing
blind. Nothing has tested this; noted so it isn't lost, not attempted here.

**UX decisions confirmed (2026-08-05), each backed by existing precedent
rather than invented fresh:**

- **Wake jolt:** `_play_startup_burst()` (rise → decay) is the starting
  point, scaled by `WAKE_JOLT_BRIGHTNESS_MULT` — already validated,
  already the `wake-interaction.md` plan. **Flagged as too slow as currently
  timed** — a feel/timing question, not a logic one, to be iterated visually
  (`led_sandbox.py`, or just direct hardware testing) once the recognizer
  side is settled, not solved by more analysis.
- **AWAKE→CYCLING:** flash, then an **instant hard cut** to the next
  station's display — no crossfade, no gradual fade-up of the new station's
  LEDs *during* the jolt's fade-out. That overlap was considered and
  explicitly dropped for v1 ("too quick to matter, keep it simple") — not
  because it's a bad idea, but because chasing it now risks the exact
  low-brightness dithering flicker this project has hit repeatedly (the
  original CHASE crossfade, the boot ceremony's own rejected crossfade-into-
  live-contract). Revisit only if the hard cut actually feels wrong once
  built, not preemptively.
- **Fade out from jolt to live display:** reuses `_play_startup_burst`'s
  already-validated shape exactly — rise, decay, then a hard handoff with
  no crossfade. Nothing new to build here, same primitive as wake.

**Config, proposed (not yet wired into `main.py`):**

```python
TAP_ENERGY_THRESHOLD = 138000     # per-bottle, see classify_valid_input above
ACK_FLASH_MS = 50                 # instant acknowledgment — as close to 0 as
                                    #   FRAME_MS/hardware allow, no verdict yet
WAKE_JOLT_MS = 500                # jolt animation duration, no input accepted —
                                    #   flagged too slow as-is, needs iteration
WAKE_JOLT_BRIGHTNESS_MULT = 2.0   # scalar over BRIGHTNESS for the jolt
WAKE_SETTLE_MS = 1500             # post-jolt debounce, no input accepted
AWAKE_MINUTES = 15                # matches WAKE_MINUTES' bounded-window
                                    #   philosophy; no EXTEND gesture, no
                                    #   runtime adjustment
CYCLE_TRANSITION_MS = 200         # flash, then hard cut to the next station
```

**Genuinely new integration surface, not just gesture recognition:** CYCLE
needs something to cycle, and `main.py` has no such concept today.

**Corrected 2026-08-18 — it cycles LINES, not stations.** This section
previously assumed a station list. Wrong model: the device sits in one
room, so the **station is fixed**; what varies is which **line** at that
station. Lines and directions are orthogonal, and direction is already
solved — `ApproachContract` renders both directions at once on arms A and
B, so there is nothing for a tap to add there. The tap selects the line.

Identity must live in the **static** view, not a cycle-time cue. The whole
premise is glancing over at a random moment (design principles #1 and #3),
so a transient "you switched to line 2" pulse would relocate line identity
from the object into the user's memory. Instead, metro-style: **anchor
stays neutral white and bright; the moving train dots take the line's
colour.**

Data model and the tinted-glass palette constraint (which is real and
measured — `insights.md` §3 found red vs. orange already ambiguous through
brown glass): `docs/contracts/schedule-json.md` § Multiple lines.

**Implemented and validated on real hardware (2026-08-05).**
`classify_valid_input` + `_TapCycleState` are built (alongside, not instead
of, §4-10's machinery) and confirmed via `gesture_sandbox.py`'s `MODE =
"v1"` path across every dimension that mattered:

- **Latency feels instant** — `[ACK]` fires immediately on trigger, well
  before the ~1.2s capture window resolves; the two-phase design achieves
  the "light switch" feel without needing the window itself to shrink.
- **Accuracy held up on live taps** — 10/10 consecutive real taps in one
  run correctly resolved to `CYCLE`, energies spanning 5,676-107,520 (well
  under the 138,000 threshold, plenty of margin, not a knife-edge).
- **One live miss, and it's the already-known failure mode, not a new
  one:** a real but hard, "rocking" tap read energy=175,448 and was
  correctly rejected as noise per the threshold — consistent with the
  3/180 miss rate already measured in §11's validation data, not a fresh
  problem. Confirms the intended tap style is closer to a smartphone
  touchscreen tap than a firm knock.
- **`SETTLING` correctly filters taps during the debounce window** — no
  spurious `CYCLE` from a tap landing right after `WAKE`.

**LED rendering wired (2026-08-16).** Candidate jolt shapes (`ack_flash`,
`ack_flick`, `confirm_jolt`) were prototyped as scripted, non-gesture-
triggered scenes in `led_sandbox.py` first (`jolt_ack_flash_vs_flick`,
`jolt_double_hill_full`), then duplicated into `gesture_sandbox.py`'s
`run_v1()` — deliberately duplicated, not imported, since neither
sandbox script is part of `make upload`'s payload and `mpremote run`
only transfers the one file named on the command line, so
`import led_sandbox` would fail on-device. `run_v1()` now renders live
off a real tap: `ACK_FN` (`ack_flick` by default) plays during the
~1.2s capture window itself — the only code running while the
recognizer hasn't decided anything yet — then, once the verdict is
known, `WAKE` gets the fuller `confirm_jolt` (rise/decay scaled to
`WAKE_JOLT_MS`, peaking at `WAKE_JOLT_BRIGHTNESS_MULT`) and `CYCLE` gets
the simpler `cycle_flash` (flash + hard cut, `CYCLE_TRANSITION_MS` —
deliberately not the fuller jolt, per this section's earlier
AWAKE→CYCLE decision). A rejected tap gets no confirm animation at all,
just a hard cut to black. Still prints every transition — `run_v1()`
stays the recognizer/state-machine regression check even with real
rendering wired in.

**First real-hardware feedback (2026-08-16):** the wired-up jolt was
tested on the actual jar. `WAKE_JOLT_MS`'s 500ms budget did NOT feel
slow — no change needed there. But ACK and CONFIRM read as **two
disconnected blips, almost too distinct**, with the ~1.2s gap between
them leaning toward a stall rather than a pause. Root cause: ACK was
dropping straight to black after its flick, so the gap looked like
"nothing is happening" instead of "it's still here, deciding."

**Fix — the "continental shelf" + tap-strength scaling.** Two changes,
both in `gesture_sandbox.py` (and mirrored as a scripted preview in
`led_sandbox.py`, see that file's caveat about dithering in the preview
specifically):

- **ACK no longer settles to 0.** It dips to a dim-but-non-zero "shelf"
  brightness instead, held statically for the rest of the capture
  window, bridging ACK and CONFIRM into one continuous gesture rather
  than two isolated events. `CONFIRM`'s jolt then rises FROM the shelf,
  not from black, and decays all the way to 0 — the shelf says "still
  deciding," decaying past it says "decided, done."
- **Tap strength now scales both the ACK peak and the shelf level** —
  `_tap_strength()` maps `dev` (the triggering sample's deviation from
  baseline — the only signal available this early; the recognizer's real
  `energy` isn't known until the capture window closes) to 0..1, which
  sets both `ACK_PEAK_FLOOR..CEIL` (the "up") and `SHELF_FLOOR..CEIL`
  (the "down") — a harder tap reads brighter on both ends, not just a
  fixed response regardless of how hard you actually tapped.
  `STRENGTH_MAX_DEV_MG` is an **untested guess (400mg)** — tune it live
  against what a real light vs. hard tap actually reads as `dev`.

**Avoiding flicker was the binding constraint, not an afterthought.** A
held/static value redrawn repeatedly through the normal gamma+dither
path is exactly the failure mode `_play_startup_burst`'s docstring warns
about (dithering has nothing to average against when the value isn't
changing) — and gamma alone would have crushed a low shelf mult toward
invisible (`gamma(0.15)≈0.014` at `GAMMA=2.2`), defeating the whole
point. Fix: the shelf is written via a separate static path (no gamma,
no dither — same fix `MARKER_BRIGHTNESS` already uses for the approach
contract's idle ticks) exactly ONCE when the ACK settles, then left
alone until CONFIRM/CYCLE/rejection overwrites it. The rise/dip and the
jolt itself stay on the normal animated (gamma+dither) path — they're
genuinely changing, so dithering helps there instead of hurting.

**Second round of real-hardware feedback (2026-08-16, same day):** the
shelf/strength revision was retested. Strength scaling works — captured
`dev`/`strength` pairs (e.g. `dev=281mg → strength=0.66`) confirmed the
mapping responds sensibly to real taps. Two more findings:

- **The ACK peak was visible for too little time to actually perceive a
  strength difference** — `ACK_HOLD_MS` widened 150ms → 400ms (§ above).
- **A real rendering bug, not a feel issue: "on the downward trend from
  the ack to the plateau, the leds turn off for about 100ms... a 'dive
  underground to 0, then back up to a plateau.'"** Root cause: the ACK's
  descent rendered through the normal gamma-corrected path, but
  `gamma(mult)` for `mult` below roughly 0.3 (at `GAMMA=2.2`) is *much*
  smaller than `mult` itself — and ack_flick's whole range (peak 0.5-1.0,
  dipping to the shelf's 0.08-0.25) sits mostly in that zone. So the
  gamma-corrected descent visibly hit black well before reaching the
  shelf's own value, then jumped back up once the static (non-gamma)
  shelf write took over. Fixed via `_write_segment(..., use_gamma=False)`
  for the whole ack shape — confirm_jolt and cycle_flash stay
  gamma-corrected (their range is high enough not to hit this, and
  confirm_jolt's dramatic peak depends on gamma's extra emphasis there).
  **Flagged but not fixed:** confirm_jolt's own rise starts from
  `start_mult` (the shelf) through the same gamma path — unconfirmed
  whether this produces the same brief dip (its rise is much faster,
  ~174ms vs. the ack's ~200ms fall) — watch for it on the next test.

**Also added this round:** a sustained-I2C-failure error state.
Real-hardware testing crashed the script twice (`OSError EIO` from a
table tap and a bottle grab jostling a breadboard connection — the same
failure `vibration_sandbox.py` already diagnosed). `_safe_read_accel`
now catches it and skips the sample instead of crashing. The natural
follow-up question — "shouldn't this show something on the LEDs, like
the ACK flash but red?" — surfaced a real tension with this doc's own
principle (`docs/contracts/led-status-messages.md`: "errors are
persistent and unambiguous... a broken device should look broken, not
almost-normal"): a brief flash for a single dropped sample would read as
*almost normal*, working against that. Resolved by keeping single blips
silent (the point of skip-and-continue) and only escalating to the
established persistent-breathe pattern — with its own new
`SENSOR_ERROR_COLOR` (cyan, distinct from `ERROR_COLOR` and
`SCHEDULE_ERROR_COLOR`) — once a read hasn't succeeded in over a second.
Unlike the production "forever, needs reset" pattern, this sandbox's
version self-clears once reads succeed again, since a jostled wire is
likely to self-heal and this is a dev tool, not the shipped experience.

**Third round of real-hardware feedback (2026-08-16, same day):**

- **The "dive to black" fix confirmed working.**
- **`ACK_PEAK_FLOOR`/`CEIL` widened.** Even at the strength extremes
  (`dev=54mg, strength=0.01` vs. `dev=444mg, strength=1.00`), the old
  0.5-1.0 ACK peak range (a 2x linear spread) wasn't perceivably
  different — human brightness perception is roughly logarithmic, so a
  narrow linear range under-delivers. Widened to 0.4-1.6 (~4x). The
  shelf range stayed put (0.08-0.25); it wasn't the thing reported as
  hard to distinguish.
- **`STRENGTH_MAX_DEV_MG=400` held up** — real captured `dev` values
  spanned 54-444mg across this session's taps, close enough to the
  ceiling that it didn't need retuning.
- **A structural observation, not a bug:** the two highest-`dev` taps
  captured this round (396mg, 444mg) were also the two that got
  rejected as noise (`energy` above `TAP_ENERGY_THRESHOLD` — correct,
  expected behavior per this section's earlier "closer to a smartphone
  touchscreen tap than a firm knock" finding). Since `dev` and `energy`
  both derive from the same physical event, they're correlated — meaning
  the brightest ACK flashes are somewhat *more* likely to end in
  rejection, not less. This is an inherent consequence of previewing
  with `dev` (available at ACK time) before `energy` (the real
  accept/reject signal, not known until the capture window closes) is
  known — not something a brightness-mapping tweak can really fix, since
  the two signals are fundamentally different quantities measured at
  different times. Noted here as a known property of the design, not
  flagged as broken.
- **EIO failures observed correlating with light taps specifically** (3
  occurrences, all preceded by near-zero `dev` heartbeat lines) — logged
  as a hypothesis being tested live, explicitly NOT treated as confirmed
  given the sample size (n=3) and this project's own repeated "small
  samples mislead" lesson (§9). Physically counterintuitive too: a
  harder impact should stress a marginal connection more, not less. An
  untested alternative hypothesis: `print()` over the USB-serial link can
  briefly block, and if that coincides with an I2C transaction, it could
  produce timing-based EIO independent of tap force — which would just
  happen to cluster around active testing (more terminal output) rather
  than light taps specifically. Needs more data either way.

**Fourth round of real-hardware feedback (2026-08-16, same day) — first
IN-BOTTLE test.** Everything up to this point was tuned against a bare
LED strip. 駅瓶's whole premise is a frosted glass jar, not a bare strip
— so this is the first test against the actual target, not a proxy.

- **Bare strip (0.4-1.6 ACK_PEAK range): three real strength levels
  (dev=93/244/344mg) read as clearly distinguishable.**
- **Same range, in-bottle: "less distinguishable... but still subtly
  different."** A frosted diffuser compresses brightness contrast — a
  range tuned bare will always under-deliver once the glass is on, this
  isn't a new bug, just the first time it was measured against the real
  enclosure. Widened again: `ACK_PEAK_FLOOR/CEIL` 0.4-1.6 → 0.35-2.2,
  pushed mostly on the ceiling (the floor was already close to
  `SHELF_CEIL`, and eating that margin risks shelf/ACK ambiguity — the
  ceiling has more room before rivaling `CONFIRM`'s gamma-amplified
  peak). `STRENGTH_MAX_DEV_MG` nudged 400→460 (observed max crept
  444mg→461mg between rounds). Expect this may need a further round —
  there's no way to predict how much a frosted diffuser compresses
  contrast without measuring it, and this is only the first in-bottle
  measurement.
- **The sensor-error escalation worked correctly in the wild**, twice:
  `[SENSOR ERROR]` → `[SENSOR RECOVERED]`, no crash, both times
  triggered by real handling (moving the bottle across the table; an
  "odd tap sequence" the user described as their own input error) rather
  than a clean single tap.
- **Revises the EIO/tap-force hypothesis from the last round:** this
  round's failures cluster around *handling* (moving the bottle, a
  fumbled tap sequence), not light taps in isolation — more consistent
  with the original vibration_sandbox.py diagnosis (jostled connection
  from handling) than a light-tap-specific effect. The earlier
  "correlates with light taps" read looks like it may have been exactly
  the small-sample coincidence flagged last round. Still not conclusively
  resolved either way.

**Fifth round (2026-08-16, same day) — pulled ACK_PEAK_CEIL back to 6.0**
after the saturation analysis above; retested in-bottle across strength
0.01-1.00 (six real taps) and confirmed working well — the ceiling now
sits just under the clamp point instead of past it.

**Hardened against regression, not just documented.** The saturation bug
(a real one, silently reproducible by anyone editing `ACK_PEAK_CEIL` or
`BRIGHTNESS` later without knowing this history) is now covered by
`tests/test_gesture_sandbox.py` — `test_ack_peak_ceiling_does_not_saturate`
fails if the configured `ACK_PEAK_CEIL`/`BRIGHTNESS`/`STARTUP_COLOR`
combination would clamp a channel before strength=1.0 (verified against
the actual historical bad value, `ACK_PEAK_CEIL=10.0`, which does fail
it). Also covers `SHELF_CEIL < ACK_PEAK_FLOOR` (the shelf/ACK-blur
invariant) and a floor on `ACK_PEAK_CEIL/FLOOR`'s spread (guards the
*other* direction — the original 2x-spread bug). Deliberately does NOT
attempt to test for `dev`-value *clustering*: that depends on what real
human taps actually produce, which is empirical, not a property of the
constants themselves — clustering stays a documented, on-hardware thing
to watch for (see the strength distribution note two rounds up), not a
pytest assertion. Required guarding `gesture_sandbox.py`'s bottom dispatch with
`if __name__ == "__main__":` first — it previously called
`run_v1()`/`run_full()` unconditionally at import time, which would have
tried to talk to real hardware the moment a test imported the module.
`led_sandbox.py` already had this guard; `gesture_sandbox.py` just
hadn't needed it until something needed to import it.

**Not yet done:** resolving the EIO/handling-correlation question with
more data; confirming whether confirm_jolt's rise has the same gamma-dip
issue; and wiring any of this into `main.py`'s actual production loop —
`gesture_sandbox.py` is still a sandbox, not the real thing.


## Sleep behaviour on a real unit (2026-09-03)

Confirmed in the code and worth stating where someone will look for it: the
display is **not always on.**

`_run_interactive_loop` boots the unit AWAKE — boot counts as the first wake
trigger — and arms `awake_until = now + AWAKE_MINUTES` (default **15 min**).
After that `_TapCycleState.resolve()` transitions AWAKE → ASLEEP and the loop
takes the `clear()` branch. A tap wakes it for another window.

⚠ **A sleeping unit is indistinguishable from a dead one**, which is the same
hazard quiet hours already carries. The loop now prints
`(asleep after 15 min — tap to wake; not a fault)` on the transition — once,
not per tick — so a console can tell the two apart. There is no such signal
without a console, which is an argument for the onboard NeoPixel carrying it
in a future debug mode (`ONBOARD_LED_MODE`).
