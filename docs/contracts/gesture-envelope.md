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
