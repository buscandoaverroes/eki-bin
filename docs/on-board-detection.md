# On-board detection — ESN, and the options ahead of it

**Status: analysis. Nothing built.** Written 2026-09-14, after four days of
adding gates to `tilt.py` and still hitting a stuck state on hardware.

Supersedes the one-paragraph ESN entry in `dev-status.md`, which said the
right things about *what* ESN is for and nothing about whether it is the
next thing to do.

---

## 1. The strongest argument for ESN is not "this is getting complicated"

It is that **what has been hand-built is already a reservoir, badly tuned.**

| in `tilt.py` | what it actually is |
|---|---|
| `TILT_SMOOTH_ALPHA` (EMA on gravity direction) | a leaky integrator |
| the 24-sample jitter window | short-term memory |
| `TILT_BASELINE_ALPHA` (neutral re-learning) | slow-decay state |
| `TILT_ENGAGE_SAMPLES` | another time constant |

Three or four hand-chosen time constants feeding a hand-written decision
rule. A reservoir is *N random* time constants feeding a **trained**
readout. The same architecture was arrived at independently, by hand — and
the difficulty now is tuning the constants, which is precisely the part a
reservoir does not ask anyone to choose.

It also lands on `insights.md` §8's own criterion. That section was
specific: the classifier earned its complexity exactly when the signal
needed *multiple features combined*, and lost to a plain threshold when one
feature sufficed. **Every gate added since is a feature.** The need for
several has now been demonstrated empirically — by building them one at a
time and watching each one fail to be enough.

## 2. The counter-argument, and it decides the sequencing

**The failures actually being hit are composition bugs, not
misclassifications.**

"Sitting flat and stuck" is control flow, not a wrong verdict: the baseline
leak is gated on `not engaged`, so a stuck session blocks the very
re-learning that would unstick it. That is a deadlock. A classifier does
not fix a deadlock — an ESN sits **inside** a state machine, it does not
replace one.

So bolting ESN onto a state machine that deadlocks adds complexity without
removing the bug, and worse, hides it: a learned model would be blamed for
a failure it did not cause.

> **Fix the state machine structurally first.** Then the ESN question
> becomes clean — replacing a working-but-brittle classifier, with
> something to compare against, rather than papering over a control bug.

Two further cautions that have not gone away:

- ESN needs labelled data, and these failures are **rare and situational**.
  "The bottle was resting somewhere the reference didn't expect" is hard to
  produce on demand and harder to label.
- §8's methodology rule stands: anything validated at n<30 or in a single
  session is a hypothesis. Every failure recorded so far is n=1.

## 3. Three things to do before ESN

Ranked. **Do 3 before 1, and 1 before ESN.**

### ① The LSM6DSV16X's MLC and FSM — already soldered in

`hardware.md` notes the Machine Learning Core and Finite State Machine as
deliberately unused. The MLC runs decision trees **on the sensor die at
microamps, while the MCU sleeps.** For the battery build that is not an
optimisation, it is a different power class — and it competes with ESN for
the same job, on silicon already paid for.

### ② A piezo disc — and it is the most on-theme option available

The whole metaphor of this project is **struck glass**
(`light-language.md` §1). A contact piezo would hear the **actual ring**.

That is not just poetic. A tap is a *narrowband resonance*; handling noise
is *broadband*. Those separate far more cleanly in frequency than they do
in accelerometer magnitude, where §8 fought to 98.4% across fifteen
sessions and stalled. And it is the **physically independent modality**
`surface-as-input.md` §5 argues is the real prize — information no amount
of accelerometer feature engineering can synthesise.

Cents, one ADC pin. Parts and the electrical traps: `shopping-battery-power.md`.

### ③ The gyro axes — free, and aimed at today's bug

Already on the chip, still unused, and directly relevant: **rotation rate
separates the three cases that keep being confused.**

| | rotation | translation |
|---|---|---|
| tilt | sustained, slow | none |
| tap | near zero | impulse |
| pick-up | transient | sustained |

The accelerometer sees only the second column. Half the evidence has been
sitting unread the entire time.

### (④ The capacitive contact electrode)

`surface-as-input.md` §5's existing recommendation, still good. More BOM
than the gyro, less than a mic, and it answers "is it being touched" rather
than "what happened" — complementary to all of the above.

## 4. Microphones: the wall is conceptual, not technical

**The common assumption is wrong** — keyword spotting on this class of MCU
is routine. TFLite-Micro's reference example is "yes/no" in ~20 KB on a
Cortex-M4; the RP2350 is dual Cortex-M33 at 150 MHz with FPU and DSP
extensions, comfortably above that; Espressif ships a production wake word
on the ESP32-S3. Sound-event classification is not an easier fallback
either — similar cost, arguably harder.

Two practical blockers: **power** (continuous sampling + MFCC + inference
is milliamps against a 1 mA idle target — always-on KWS and a two-month
battery are mutually exclusive) and a **microphone** with an acoustic path
through glass.

**But the real blocker is the concept, and it should be recorded as a
decision rather than a constraint:**

> You don't talk to your bottle. A voice interface introduces a creepy
> factor that is antithetical to an innocent object that is not connected
> to the internet.

That is consistent with everything else here — "ambient, not demanding",
no phone, no screen, no radio in V2 normal operation. A jar you address is
a gadget, and the whole design exists to avoid being one.

**The interesting middle survives**: listening to the *glass* rather than
to a person. That is option ②, and it needs no model, no wake word, and
nothing that could ever be mistaken for listening to a room.
