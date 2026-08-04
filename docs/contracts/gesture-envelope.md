# Gesture envelope & interaction contract (IMU-driven)

**Status: Design.** Evidence-based — every claim below is backed by real
data in `docs/insights.md` §8-9, gathered via the sandbox toolchain
(`micropython/vibration_sandbox.py` / `imu_test.py` / `handling_test.py` /
`orientation_test.py`), not assumed. Not yet implemented in `main.py`.

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
TAP_MAGNITUDE_THRESHOLD_MG = ...          # per-bottle, from vibration_sandbox.py
FLICK_SPACING_STDEV_THRESHOLD_MS = ...    # per-bottle
POSITION_THRESHOLD_MG = ...               # per-bottle, only read if
                                            #   GESTURE_POSITION_ENABLED
```

None of these have real values yet — they need to come from running the
sandbox tooling against the actual bottle being flashed, the same way
`config_friend1.py`'s display knobs were hand-tuned per jar.

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
- No real threshold *values* exist yet — §5's config knobs need actual
  numbers from running the sandbox tooling against a specific physical
  bottle before this can be implemented, not just designed.
- Feature extraction (§3) needs porting from host Python
  (`prepare_tap_dataset.py`) to MicroPython — mechanical, not yet done.
- The menu/scrollwheel option list (§7) is unspecified — a product
  decision, not a hardware one.
