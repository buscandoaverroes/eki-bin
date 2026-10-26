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
- **Phase 0b — the raw-sensor sandbox (2026-10-04; `make imu-record`).** The
  in-situ recorder above records the pipeline *and its failures*: the loop is
  slow, blind for ~2.7 s after a tap, and its tilt constants depend on its own
  rate. So, ahead of any firmware fix: **record the sensor, not the pipeline.**
  `micropython/imu_stream.py` runs nothing else — no recogniser, no render —
  and streams raw accel + gyro at the sensor's rate (240 Hz default; 480/960
  selectable, untested) with its own microsecond clock, a data-ready flag per
  sample and a once-a-second `stat` (achieved Hz, worst gap). Everything the
  firmware would have decided is then **replayed on the Mac through the real
  `tilt.py` / trigger / classifier at any simulated loop rate**, including the
  rate we wish it ran at. The registers are read back into the header, not
  assumed.
  - *Labels are intent, not verdicts* (`scripts/imu_record.py`): what the human
    did. Points: `7 8 9` tap top/body/base, `u i o` knock table / tap another object on the table (`knock_object`; was
    `knock_shelf` in intent-1) /
    bump, `j k l` lift / set down / grab, `p` mark. **States** (press to start,
    again to end): `n` rest_flat, `m` rest_lean, `,` hand_hold, `.` tilting,
    `;` carry. Undo is Backspace/`0`, append-only, as before.
  - *How to cause a stuck tilt on purpose:* you cannot make the firmware stick,
    but you can record its *input* — **`m` rest_lean: set the bottle down at a
    4–12° lean, on a few surfaces, for 30–60 s each**, plus `,` hand_hold and
    `.` tilting around the deadzone edge. Replay then finds the stuck state
    offline, reproducibly, and the regression test is made from the recording.
  - *First dry run of the sandbox (2026-10-04) — and what it fixed.*
  - **Gyro clipped.** `CTRL6` read back as 0 (the default, believed ±125 dps)
    and all three axes hit the int16 limit (32764) during ordinary handling.
    ⚠ **Every gyro figure in this document in °/s was computed at 8.75 mdps/LSB
    and is probably ~2× too high** (4.375 mdps/LSB at ±125 dps); the *ratios and
    separations* are unaffected. The scale is still to be verified with a known
    90° turn. The streamer now sets a wider range (`GYRO_FS=1000` default) and
    the value actually set is read back into the header.
  - **Rate: 165–170 Hz achieved, not 240**, with ~140 failed I2C reads a second
    and a ~8.5 ms stall after every printed batch (~2 samples lost per batch).
    Fixes: a compact 15-byte row, base64-packed (≈30–40 % smaller than text),
    and the bus left alone for 60 % of a sample period after each good read.
    **Not yet re-measured.** The lossless fix is the IMU's own FIFO (it buffers
    through a print stall); its register map has to be checked against the
    datasheet first, so it is not done blind.
  - **Second sandbox run (2026-10-04, 109 s) — gyro scale verified.** Two
    deliberate ~90° tilts, measured independently by the change in the gravity
    vector (89.2° and 87.5°), integrate to **33–35 mdps/LSB** at `CTRL6 = 3` —
    the datasheet's 35 for ±1000 dps. So the FS code table is right, the
    default `CTRL6 = 0` was ±125 dps, and the earlier °/s figures in this
    document were 2× high. No clipping (peak 4124 LSB ≈ 144 °/s); failed reads
    0 (the throttle worked). **But the rate fell to ~77 Hz**: ~82 ms stalls
    between batches, traced to `import struct`/`import binascii` *inside* the
    per-batch functions — under the mount each costs a round trip to the Mac.
    Moved to module top and pinned by a test; not yet re-measured.
  - **Third sandbox run (68 s): 95–119 Hz.** The between-batch stall is back to
    ~8.5 ms (the import fix worked), but ~20 % of sample intervals *inside*
    batches were ~26 ms, evenly spread across row positions — so not the
    print. The throttle's `time.sleep_us` is the suspect (it lets the port
    service USB/the mount); replaced with a spin-wait. Expected ceiling after
    that is ~215–220 Hz (20 samples per ~92 ms); **lossless 240 needs the
    sensor FIFO.**
  - **`make imu-bench`, round 1 — the bottleneck is not output.** With no
    output at all the poll loop still got ~23 Hz (gaps 38–46 ms); garbage
    collection off: no change; printing b64 or text: no change. Reads took
    <0.7 ms and the loop spent <0.07 ms outside them, so it was polling at
    ~1.5 kHz and *not seeing* the data-ready flag. Leading hypothesis: the
    polling interferes — every poll burst-read the output registers, with
    block-data-update on (`CTRL3 = 0x44`). Round 2 compares burst vs.
    status-only reads, tight vs. paced, before the recorder is changed again.
  - **`make imu-bench`, round 2 — found it.** Burst polls (STATUS + data in one
    16-byte read): 78 Hz tight, 39 Hz paced. **Status-only polls (1 byte, then
    the 12 data bytes only when ready): 235 Hz** — tight (6,400 polls/s) and
    paced (310 polls/s) alike. Mechanism: reading the output registers clears
    the data-ready flag, so a sample landing between the status byte and the
    data bytes of one burst was consumed unseen; polling harder lost more.
    The sensor's settings were not at fault — the read pattern was. The
    streamer now polls status-only and paced; expected ~225–235 Hz (one sample
    per batch is still overwritten during the ~8.5 ms print). The FIFO is no
    longer needed at 240 Hz; it would be for 480+.
  - States need an end: `/` ends whichever is open, and quitting closes it, so
    every segment in a file is a closed interval. Ctrl-C/`q` no longer prints a
    traceback (`stop_child` escalates INT → TERM → KILL).
- **First rich recordings (2026-10-04)** — `imu-...-112059` (3.7 min, 135
  point events: taps at three heights ×20, table knocks ×28, taps on other
  objects on the table ×26, bumps ×19) and `-112544` (floor walking and sitting
  on a hard chair ×11). Both 234 Hz, zero failed reads. Which files to analyse,
  which were dry runs, and per-session relabels: `data/imu-sessions.json`.
- *Rich-data checklist for a session:* taps at three heights × soft/hard;
    knocks on the table and a shelf at several distances; lifts and set-downs ×
    30; grabs without lifting; long rests flat and leaned; hand-held still;
    tilting; carrying. Note the surface and whether the bottle is empty or
    filled (`SURFACE=`, `NOTE=`) — it changes the dynamics.
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

- **Built 2026-10-04: `scripts/replay.py` (`make replay`).** Replays
  `data/imu-*.jsonl` through the real `tilt.TiltController`, trigger maths,
  `extract_gesture_features` and `classify_valid_input` at a simulated loop
  rate (`LOOP_HZ=57,240`); the loop's blindness after a trigger is simulated,
  or removed with `--ideal` to score the classifier alone. Labels are matched
  one-to-one, nearest first, in a window of −1.0/+0.2 s (measured label lag:
  median ~330 ms). `--csv` writes one row of features per trigger. Knobs come
  from `data/knobs-bottle-01.json` (the firmware's own recorded snapshot).
- **First results (5 recordings, one bottle, one table, one day):**
  - *Table knocks are the biggest false-tap class, and the z-share veto
    removes them.* Knocks on the table or an object on it were accepted as taps
    17/54 times at 57 Hz and 25/54 at 240; with `z_share < 0.5` it was 1 and 2,
    with **no true tap lost**. Floor footsteps / sitting down: 0/11 already.
  - *The gyro veto removes most handling taps between labelled actions* (the
    unexplained accepted taps in the states session: 23 → 2–3), at a cost of
    1–3 true taps — the threshold (1.5 °/s, bias removed) is a first guess.
  - *Grabs remain hard*: 10–12/39 accepted even with both vetoes. A grab IS a
    touch on the glass; what separates it is what follows (a lift), which is
    the arbiter's settlement window, not a feature.
  - *Faster loop: more real taps triggered (untriggered 13 → 7), and more
    knocks too* — the loop-rate fix and the z veto have to land together.
  - *The tilt constants ARE rate-dependent, confirmed by replay*: deliberate
    tilts engaged in 9/10 segments at 57 Hz but 2/10 at 240 Hz; a lean stuck in
    2/10 at 57 Hz, 0/10 at 240. **Converting tilt to milliseconds must come
    before any loop-rate fix**, or the fix breaks tilt.
  - *Protocol confound:* labels were ~1.3 s apart, but the firmware is busy
    ≥1.2 s after any trigger (2.7 s after an accepted one), so about half the
    tap labels fell in busy windows. Tap-rate numbers from that file are weak;
    future tap sessions want ≥4 s between events, taps and knocks in separate
    files.

- **Shipped from the Phase 1 results (2026-10-04), both verified by replay:**
  1. *Tilt constants are durations* (`TILT_*_MS`; defaults derived from the
     per-sample values as tuned at 25 ms). Deliberate tilts now engage 10/10
     at 57, 139 and 240 Hz (was 2/10 at 240). The lean-induced stuck tilt now
     reproduces identically at every rate (2/10 lean segments) — a stable
     target for the next fix (deadzone hysteresis).
  2. *The vertical-impulse check* (`TAP_VERTICAL_SHARE_MAX = 0.5`,
     `gestures.impulse_vertical_share`), measured against the settled gravity
     vector, not the sensor's z, so it is mount-independent. Firmware verdicts,
     check off → on: knocks on the table/objects accepted **17 → 1 at 57 Hz,
     23 → 1 at 240 Hz**, true taps hit unchanged; it also removes about half
     the handling taps between labelled actions (23 → 12). Bumps rose 0 → 1
     and 2 → 4: a rejected knock no longer blinds the loop, so the next event
     is seen — the busy window, not the check.

- **The energy rule, loosened (replay, 2026-10-04).** With the vertical check
  shipped, `energy < 138k` mostly rejects real taps: in `--ideal` mode (every
  impulse judged) it rejected 10 taps at 57 Hz and 14 at 240. Raising it alone
  trades those back for handling (240 Hz ideal: taps 35 → 48 → 49 of 62 at
  138k / 1M / off; handling accepted 37 → 49 → 93 of 169). **With the
  mid-window gyro check** (rotation 150–400 ms after the trigger < 1.15 °/s,
  bias removed — the feature `docs/classifier-approach.md` found) the trade
  disappears: same tap hits as no check at every setting, and handling at
  1M is 26/169 (off: 31) with stray taps between actions ~0–1. The late-window
  (≥400 ms) version cost 10+ taps — it catches the *next* event when events are
  ~1.3 s apart. Knocks stay at 1/54 throughout. **Next change: the mid-window
  gyro check in firmware, and `TAP_ENERGY_THRESHOLD` ~1M (a gross-handling
  guard, not the tap test).** Needs the gyro on in production and a gyro bias
  estimate that does not come from a pre-trigger buffer the loop does not keep.

- **Shipped: the mid-window gyro check, with a running baseline, and the
  energy guard raised to 1M (2026-10-04).** `TAP_GYRO_MID_MAX_DPS = 1.15`
  (None disables it and leaves the gyro off); `gestures.GyroBias` learns the
  zero-rate offset only while at rest (gated at 5 °/s, τ = 2 s, re-seeds after
  10 s gated out) because the firmware keeps no pre-trigger history; the
  capture reads gyro rows for the first 450 ms only. Replay through the
  firmware's own code path, before (138k, no gyro) → after:

  | | loop 57 | loop 240 | ideal 57 | ideal 240 |
  |---|---|---|---|---|
  | taps hit /62 | 18 → 19 | 21 → 21 | 29 → **38** | 35 → **48** |
  | handling accepted /169 | 12 → 14 | 17 → 19 | 25 → 17 | 37 → 28 |
  | stray taps between actions | 12 → **2** | 13 → **2** | 15 → 2 | 20 → 3 |
  | knocks /54 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |

  The loop-mode tap numbers barely move because ~half the tap labels sit in
  busy windows (protocol confound); ideal mode is the classifier's real gain.
  Not yet run on the bottle. ⚠ A `config.py` that sets
  `TAP_ENERGY_THRESHOLD = 138000` explicitly keeps the old rejection.

- **First feel on the bottle (2026-10-04, `make dev`), after the vertical +
  gyro checks and the 1M energy guard:** weak taps and table noise ignored
  (the owner's preference: err toward ignoring noise — tapping harder is
  easy). A clean pickup is ignored; **a pickup with a "jitter" — a finger
  touch or two, then the lift — still reads as a tap.** Accepted for now;
  it is exactly the arbiter's look-forward case.
- **⚠ Watch: once, asleep, it could not be woken at all** — not by taps, not
  by a hard shake; the next attempt woke on the first tap. Not reproduced.
  Suspects, unverified: `make dev`'s mount, or a `GyroBias` seeded while the
  bottle was being handled — every tap would then read as rotation until the
  10 s re-seed. Cheap guard if it recurs: have the gyro check abstain (None)
  until the baseline has learned for ~2 s at rest. Log any recurrence with
  `make interaction-log`.
  - **Guard added 2026-10-21, at 6 s rather than 2.** `GyroBias.estimate()`
    returns None — "no evidence", never a rejection — until the baseline has
    spent `GYRO_BIAS_WARMUP_MS` (default 3 × `GYRO_BIAS_TAU_MS`) learning at
    rest since its last seed. **2 s would not have been enough:** the gate is
    per-axis 5 dps, so a seed can be off by up to √3 × 5 = 8.7 dps and still
    be learned from; after one time constant that is still 3.2 dps, above
    the 1.15 dps threshold. After three it is 0.43.
    Being gated out (handling) does not restart the warm-up — a good
    baseline that sees a grab is still good — only a re-seed does.
    **Replay can't see this one:** every recording starts at rest, so the
    guard scores identically to no guard (57 and 240 Hz, ideal) — free, but
    also unexercised. The evidence is a test that reproduces the case
    directly (`test_the_unwakeable_case_is_reproduced_and_now_abstains`:
    seeded at 20 dps, a perfectly still bottle reads as ~20 dps of rotation
    on the old path). Whether it was *the* cause of the one observed
    episode is still unknown; `make dev`'s mount remains the other suspect.
  - **⚠ Recurred 2026-10-21 — from FLASH, with the guard deployed** —
    alongside "no tilt". That rules out BOTH suspects above, so the cause is
    still unknown. Two things learned from it:
    - **Taps and tilt sit behind one gate** (`imu_addr` present, phase
      accepts input, not booting), so a single fault stops both. That fits
      the two observations arriving together.
    - **The console printed nothing about the IMU**, so four failures looked
      identical: gate shut (phase stuck), I2C reads failing, nothing
      triggering, everything rejected. Hence an `imu:` line in every 30 s
      block — phase, reads ok/failed/gated, `taps N → M ok (reason …)`,
      tilt state, gyro baseline state. **The next occurrence is diagnosed
      by reading that line, not by guessing.**
  - **✅ DIAGNOSED 2026-10-22/25 — the sensor resets itself.** The new
    `imu:` line read `asleep · reads 4342 ok, 0 failed, 0 gated · taps 0 →
    0 ok · tilt idle 0.0°`: gate open, bus fine, nothing triggering, tilt
    pinned at zero. At the REPL, with the loop stopped but the state kept:
    `WHO_AM_I 0x70` (alive, answering) but **`CTRL1 0x0`, `CTRL2 0x0`,
    `STATUS 0x0`, outputs `(0,0,0)`**. The LSM6DSV16X had reset to its
    power-on defaults while the board kept running — both settings lost at
    once, so a whole-chip reset, not one register clobbered — and the
    firmware, which configured it ONCE at boot, read zeros forever. No I2C
    error, so nothing complained.
    **Writing `CTRL1 = 0x07` by hand revived it** — `(-715, 483, 16276)`,
    0.99 g, `STATUS 0x5` — after a 100 ms wait. No software reset needed.
    (An immediate read after the write still returned zeros: the first
    sample takes a few ms to exist.)
    **Fix — `gestures.ImuWatch`:** 30 consecutive `(0,0,0)` reads (~0.2 s;
    a working accelerometer always reads gravity, and even in free fall its
    noise is several LSB per axis) → `imu_recover()` writes the boot
    settings again and resets the gyro baseline, which had been learning
    from zeros. Zero samples are never passed on — to the trigger, the
    first real one would be a 1 g step, a false tap. Plus a slow check:
    CTRL1/CTRL2 read every 30 s, for a reset whose outputs freeze non-zero.
    Retries at most every 5 s. Each recovery prints the display state and
    brightness, and the `imu:` line counts `ZERO` reads and recoveries.
    **Still unknown: WHY it resets.** Candidates: a dip in the sensor's
    supply (§13 — the strip has browned the board out before), a glitch
    from touch (September: touching the IMU gave EIO), or something on the
    shared bus. Recoveries clustering while the display is lit and bright
    would point at the supply, and at the load switch / decoupling work.
    **✅ Answered 2026-10-26: the wiring, at certain angles.** The guided
    session (strip dark: `imu_stream` drives no LEDs) reset 12 times in
    683 s. 11 came during handling and none in 30 taps, with no shock in the
    300 ms before any of them. 8 of 12 came while the bottle leaned toward one
    sector (~60–115° in the sensor frame), some at only 13–26° of lean.
    About 25 tilts leaning the other way, many past 45°, never reset. So
    not impact, not touch, not the strip's load: a loose wire inside the
    bottle making intermittent contact in one direction (the owner saw the
    same pattern by hand). A whole-chip reset suggests the sensor's power
    or ground. **Fix: the harness (wall #2), not firmware.** `ImuWatch`
    stays as the safety net. The reset count per session is the test of
    whether a harness fixed it.
  - **Found while reading the gate, NOT today's cause:** `_TapCycleState`,
    `_StatusMessage` and `tilt._elapsed` compared `ticks_ms()` stamps with
    plain subtraction. `ticks_ms` wraps every ~12.4 days (2**30 ms) and the
    rp2 hardware timer survives soft resets, so a wake in progress at the
    wrap left the phase in `waking` forever — gate shut, no taps, no tilt,
    until a power cycle. Fixed with `primitives.ticks_since`. It cannot
    explain today's episode: a fresh flash restarts the counter near zero.

### Between Phase 1 and 2 — the frame, and what the data says (2026-10-25)

**The frame: detect → arbiter → classify.** Every idea so far —
thresholds, trees, an ESN as a classifier, an ESN as an anomaly detector —
fits one of three roles, and the roles do not compete:

| role | job | starts as | earns a change by |
|---|---|---|---|
| **detect** | *when to look* — did anything happen? | the fixed trigger, on this table | evidence the table version fails somewhere |
| **the arbiter** | *when to decide* | a settlement window, length from the data below | — it is required whatever the stages are |
| **classify** | *what it was* | the current rules (energy, vertical, gyro) | beating them on replay |

*Named detect / arbiter / classify, not Stage 1 / Stage 2: the display
pipeline already owns those words (design principle 9, `tests/test_stage1.py`),
and this doc used them for both until 2026-10-26.*

**The rule for detect and classify: start with the controlled condition.** A fixed
threshold on one table, not learned and not adaptive. Prove it there. Only
then test an adaptive detect against it — a threshold scaled to the recent
noise first, and an ESN only if the background turns out to have a rhythm a
predictor could learn (music through a shelf, a compressor, a train line).
Music is a variable to add on purpose later, not the starting case.

**The problem, decomposed:**

1. **Detection** — did anything happen? Depends on the room (below).
2. **Discrimination** — what was it?
   - knock through the table vs a touch: separable *at impact* — handled
     (vertical share, 17 → 1)
   - lift / set-down vs a tap: largely handled (0/50, 2/51 false taps)
   - **a grab beginning vs a tap: open** — overlapping, needs the aftermath
   - kinds of tap (double, position): deferred; §8's limits stand
3. **Timing** — when can a verdict be trusted? (below: ~200 ms+)
4. **Transfer** — other bottles (the glass's own response) and other rooms
   (the background). Different problems: subtracting a room's background does
   not change how a heavier bottle answers a tap.

#### When does a grab stop looking like a tap?

50 labelled taps vs 37 grabs (and 48 knocks), five sessions, bottle-01, one
wood table. Features in slices after the trigger, against a baseline from
0.6–0.1 s before it. AUC: 0.5 = indistinguishable, 1.0 = fully separable.

| ms after impact | tap vs grab, best AUC | | tap vs knock |
|---|---|---|---|
| 0–30 | 0.83 rotation | grabs twist ~2× harder (31 vs 16 dps median) | 0.97 |
| 30–100 | 0.64 | nearly identical | 0.95 |
| **100–200** | **0.85** movement | **tap settled (1.8 mg), grab still moving (8.0 mg)** | 0.77 |
| 200–400 | 0.68 | the hand has closed and paused | 0.81 |
| 400–800 | 0.78 | a held bottle trembles; one on a table does not | 0.71 |

**No single window separates a tap from a grab; the difference is a shape
across ~800 ms.** That is the definition of a problem that has to wait and
combine windows — the arbiter's job, not a better threshold's. It also
corrects an earlier claim in this repo's conversation that the two are
*identical* at impact: they are not (0.83), but they overlap too much to
call there.

Knocks, by contrast, separate right at impact (they arrive weaker, through
the table), which is why the vertical check worked so cleanly.

⚠ One bottle, one table, one day. §8's rule applies: a hypothesis until a
second session agrees.

#### Moving the gyro window earlier does not help — measured

The timing table suggested the shipped gyro check (150–400 ms) partly
misses where grabs differ (100–200 ms). Swept through the firmware's own
path (`TAP_GYRO_MID_START_MS/END_MS`, replay, 240 Hz ideal, energy 1M,
vertical 0.5):

| window | thr | taps kept | grabs accepted |
|---|---|---|---|
| **150–400 (shipped)** | **1.15** | **48/62** | **22** |
| 120–300 | 1.15 | 45 | 18 |
| 120–300 | 0.8 | 44 | 15 |
| 100–250 | 0.8 | 38 | 11 |
| 100–200 | 0.8 | 36 | 9 |

**Every grab rejected costs about one real tap.** Taps rock the bottle
too, and some are still rocking at 100–150 ms, so any single rotation
threshold that catches grabs catches taps. That is the timing table's
overlap made concrete, and it is the evidence this check is at its limit:
the remaining grabs are the arbiter's, not a retune's. Shipped defaults
kept. (Tapping harder does not rescue it — a harder tap rocks more.)

#### The noise floor is not zero

| | accel deviation | gyro |
|---|---|---|
| untouched on the table, median | 1.0 mg | 0.06 dps |
| untouched, 99.9th percentile | 10.5 mg (max 37) | 1.4 dps |
| someone walking around it | **7–50 mg** | |
| trigger threshold | **50 mg** | |
| a median tap, first 30 ms | ~170 mg | |

The loudest footstep reached the trigger threshold exactly. The room is a
real input, and detect has a real job — but the controlled-condition rule
still says: fix the table case first.

#### Sample rate, SPI, MicroPython

- **The tap/grab difference lives at hand-motion timescales** (tens to
  hundreds of ms). At 240 Hz the decisive 100–200 ms window holds ~25
  samples. SPI would not add information for this question.
- **Rate does matter for *detection*:** replayed at 57 Hz, 20 of 62 taps
  never triggered; at 240 Hz, 12. Short impulses fall between samples.
- **The limit is the MicroPython loop (~145 Hz with rendering), not I²C**,
  which could sustain kHz reads. The no-soldering fix, if rate becomes the
  bottleneck, is the IMU's **FIFO**: the chip buffers at full ODR and the
  loop collects batches. Unused today.
- Rust buys compute headroom (a continuous ESN), not information.

#### A simulator: replay, with pluggable stages and a live source

Enough data exists to develop and compare stage designs **for the table
case** — not to prove them (one bottle, one day), and none at all for other
rooms. The simulator is an extension of `scripts/replay.py`, not a new tool:

1. **Blocks as plug-ins.** Detect, the arbiter and classify become objects
   the harness drives, with today's firmware behaviour as the baseline.
2. **The arbiter is written as a pure firmware module** (like `tilt.py`),
   which the harness imports — one implementation, scored on recordings,
   then switched on in `main.py`. Never a parallel copy.
3. **A live source.** `make imu-record` already streams raw samples to the
   Mac in the recording format; a `--follow` mode tails that file and runs
   the same pipeline as it arrives, printing verdicts (committed / vetoed /
   why). The bottle on the bench, the Mac deciding — a design loop with no
   upload in it.

**Data still needed:** a session that deliberately interleaves *tap only*
and *grab → tilt*, labelled — the exact discrimination this is about — and a
second day, to validate rather than develop.

#### The first dry run of that session (2026-10-26), and what it changed

Two things, both about the recording rather than the bottle:

1. **The stream died 2.1 s in, silently.** The last rows were real gravity,
   then nothing for a minute, while the Mac went on printing "234 Hz". Most
   likely the IMU reset itself again (§ the IMU resets itself). The stream
   couldn't say so: it waited quietly for data, and its heartbeat only
   printed when data came. It now heartbeats on wall time, and after 100 ms
   without data it checks CTRL1 and revives a reset sensor (an `imu_reset`
   event). The Mac warns `STREAM STALLED` within 1.5 s.
2. **Labelling by hand bent the motion being measured.** With one hand on
   the bottle and one on the keys (`l` at the grab, `.` at the tilt), the
   grab came out as a performance, not a natural movement. Since the
   order is known in advance, the recorder now **cues** the trials
   (`PROTOCOL=tap-vs-grab`). A countdown shows the instruction in words, then
   a beep for GO. Space means done, `r` means redo. The **cue** is the label.
   The act's timing comes from the data, inside the window [GO, done]:
   hand-pressed times were late anyway (press *after*, plus reaction time).
   Botched attempts stay in the file, labelled `redo`. Records and reasons:
   `scripts/imu_protocol.py`; `imu_protocol.trials()` reads them back.

   ⚠ For analysis: the space press that ends a trial is itself a knock on
   the table if the keyboard shares it. It sits at the window's `done`
   edge, so trim the last ~300 ms or put the keyboard elsewhere.

#### The baseline: shipped firmware on the guided session (2026-10-26)

`imu-bottle-01-20261026-193043`, 68 kept trials, shipping knobs (energy
1e6, vertical share 0.5, gyro 150–400 ms ≤ 1.15 dps):

| loop | taps accepted | grab/hold trials with a false tap | tap-wait-grab: tap / false after | hands-off countdowns |
|---|---|---|---|---|
| 240 Hz, no blindness | 15/30 | 16/30 (20 false taps) | 5/8 · 2 | 0 |
| 240 Hz | 15/30 | 16/30 (20) | 5/8 · 2 | 0 |
| 145 Hz (≈ with rendering) | 9/30 | 15/30 | 5/8 · 0 | 0 |
| 57 Hz | 4/30 | 12/30 | 3/8 · 0 | 0 |

**Of the 15 taps missed at 240 Hz, 12 never triggered: a detect loss, not
a classify one.** The trigger watches the change in the *length* of the
acceleration vector, |a|. A tap on the side of an upright bottle pushes it
sideways, which rotates the vector and barely lengthens it. Every one of
the 30 taps moved the vector by 54–865 mg (median ~210). Measured as |a|,
that was 5–298 mg, typically 3–5× smaller. The earlier hand-labelled
sessions (48/62) had harder, performed taps. Guided taps are natural ones,
and natural taps are gentle. The arbiter can't commit a tap that detect
never hands it, so **detect comes first**: trigger on the high-passed
vector (a minus a slow baseline vector), then re-measure the noise floor
in those terms. The chip's own wake-up detection works on high-passed
per-axis data, so this also points the way to moving detect onto the
chip.

The hands-off countdowns produced no false taps. Accepted taps outside the
kept trials all fell in redone attempts (real handling) or just after a
sensor reset (the first samples after a reconfigure).

#### The simulator, and detect's first swap (2026-10-26)

`scripts/sim.py` (`make sim`, `make sim-live`) is replay with the blocks
pulled apart: LOOP → DETECT → ARBITER → CLASSIFY, plus the tilt controller
in parallel. What ships fills every slot. With those blocks it reproduces
`replay.replay()` exactly, every event and feature, on real recordings at
57/145/240 Hz and in ideal mode (`tests/test_sim.py` pins it on synthetic
streams). It processes one sample at a time and never looks ahead, so
`--follow` runs the same pipeline on a recording while it is being made.

First swap, **detect = vector**: ‖a − per-axis median‖ instead of
|a| − median(|a|). The buffer, the 50 mg threshold and classify are all
unchanged, so the only difference is the geometry.

| | magnitude (ships) | vector |
|---|---|---|
| natural taps, guided, 240 Hz | 15/30 (18 triggered) | **29/30 (30)** |
| natural taps, guided, 145 Hz | 9/30 | **29/30** |
| performed taps, 2026-10-04, ideal | 48/62 | **59/62** |
| knocks: table · other object (ideal) | 0/28 · 1/26 | 0/28 · 1/26 |
| bumps (ideal) | 5/19 | 7/19 |
| guided grab trials with a false tap, 240 Hz | 16/30 | 14/30 |
| set_down · release with a false tap (ideal) | 2/51 · 4/29 | **9/51 · 13/29** |
| rest_flat (151 s) · guided countdowns (~7 min) | 0 · 0 accepted | 0 · 0 accepted |

- **Recall is solved for this table**, and the loop rate stops mattering:
  the vector deviation is 3–5× larger, so the impulse stays above threshold
  for long enough that a 145 Hz loop still sees it.
- **The cost is the hand leaving the bottle.** Set-downs and releases
  trigger more and pass classify more. They come straight after the hand has
  been holding the bottle, so this is the arbiter's look-back veto, not a
  threshold to raise.
- **The noise floor isn't proven yet.** About 9 minutes of hands-off data,
  one table, a quiet room, nothing for footsteps. A rest-heavy session
  (footsteps, door, a chair) is needed before this ships.
- Live, trial 1 of the session shows the arbiter's case in one line: a
  grab held still passes classify (no rotation in 150–400 ms), and the tilt
  engages a second later.

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
