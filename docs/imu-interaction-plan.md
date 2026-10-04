# Interaction plan — making tap and tilt coexist

**Status: draft plan. Nothing built. Written 2026-09-29 to be iterated on
before any code.** Branch context: `feature/docs-sweep-imu-plan`.

Sits on top of `docs/on-board-detection.md` (which ranks the *options*) and
`insights.md` §8 / §15 / §17 (which record the *evidence*). This document
is the sequenced plan those two imply, plus the design that came out of a
conversation about what "mutually exclusive" actually has to mean.

---

## 1. The problem, restated

Tap and tilt each work in isolation and are unreliable together. Three
distinct failures hide under that sentence, and they want different fixes:

| # | failure | mechanism | class |
|---|---|---|---|
| A | Tilting fires 1–3 spurious taps per session, each answered with a `shake` | The tap trigger hunts for `|mag − baseline| ≥ TAP_TRIGGER_THRESHOLD_MG`; moving a bottle produces exactly that. `tilt.py` gates on |a| ≈ 1 g; the tap trigger has no mirror gate. | missing mutual exclusion |
| B | **The approach to a tilt fires a tap** — grabbing the bottle, knocking the shelf while reaching, moving something in front of it out of the way | The tap happens *before* the tilt exists as a state, so no gate keyed on "tilt is engaged" can see it. The evidence of "this was the start of handling" arrives *after* the false tap. | **causality: the disambiguating signal is in the future** |
| C | A tilt session gets stuck "engaged" (bottle flat on a table reading a few degrees forever, brightness creeping) | Baseline re-learning is gated on `not engaged`; a stuck session blocks the re-learning that would unstick it. A deadlock in control flow, not a misclassification. | structural bug |

**A** is the easy one and is already diagnosed. **C** is a real bug. **B**
is the interesting one and is why "just suppress taps while tilting" is not
enough — the user's framing, which is right: *if you could go back five
seconds from the moment a tilt begins, you would silence the tap.* The states
are not purely exclusive; there is a **negative overlap**, a window *before*
tilt engagement in which taps are already suspect.

## 2. The core design idea: taps are provisional, and the future can veto them

We cannot travel back in time. There are exactly three ways to get the same
effect, and they compose:

1. **Look-forward (delay the verdict).** Do not commit a tap until enough
   *after* the impulse has been seen to tell "isolated strike then stillness"
   from "impulse that is the first moment of being handled". The capture
   window already does part of this (`classify_valid_input`'s energy over the
   ~1.2 s capture is what rejects pick-up/carry at 98.4%). The gap is what is
   *committed* during that window — see (2).
2. **Split "acknowledge" from "commit" and make commit undoable.** ACK (the
   instant light response) is deliberately live during capture, before any
   verdict exists (`gesture-envelope.md`). That is correct for feel and is
   the visible symptom of failure B. The *state change* a tap causes —
   `CYCLE` advancing the line — can be held provisional and **rolled back** if
   handling is detected in a look-back window afterwards. Cheap: a cycle is
   one integer; keeping the previous value is free.
3. **Look-back (retroactive veto).** Keep a rolling event log of the last
   ~5 s: taps, tilt state changes, rotation activity. When tilt engages, or
   gyro shows sustained rotation, mark taps inside the window as "handling
   preamble" and undo/suppress what they did. This is the user's
   "go back five seconds", implemented as a *ledger* rather than time travel.

The result is that a tap is a **claim with a settlement period**: ACK now,
CONFIRM/commit only if nothing incriminating arrives within the settlement
window, undo if it does. The settlement window is the parameter to measure,
not guess (§5).

### The cost, stated plainly

- A settled `CYCLE` feels later than today's. Today CONFIRM plays right after
  capture. Settling adds up to the window length. Mitigation: settle on
  *evidence of stillness*, not a fixed timer — if the bottle is demonstrably
  still after the impulse (which the gyro can say cheaply), commit early.
- A swallowed ACK looks like "a tap that did nothing". That is the price of
  keeping ACK instant. The alternative — hold ACK until the verdict — kills
  the instant feel that took five hardware iterations to get right, and is
  not recommended unless recorded data shows the ACK-then-nothing case is
  common and confusing.
- Undoing a visible CONFIRM is not possible (the light already happened).
  So undo applies to *state*, not to *already-emitted light*. This is fine
  provided commit waits for settlement; it is the reason (2) matters.

## 3. The gyro is the likely discriminator — and it is free

The LSM6DSV16X's gyroscope is on the same die and currently **unpowered**:
the firmware writes only `CTRL1` (accelerometer ODR); `CTRL2` (gyro) is never
set. Rotation rate separates precisely the cases being confused:

| | rotation rate | translation |
|---|---|---|
| deliberate tap on glass | ≈ 0 | brief impulse |
| tilt | sustained, slow | none (1 g held) |
| pick-up / grab / reach-and-move | **rises with or just after contact** | sustained |
| shelf knock (bottle not touched directly) | small, decays | impulse |

The accelerometer sees only the right-hand column. A grab is an impulse
*followed by rotation*; a tap is an impulse followed by nothing. That is
failure B's signature, readable in the settlement window without any model.

Also answers the second half of the conversation: **does detecting the
"engage tilt" gesture (a quick raise) itself spook the tap trigger?** Yes —
a raise is a translation transient, indistinguishable from a strike on
acceleration magnitude alone. The gyro (rotation and its onset) plus the
arbiter's HANDLING state are what let the raise be *claimed by tilt* instead
of *reported as a tap*.

Costs to check, not assume: power (gyro high-perf mode draws far more than
accel-only; irrelevant on USB, relevant if the bottle stays battery-powered —
use low-power ODR or gate it on the wake state), and I2C read length per
sample (one more 6-byte burst, or one 12-byte burst).

## 4. Tilt: always-on sense, or a mode?

Two designs, and the plan builds the arbiter so either is a config choice:

- **Always-on** (today). Tilt engages whenever the bottle leans past the
  deadzone while awake. Direct and discoverable; maximally exposed to
  failures A/B/C.
- **Armed by a gesture** — tilt is only live for a few seconds after a tap or
  wake ("tap, then tilt to adjust"), or after a distinctive engage motion.
  Halves the exposure, at some cost in directness and one more thing to
  learn. Note the trap already identified: *the engage motion is itself a
  handling transient*, so an engage-by-raise design needs the same gyro /
  arbiter machinery to avoid firing taps — it does not remove the problem,
  it relocates it. **Armed-by-tap** avoids that (a tap is already a
  recognised, settled event) and is the version worth prototyping.

Decide by data (§5, Phase 0): how often does unintended tilt engagement
occur in a day of normal living? If rare, always-on with the arbiter is
enough.

## 5. The plan, in order

Each phase is independently useful, ends with `make test` green, and gates the
next. **Phase 0 comes first because every other phase needs ground truth,
and the project's own methodology rule (§8: n<30 or single-session is a
hypothesis) forbids tuning against anecdotes.**

### Phase 0 — Record everything, unfiltered (no behaviour change) — **built 2026-09-29, not yet run on hardware**

- Extend the freeform logger (`micropython/tilt_freeform.py` already logs
  every sample to JSONL and asks "how did it feel") into a **combined
  interaction logger**: continuous accel **+ gyro**, at the loop's real
  sample rate, with the *current* tap/tilt pipeline's decisions recorded
  alongside as events (`trigger`, `tap_verdict`, `tilt_state`, `shake`).
- Add a one-key **label**: after any unwanted response, mark it (false tap,
  stuck tilt, missed tap). Labelling in the moment, one press, beats
  reconstructing from logs.
- Sessions to collect: normal living (a day), deliberate grab-and-tilt ×N,
  reach-past-and-knock-shelf ×N, tap-only ×N, tilt-only ×N, table-flat-stuck
  repro. Gyro enable is the *only* firmware change in this phase.
- **As built** (`micropython/interlog.py`, `interlog_run.py`,
  `scripts/interaction_log.py`; `make interaction-log UNIT=bottle-01`):
  the real firmware runs from the Mac with recording on and **streams** every
  record as a tagged console line to `data/interaction-<unit>-<time>.jsonl` —
  nothing is written to the board's flash (`insights.md` §13). One keypress
  labels a moment, **right hand only** (the left holds the bottle), one row per
  theme: `7 8 9` tap true/false/missed; `u i o p` tilt true/false/missed/stuck;
  `j k l` grabbed/false/missed (grab labels are ground truth for the arbiter's
  future HANDLING state — only `j` means anything today). Console lines are
  marked `▶` for something the bottle *did* (label it) and `·` for information.
  Files carry `label_map: 2`. **Backspace (or `0`) undoes the last label**:
  append-only — an undo record voids an earlier label by id, never an edit, so
  a mislabel and its correction are both visible; loaders use
  `effective_labels()`. Each label records `near`, the events of the previous
  few seconds, because a label pressed right after a tap is written *before*
  that tap's `tap_response` (the device blocks ~1.2 s capturing): association
  must be by time window, never "the last event". `--unit` is required and `--mount base|lid` is
  recorded, because both are facts nobody can recover later.
  - **The capture window is recorded too**, gyro included. `_handle_tap`
    blocks ~1.2 s sampling accel at 240 Hz, and that window is exactly where a
    tap's — and a grab's — signature lives; the main loop is blind during it.
    A small observer hook in the capture loop (`gestures.capture_observer`)
    rides along inside it.
  - **Adaptive rate:** 5 Hz idle, 50 Hz on any motion and for 2 s after, so a
    still bottle does not produce a gigabyte a day and the lead-in to an event
    is never thinned.
  - Raw int16 LSB are logged; unit conversion lives on the host.
  - ⚠ **Bench checks before trusting it:** the gyro reads ≈ 0 at rest and a
    known 90° turn integrates to ≈ 90° (the ODR/register encoding is assumed
    to mirror the accelerometer's; the range/sensitivity is the datasheet
    default, unverified here).
  - **Bench check, from a 5-minute dry run on bottle-01 (2026-09-29; the
    recording itself was discarded as sandbox data):** accel is sound
    (|a| = 1.000 g at rest, sd 0.002). The gyro is alive and sane: rest offset
    ≈ (−62, +3, +40) LSB — under 1 dps at the assumed 8.75 mdps/LSB — with
    ~10 LSB (~0.1 dps) of noise; peak 10.5 k LSB ≈ 92 dps during handling,
    a plausible hand rotation. **Still unverified:** the LSB→dps scale (a known
    90° turn), so treat degrees-per-second as approximate until then. (Correction, same day:
    an earlier note here said the loop runs at ~40 Hz. That was the *logging*
    cap — the Decimator holds ACTIVE_HZ to 50 — and says nothing about the
    loop. The recorder now emits a `rate` event every 5 s; the loop rate is a
    candidate cause of missed taps and is unmeasured until that is read.) **Capture rows were ~5 ms apart, not the recognizer's
    4 ms**: the extra gyro read shifts its cadence slightly — noted, and part
    of why the recorder is not neutral.
  - ⚠ The recorder is not neutral: it adds a gyro read per capture sample and
    prints continuously. If the recognizer behaves differently under it, that
    is a finding, not noise.
- **First look at real data (2026-09-29, one session, 17 triggers — a
  hypothesis, not a finding; §8's bar is n≥30 across sessions):**
  - *Handling separates on gyro.* Mean rotation rate over the second half of
    the capture window: true taps 0.8–0.9 °/s; the triggers that fired during
    a tilt or grab 3.6–84 °/s.
  - *Ambient separates on nothing we measured yet.* Three `false_tap`s were
    quiet in the gyro (0.8–0.9 °/s, i.e. indistinguishable from a real tap) —
    one was a tap on the table. All three had their impulse energy
    **z-dominant (53–79 %)**, against 7–31 % for most true taps (one true tap
    was 50 %). Physically plausible with the IMU on the base: a knock on the
    surface arrives vertically, a touch on the glass arrives sideways. If it
    holds, taps *at the top of the glass* may be legitimately z-heavy — which
    is exactly why position variety is on the collection list below.
  - *The trigger floor is ~50 mg*, and 10 of 17 triggers had `dev` 50–68.
    Energy alone accepted nearly all of them.
- **Second session (2026-09-29, 22 triggers, 4 min) — same pattern, and the
  rate finding.**
  - *Gyro separates handling again.* Every `true_tap` had late-window
    rotation of 0.8–1.1 °/s. Every trigger near a tilt start, a set-down or a
    grab had 2.7–67 °/s, and all of those were responded to. Across the two
    sessions this is a clean split on the data so far — and it is a feature of
    the **existing capture window**, so using it adds no latency. (Ambient
    knocks are the exception: quiet in the gyro, 0.8 °/s, like a true tap.)
  - *The owner's observation, in the data:* the first lean off the table and
    the set-down are read as taps and then, correctly, as tilt — the trigger
    fires on the lift/landing transient before any tilt state exists.
  - *Loop rate is far below design:* `rate` events read 1–57 Hz, median ~35,
    against the recognizer's designed 240 Hz (4 ms tick); ~20 Hz was seen on
    the terminal. Windows near 1–2 Hz are the loop **blocked** by a motion
    word or a tap capture; the ~55 Hz ceiling is the loop's real speed. So the
    trigger sees a bottle sampled every ~18–25 ms, and a tap impulse is a few
    ms wide — its measured `dev` depends on where the samples happened to fall,
    which is a candidate explanation for the spread in `dev` and for missed
    soft taps. **Unattributed:** how much of that is the recorder (a print per
    logged sample over the mount, a gyro read). `make interaction-log
    LEVEL=rate` runs the meter alone; compare its `hz` with `LEVEL=full`.
  - *"Grab" is not a gesture and never was.* Nothing in the firmware
    recognises a grab. `grab_and_tap` was a **data-collection class** in the
    old sandboxes (tap while gripping) and was parked when its pilot reversed
    at n=30 (`insights.md` §9). "Grab" in this plan is the arbiter's future
    HANDLING state; the `j`/`k`/`l` labels are ground truth for it.
- **Third session (2026-10-04) — the loop-rate runs, and a stuck-tilt episode.**
  - *Loop rate is the firmware, not the recorder.* `LEVEL=rate` held 57–60 Hz
    while lit (139 Hz in what look like dark windows); `LEVEL=full` held
    54–56 Hz — the recorder costs ~5 %. About 17 ms an iteration lit against a
    designed 4 ms points at the per-frame render, which runs whether or not
    anything changed; `rate` events now carry `render_ms` to measure it. After a
    tap the loop is also **blind for ~2.7 s** (1.2 s capture + the response
    animation): no tilt update, no second tap.
  - *Pure gyro vs. a veto* (all sessions, 20 true taps / 17 handling / 7
    ambient): late-window gyro is the cleanest handling detector found (true
    taps 0.8–1.2 °/s, no exceptions), but the early gyro peak does not separate
    ambient from taps (1–142 vs 11–240 °/s) and every ambient knock was as quiet
    late as a true tap. Tilt needs the accelerometer's gravity vector. So it is a
    question of which features decide, not veto-vs-base; a gyro-first *trigger*
    is a candidate for the Phase 1 harness to score against the current one.
  - *Stuck tilt, two episodes, ~20–50 s each* (`level=rate`, so no raw samples
    — **not replayable**; re-record at `full`). Engaged at 7.5–9.2° the whole
    time, the state flickering idle/up/down. Two causes visible in the settings
    alone: (1) `TILT_DEADZONE_DEG` is 8.0, so the bottle was resting *on the
    deadzone edge* — chatter, with no hysteresis; (2) release needs 6 s with the
    last 24 samples within 0.5°, so anything that jostles it (a tap while
    engaged, a hand nearby) restarts the clock. A tilt session in progress when
    the display sleeps also freezes rather than ends, since `update()` is not
    called while asleep.
  - *Design smell found while reading it:* **the tilt controller's time
    constants are per-sample, not per-millisecond** — `TILT_SMOOTH_ALPHA`,
    `TILT_ENGAGE_SAMPLES`, `TILT_STILL_WINDOW` and `TILT_BASELINE_ALPHA` all
    advance once per `update()`. They were tuned at the sandbox's ~40 Hz; the
    production loop runs 4–139 Hz. "Engaged after 4 samples" is 29 ms at 139 Hz
    and a full second at 4 Hz; "a still window of 24 samples" is 0.4 s or 6 s.
    That alone can make tilt feel different from minute to minute. Fix in
    milliseconds (alpha from `dt`), independent of the render fix.
- **Collection targets — the holes** (per `insights.md` §8: n≥30 per class,
  ≥2 sessions, before believing anything). Label each as it happens:
  1. **Ambient (`m`)** — deliberate knocks on the table/shelf at several
     distances and on more than one surface, plus real life (door, footsteps).
     Also press `8` if the bottle responded. *Zero rows today.*
  2. **True taps by position and strength** — top/neck, side, near the base;
     fingertip vs nail; soft to hard. *Needed to know whether z-share is a
     safe discriminator or would reject legitimate top taps.*
  3. **Soft taps that do not trigger (`9` missed)** — the trigger floor is
     ~50 mg; how many real, soft taps sit below it? Read `rate` first: a slow
     loop can miss a short impulse outright.
  4. **The reach (failure B)** — approach, touch, grab, tilt, as one motion,
     ×30. Press `8` if it tapped and `j` for the grab.
  5. **Stuck tilt (`p`)** — one instance today. Set the bottle down at
     different angles on different surfaces.
  6. **Tap during tilt, tilt after tap** — the interleavings; today there are
     two.
  7. **Asleep vs awake** — only four wakes recorded; and quiet hours.
  8. **A second session on another day.**
- **Exit:** ≥30 labelled examples of failure B and ≥30 of true taps, across
  at least two sessions (§8's bar), stored under `data/` (gitignored, like
  `rtc-drift.jsonl`), with the unit recorded from the start (see the
  manifest hazard in `dev-status.md`).

### Phase 1 — Replay harness (tests that can fail for the right reason)

- A host-side tool that feeds a recorded JSONL stream through the *real*
  `tilt.py` / trigger / `classify_valid_input` code and reports what the
  pipeline would have decided vs the labels. Uses the same "import the real
  module, never re-derive it" rule the sandboxes already follow.
- This is the regression suite for everything below and the **baseline any
  ML must beat**. It also settles the on-board-detection doc's open
  question — are the failures composition bugs or misclassifications? — with
  numbers instead of an argument.
- **Exit:** the current pipeline's failure rates on the recorded corpus
  reproduce A, B and C. If they do not, the logger is wrong; fix that first.

### Phase 2 — The arbiter (the structural fix)

One pure, host-testable object that owns the tap/tilt relationship, replacing
the ad-hoc coupling in `_run_interactive_loop`. Sketch, not a spec:

- **States:** `IDLE`, `SUSPECT` (an impulse just occurred; verdict pending),
  `HANDLING` (rotation or sustained motion observed), `TILTING`, `SETTLING`.
- **Inputs:** each sample's accel and gyro, the trigger event, tilt
  controller status. **Outputs:** `tap(commit)`, `tap(veto)`, `tilt(allowed)`.
- **Look-back ledger:** taps stay provisional for the settlement window;
  entering `HANDLING`/`TILTING` within it vetoes them and reverts their state
  change (cycle index). Settle early on demonstrated stillness.
- **Fix failure C here, structurally:** tilt release must not depend on the
  state it is trying to leave. Baseline re-learning needs an escape that is
  not gated on `not engaged` — e.g. an engaged session that has been
  demonstrably still (the existing `TILT_STILL_MS` logic) already releases;
  find why it does not in the stuck case *using the Phase 1 recording of it*
  rather than guessing.
- Tests: replay corpus (Phase 1) plus hand-built sequences for each state
  transition.
- **Exit:** failures A and B fall to an agreed rate on the replay corpus
  (propose: <1 false tap per hour of normal living; ≥95% of true taps
  committed), C does not reproduce. Then a real-hardware session in the
  bottle, and only then merge.

### Phase 3 — Gyro-driven features, if the arbiter needs them

If Phase 2 with accel-only still leaves B, add rotation onset/rate as
arbiter inputs. Often the cheapest change with the largest effect; kept as
its own phase so it is measured in isolation rather than bundled.

### Phase 4 — Decide tilt: always-on vs armed (§4)

From the Phase 0/2 data. One config flag; no rewrite.

### Phase 5 — ML, only if the arbiter plateaus

Gate: the arbiter, on the replay corpus, misses the target rate *and* the
misses are misclassifications (an ambiguous window with the right features
available), not control bugs. Then, in order (`on-board-detection.md`):
sensor-die decision trees (MLC) → piezo disc → reservoir/ESN on the captured
window (never continuous on battery). Under a USB-powered lamp/chandelier the
"continuous" objection weakens — inference can run on every window — but the
**per-unit calibration** finding (§8: cross-bottle accuracy 0%) does not go
away, and the Phase 0 recorder becomes the per-unit calibration ritual
(`on-board-detection.md`: "a ten-tap ritual the recipient performs").

## 6. Explicit non-goals

- No new sensor hardware in Phases 0–4. The piezo is a Phase 5 option only.
- No threshold tuning as the fix (§8: proven not to transfer between
  bottles; the same reasoning applies to a lid mount).
- No `grab_and_tap`-style extra gestures (`insights.md` §9, parked). The goal
  is a *reliable light switch*, not a richer vocabulary.
- No changes to the light language or display contracts.

## 7. Risks and open questions

- **Settlement latency vs. feel.** The whole B-fix trades responsiveness for
  correctness; the right window is empirical. Phase 0 must record enough to
  pick it (distribution of "time from false tap to first sign of handling").
- **Mount change.** If the IMU moves to a lid (chandelier), recorded corpora
  from the bottle base do not transfer. The *arbiter* (states, ledger,
  replay tooling) does; thresholds and any trained model do not. Keep
  constants in config and tag every recording with unit + mount.
- **Does a corded lamp even want tilt?** If the form factor changes the
  input vocabulary to tap-only, phases 2–4 shrink to "make tap robust to
  being nudged". The plan is still worth doing first because the arbiter
  and the replay harness are needed either way.
- **Gyro power on the battery variant.** Measure; use `power_budget.py`.
- **A swallowed ACK** (§2) — accepted for now; revisit with data.

## 8. What this plan deliberately does *not* decide

Which form factor wins; whether ML ever ships; whether tilt is a mode. Each
has a decision point above tied to data, not opinion.
