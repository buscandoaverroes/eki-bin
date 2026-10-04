# Classifier approach — which decision logic, and how to get there

**Status: analysis, 2026-10-04. Nothing built into firmware.** Evidence: the
five `use: true` recordings in `data/imu-sessions.json` (one bottle, empty, one
wood table, one day). Sits under `docs/imu-interaction-plan.md` (Phase 1
results → Phase 2 arbiter → Phase 5 ML gate) and updates the ranking in
`docs/on-board-detection.md`. Every number below is a **hypothesis** by
`insights.md` §8's rule (n<30 per class per session, or single session).

---

## Recommendation (short)

1. **Hand-written rules shaped as a depth-2 decision tree, plus the arbiter's
   settlement window. No trained model on the device yet.** On this data a
   tree that learns freely from 15 features picks *two* physics features —
   rotation in the middle of the capture window, and the vertical share of the
   impulse — and nothing more complex (logistic regression, a 50-tree forest)
   beats it by more than noise. Write those two tests by hand, with the
   thresholds in config.
2. **Retire `energy < TAP_ENERGY_THRESHOLD` as the accept rule.** On these
   recordings it rejects 14 of 49 triggered real taps (9 of 20 top taps) and
   accepts 54 of 58 table knocks. It is a 98.4 % result from August's
   *different* question (tap vs. pick-up/carry) that does not carry over.
3. **Grabs are not a classification problem.** A grab is a touch on the glass
   and its 150 ms impulse looks like a tap (median z-share 0.06, same as taps).
   What separates it comes *later*: a look-forward veto ("gravity moved > 5°
   within 3 s") removes 11 of 27 accepted grabs and **no taps**. That is the
   Phase 2 settlement ledger, not a model.
4. **Train offline, deploy rules.** Use scikit-learn on the Mac (already in
   `.venv`: scikit-learn 1.9, numpy, scipy — nothing installed for this) as the
   *search tool* that proposes features and thresholds; ship what it finds as
   readable `if` statements. Re-run the search every time a session lands.
5. **ESN / small neural net: no.** 49 positive examples from one session
   cannot fit a reservoir readout or a net honestly, and the information they
   would add (temporal memory) is supplied explicitly by the settlement window.
   **MLC: later, and only for a battery build** — the shape of the rule
   (a shallow tree) is chosen so it can go there, but the best feature
   (a *ratio*, measured right after a *trigger*) is not native to the MLC.

## What the data is, and the confound that limits it

Triggers come from the real firmware trigger (`scripts/replay.py`, `--ideal`,
240 Hz loop — so the classifier is judged on every impulse, not on what the
blind loop happened to see). Each trigger gets the nearest label one-to-one
(−1.0/+0.2 s, as `score()` does). Every trigger in a session with no tap labels
counts as *handling*; extra triggers near labels in the tap session are dropped
as ambiguous.

| class | n triggers | from |
|---|---|---|
| tap (top 20 / body 15 / base 14) | **49** (of 62 labelled; 13 never triggered) | 112059 only |
| ambient (table knock 28, object knock 20, bump 10) | **58** | 112059 (+1) |
| handling (grab 34, lift 50, set-down 47, release 10, carry/tilt/moves ~230) | **372** | 115305, 120053, 121114 |

**The confound:** every tap and nearly every ambient knock is in *one*
session; all handling is in the others. Class is almost identical to session,
so a model could learn the session (gyro bias, posture) rather than the
gesture. Features below are bias-removed relative to the 0.5 s before the
trigger to limit this, but leave-one-session-out is **impossible for taps**
(hold out 112059 and there are no positives to train on). Taps were also
pressed ~1.3 s apart, which corrupts any look-forward measurement on taps
(the next tap lands inside the window). Neither can be fixed by analysis —
only by recording (see *Data still needed*).

## Features (all inside the existing 1.2 s capture window or before it — no added latency)

From the raw 234 Hz stream; scripts in the session scratchpad (`feats.py`,
`cv.py`, `survivors.py`), to be promoted into `scripts/` if adopted.

| feature | tap p50 (p5–p95) | ambient p50 | handling p50 |
|---|---|---|---|
| `z_share` — z fraction of accel impulse energy, first 150 ms | 0.10 (0.04–0.23) | **0.85** | 0.51 |
| `gyro_mid_mean` — mean bias-removed rotation 150–400 ms, °/s | 0.17 (0.09–0.87) | 0.39 | **22** |
| `gyro_late_mean` — same, 400–1200 ms (the replay's `gyro_late_dps`) | 0.10 (0.07–3.7) | 0.16 | 11 |
| `tilt_change_deg` — gravity direction, pre vs last 200 ms | 0.03 | 0.02 | 9.0 |
| `pre_gyro_mean` — rotation 100–600 ms *before* the trigger | 0.06 | 0.07 | 8.3 |
| `energy` (the firmware's) | 89 k | 33 k | 1.4 M |
| also: `peak_dev`, impulse log-energy, `hf_ratio` (sharpness), ring-down, peak time, early gyro peak, integrated angle, late/pre accel sd | | | |

Read: **ambient = vertical impulse, no rotation; handling = rotation; tap =
horizontal impulse, no rotation.** Energy orders the classes the wrong way for
taps vs. knocks (knocks are *softer* at the base IMU).

## Results — cross-validated

Rows are triggers accepted as taps. CV is **time-blocked**: each session is cut
into five contiguous fifths, fold *k* tests on the *k*-th fifth of every
session, trained on the rest (no random splits — neighbouring events are
correlated). Brackets: Wilson 95 % intervals on the headline cells.

| decision logic | taps accepted (want high) | ambient accepted (want 0) | handling accepted (want 0) |
|---|---|---|---|
| shipped: `energy < 138 k` | 35/49 (71 %) [58–82] | 54/58 (93 %) | 113/372 (30 %) |
| shipped + `z_share < 0.5` (hand) | 35/49 | 7/58 (12 %) | 86/372 (23 %) |
| shipped + `gyro_late < 1.5 °/s` (hand) | 32/49 | 54/58 | 31/372 (8 %) |
| shipped + both vetoes (hand) | 32/49 (65 %) | 7/58 (12 %) | 25/372 (7 %) |
| tree depth 2, 3 features, CV | 45/49 (92 %) [81–97] | 8/58 (14 %) [7–25] | 34/372 (9 %) |
| tree depth 2, 15 features, CV | **48/49 (98 %)** [89–100] | 8/58 (14 %) | 35/372 (9 %) |
| tree depth 3, 15 features, CV | 45/49 | 8/58 | 24/372 (6.5 %) |
| logistic, 15 features, CV | 47/49 | 12/58 | 39/372 |
| random forest 50 × depth 4, CV | 43/49 | 4/58 | 26/372 |
| **hand rule** `gyro_mid < 1.15 °/s AND z_share < 0.40` (in-sample — thresholds are the tree's) | 49/49 | 8/58 | 34/372 — of which grab 27, release 3; other handling 7/338 (2 %) [1–4] |
| … + look-forward veto: gravity moved > 5° in 1.2–3 s | 49/49 | 7/58 | grab 27 → 16 |

Robustness checks:
- **Leave-one-handling-session-out** (that session's handling never seen in
  training): depth-2 tree accepts 37/373 — 37/279 in the handling session
  (nearly all grabs), 0/19 and 0/75 in the rest/tilt sessions. Logistic on 3
  features is worse there (19/75 in 121114): it extrapolates linearly; a tree
  fails safe.
- **Tap session alone, taps vs. ambient**, blocked CV: depth-2 tree 45/49 taps,
  5/57 ambient; logistic 49/49, 2/57. Separable, on this table.
- **The fully free depth-2 tree** chose `gyro_mid_mean ≤ 1.15 °/s` then
  `z_share ≤ 0.40`; depth 3 added `gyro_early_peak ≤ 62 °/s`. Logistic and
  forest importances rank the same features (z-share, mid/late gyro) first.

What this does and does not say:
- The **margins are thin**: the largest tap `z_share` was 0.37 (a top tap)
  against a 0.40 cut; the largest tap `gyro_mid` 1.03 against 1.15. The cuts sit
  on the edge of the tap cloud because there are only 49 taps. Expect them to
  move with a second session; top-of-glass taps are the ones to watch.
- More model capacity bought nothing here — forest vs. depth-2 tree differ by
  ~4 events in each cell, inside the intervals.
- **Grabs dominate what is left** (27 of 34 handling false accepts). The 11 the
  look-forward removes are grabs followed by a lift; most of the 16 left are
  likely the "grab alone, no lift" block at the start of 115305, which is a
  touch by definition. Whether *that* should light the bottle is a design
  question, not a classifier one.
- 13/62 tap labels never fired the trigger even at 240 Hz. No classifier
  recovers those; that is the trigger's floor (50 mg) and the loop rate.
- Bumps (n=10) and the "unlabelled" triggers in the tap session are n<30;
  footsteps/chair (112544) triggered nothing.

## The options, judged against this

| option | fits the data? | MicroPython on RP2350 | Rust port | battery | verdict |
|---|---|---|---|---|---|
| hand rules (depth-2 tree shape) | yes — matches the best model within noise | features ~300 samples × 6 axes in the capture window: est. 10–40 ms once per trigger (the existing `extract_gesture_features` already does a sqrt per sample); decision ~µs | trivial | MCU must be awake | **now** |
| learned tree / logistic on MCU | yes, but no gain yet | same features + 15 multiplies: negligible | trivial | same | **as the offline search tool; deploy only if it beats the hand rule on new sessions** |
| MLC decision tree (on the IMU die) | partly — see below | n/a (config blob written over I2C) | n/a | **µA while MCU sleeps** | **only for a battery build; after the rule is stable** |
| ESN / reservoir | no — ~50–100 readout weights vs. 49 positives | N=50 reservoir at 240 Hz ≈ 600 k MAC/s: not feasible continuously in pure MicroPython (≈ 1 µs+ per float op); per-window only | ~4 ms/s at 150 MHz with FPU — fine | continuous inference kills a battery | **no** — its strength (memory) is what the settlement ledger does explicitly |
| small NN (1D CNN on raw window) | no — needs 100s–1000s per class | impractical without ulab/native code | feasible (tens of KB) | as ESN | **no** |

All runtime figures are estimates, not measured; measure with the `rate`/
`render_ms` instrumentation before relying on them.

### MLC — what it can and cannot express

**Fairly sure** (consistent across ST's LSM6DSOX/LSM6DSV families):
the MLC computes *statistics over a fixed window* of chosen inputs (accel and
gyro axes, their norm or squared norm, optionally filtered — HP/BP/IIR) —
features such as mean, variance, energy, peak-to-peak, min/max, zero- and
peak-crossings — and runs **binary decision trees** on them, outputting a
class code into a register and optionally raising an interrupt. Trees are
trained off-chip (ST's MEMS Studio/Unico tools, or scikit-learn exported via
ST's scripts) and loaded as a register configuration.

**Recalled, must be checked against the LSM6DSV16X datasheet and its MLC
application note before designing to it:** the number of trees (8 on the
LSM6DSOX; possibly fewer on the DSV16X), the shared node budget (~256), the
maximum window length (~255 samples), the MLC ODR options (up to 240 Hz on
the DSV16X?), the "meta-classifier" output filter, and the FSM's ability to
sequence events.

**What it cannot do natively**, which is what matters here:
- *Triggered* windows. MLC windows are fixed and free-running; "the first
  150 ms after the impulse" becomes "whichever window contains it", diluted.
- *Ratios.* `z_share` = E_z / E_total is not a feature; an axis-aligned tree
  can only approximate it from `energy_z` and `energy_xyz` with several splits
  — and amplitude-based splits are exactly what failed cross-bottle (§8, 0 %).
- *Look-forward/look-back of seconds.* The settlement window and ledger live
  on the MCU regardless; the MLC can at most be the cheap first stage that
  wakes it ("impulse with low rotation" vs. "rotating").
So the MLC's job, if it gets one, is **wake filtering on a battery**, not the
final verdict.

## Per-unit calibration

August's finding stands: amplitude thresholds did not transfer between bottles
(position: 0 %); timing features did (85 %). The two features chosen here are
**not amplitudes**: `z_share` is dimensionless (direction of the impulse) and
`gyro_mid_mean` is in physical °/s with the bias removed. That is a reason to
*hope* they transfer, not evidence — a lid mount changes `z_share`'s meaning
entirely, and a heavier or filled bottle damps rotation. Plan:
- **Structure fixed, thresholds per unit** in config (as `TAP_*` knobs are now).
- **Calibration ritual** using `make imu-record`: ~15 taps across heights,
  ~15 table knocks, ~10 grab-and-lift, 60 s flat rest. The fit is the offline
  search above, restricted to the two thresholds; output is a knobs file like
  `data/knobs-bottle-01.json`. Five minutes, maker-side (§8 option (a)).
- **The test that decides it:** on bottle 2, score bottle-01's thresholds
  untouched vs. recalibrated. If untouched is within the intervals, drop the
  ritual to a smoke test.

## Power (if a battery build happens)

- The pipeline above needs the MCU awake and polling at 240 Hz; RP2350 active
  draw (tens of mA, estimate) dwarfs the IMU's, so a battery build cannot run
  it continuously regardless of model choice.
- Battery shape: IMU wake-up/activity interrupt (or an MLC "impulse" class)
  wakes the MCU; MCU powers the gyro and captures the window. **Caveat:** the
  gyro needs tens of ms to start (datasheet turn-on time — check), so
  `gyro_early_peak` and `pre_gyro_mean` would be unavailable; `gyro_mid_mean`
  (150–400 ms) is probably still fine, which is another reason to prefer it.
- Gyro in high-performance mode is roughly an order of magnitude above
  accel-only low-power (recalled; measure with `power_budget.py`). On USB/lamp,
  irrelevant.

## The testing ladder (each rung has an exit; do not skip)

**Rung 0 — offline, from recordings (now).** Promote the scratch feature
extractor into `scripts/replay.py` as `capture_features` additions, add the
hand rule and the depth-2 tree as candidates, and add a `--cv blocked` mode
that prints the table above. Add a golden-file test (one recording, fixed
expected verdicts) to `make test`.
*Exit:* the table regenerates from one command; ≥2 sessions contain taps, so
leave-one-session-out runs for every class.

**Rung 1 — fix the recording protocol, then re-collect.** Taps ≥ 4 s apart,
taps and knocks in separate files, a "grab, hold 3 s, release, no lift" block,
a "reach, grab, lift, tilt" block (failure B), on a second day and a second
surface. Re-run Rung 0.
*Exit:* hand rule within the intervals of the tree on held-out sessions; tap
recall ≥ 95 % with ≥ 60 taps; ambient ≤ 5 % with ≥ 60 knocks.

**Rung 2 — live shadow mode on the Mac.** `imu_stream.py` → Mac runs the real
trigger + features + every candidate in real time and prints verdicts *without
driving the LEDs*; the human labels as now. **Self-labelling / active
learning:** prompt ("tap?") only when candidates disagree or the logistic
probability is 0.3–0.7, and auto-label the confident rest; log every prompt.
Also run unlabelled "normal living" hours with only the `h`/`8` keys.
*Exit:* ≥ 3 h of normal living with ≤ 1 accepted false tap per hour (rule of
three: 0 in 3 h ⇒ < 1/h at 95 %), and the disagreement rate falling session
over session.

**Rung 3 — port to firmware behind a flag**, together with the loop-rate fix
and tilt-in-milliseconds (Phase 1 showed those must land together), with the
Phase 2 settlement ledger carrying the look-forward veto. Record with
`make interaction-log` and replay the *same* recording on the host.
*Exit:* host/device verdict parity on a recorded session; `make test` green;
one lived-with day.

**Rung 4 — second bottle.** Calibration ritual vs. untouched thresholds.
*Exit:* decision on per-unit vs. universal thresholds, written into
`docs/gift-registry.md`'s per-unit record.

**Rung 5 — only if battery or plateau.** MLC wake filter (battery), or a
learned tree on the MCU (only if Rung 1–2 shows a misclassification the rules
cannot fix *with the right features available* — the plan's Phase 5 gate).
*Exit:* MLC class codes match the host tree on replayed windows; current
measured.

## Data still needed (with counts)

| need | have | target | why |
|---|---|---|---|
| true taps, ≥ 4 s apart, by height × soft/hard | 49 triggered, one session, 1.3 s apart | ≥ 30 per session × ≥ 3 sessions (~100) | LOSO for taps; look-forward cost on taps; top-tap z-share margin |
| table/shelf knocks, several distances, ≥ 2 surfaces | 48, one table | ~100 across surfaces | z-share depends on surface coupling |
| grab alone (no lift), grab→lift, reach→grab→tilt | 34 grabs mixed | 30 + 30 + 30 | separates "touch" from failure B; sizes the settlement window |
| taps on a **filled** bottle | 0 | 30 | mass changes ring and rotation |
| normal living, unlabelled hours | ~0 | ≥ 3–5 h | false taps per hour is the real target metric |
| missed (sub-trigger) soft taps | 13 inferred | labelled `9`-style, 30 | trigger floor, separate from the classifier |
| a second bottle | 0 | one full ritual + one session | calibration question |

Until Rung 1's exit is met, treat every row of the results table as a
hypothesis about *this* bottle on *this* table on *this* day.
