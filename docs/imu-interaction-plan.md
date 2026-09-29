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

### Phase 0 — Record everything, unfiltered (no behaviour change)

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
