# eki-ishi (駅石) — Glass Stone Concept Note

_Living document, opened 2026-08-16 from a brainstorming session. **Nothing here
is committed or decided** — this is a form-factor proposal that would change
several things `docs/concept.md` currently locks. Read alongside
`docs/roadmap.md` § Form-Factor Philosophy, which already frames variants as
parallel research threads rather than a linear progression._

> **Name:** provisional. 駅石 ("station stone"), by analogy with 駅瓶
> ("station jar"). Coined in the session that produced this doc; not settled.

---

## 1. The object

A hand-blown solid glass "pebble" — an irregular, stone-like form, roughly the
size of a softball, **clear** with internal bubbles and waves. Shining an
8-LED stick up through it from underneath (`led_test.py`, cursory bench check
only) revealed real internal structure: the light doesn't simply pass through,
it catches on the internal irregularities and renders a pattern.

The proposal: build the whole system as **a stand the stone sits on** — a
crafted base (wood, metal) holding the electronics, with the stone as the
display surface and the interaction surface.

---

## 2. Why this is a big deal: the constraint that goes away

The bottle paradigm is **hardware-defined software at its core, and that was
the point** — a great many decisions across this repo trace back to one
number: a wine/sake bottle bore of ~18–19mm. The XIAO ESP32-C3 was chosen
over the Pico 2W largely because it is ~17.8mm wide (`docs/roadmap.md` § v1.1);
`docs/insights.md` §5 records the Pico "won't fit most bottle tops" as a real
form-factor finding. Qi wireless power exists in the design because there was
no way to run a wire in without drilling the glass.

A stand removes that constraint entirely, and several stalled or impossible
threads move at once. This is the actual argument for the pivot — not that
the stone is prettier.

| Thread | Status in bottle paradigm | Status on a stand |
|---|---|---|
| **JJY radio time receiver** | Impossible — ferrite bar antennas are ~30–40mm, no candidate fits the neck | Becomes possible → see `docs/jjy-time-signal.md` |
| **True no-WiFi operation** | Blocked on the above; DS3231 + annual NFC tap was the workaround | Follows directly from JJY |
| **Onboard NFC *reader*** | No space; forced the ST25DV *tag* architecture instead | PN532-class reader fits in/behind the stand → see `docs/nfc-provisioning.md` §8 |
| **Phone-free provisioning** | Stuck since 2026-07-23 (custom iOS app blocked on Xcode/Intel-Mac/$99 dev program) | Unblocked by the reader + USB-writer path |
| **Power** | Qi coil, FOD risk, 800mA ceiling, brightness capped ≈0.15 (`docs/hardware.md`) | Wired USB-C to the wall — honest, and no worse visually than the Qi pad's own cable |
| **Battery/standalone research** | An entire open thread (LPCD readers, CR2032 math, µA sleep budgets — `docs/roadmap.md`) | Moot. Wired power retires the thread |
| **MCU choice** | Constrained to narrow boards | Reopens — see §6 |

**Power, stated plainly:** running a USB-C cable from the stand to the wall is
not a regression from Qi. The Qi pad *also* has a visible cable to the wall.
The bottle's "no visible wire" property was always local to the bottle itself,
never to the shelf.

---

## 3. What it costs: the display paradigm does not survive

This is the real price, and it should not be glossed.

**Positionality dies.** `ApproachContract`
(`docs/contracts/approach-contract.md`) — anchor, arms, markers, CHASE
transitions, the whole positional vocabulary — depends on a viewer being able
to resolve *which LED* is lit along a line. Light diffused up through a solid
irregular mass does not preserve that. Arc-of-light-as-arc-of-time, locked in
`docs/concept.md` § Design Principles #3, goes with it.

**Colour becomes the dominant discriminator, and this is genuinely better
here.** The bottle work fought glass tint constantly: the brown gift jar
shifts white → soft orange-white, forest green → yellow-green, gray → yellow
(`docs/hardware.md`, 2026-07-23). Every palette had to be tuned per enclosure,
and `docs/insights.md` §3 found red vs. orange ambiguous through brown glass at
distance. **The stone is clear — it has no meaningful tint of its own**, so
hue arrives roughly as rendered. In the bottle world positionality beat colour;
in the stone world that inverts.

**Brightness is a 2–3 level enum, not a continuous axis.** Much of the light
passes through rather than being contained, so the usable dynamic range is
small. Two implications:
- More LEDs mostly add ambiguous brightness rather than information — the
  "count the LEDs" affordance of the bottle (`docs/insights.md` §3) is gone.
- **Design recommendation:** treat brightness as a small enum (off / dim /
  full) rather than a continuous multiplier. This also sidesteps, by
  construction, the entire recurring bug class this project has hit four
  separate times — gamma/dither flicker at low brightness
  (`docs/insights.md` §6, `dev-status.md` § V1.4 passes 1–2, § CHASE
  transition, § LED status messages' "never blend between states" rule).
  Those bugs only bite when rendering smooth continuous ramps at low values.
  A three-level enum cannot express one.

Enough brightness range remains for the tap/ACK-CONFIRM jolt to land
(`docs/contracts/gesture-envelope.md`) — but note that the jolt's whole
tap-strength-scaling feature currently spans 0.35–6.0× and was widened three
times to stay perceptible through *frosted* glass. Through clear glass with
less containment, expect to re-derive that range from scratch, not port it.

**And a direct conflict this section has to own, not just note:** the
brightness-enum recommendation immediately above and the tap-strength-scaling
feature immediately after it **cannot both survive**. Strength-scaled ACK
brightness *is* a continuous multiplier — a 2–3 level enum can express at most
2–3 strengths, which is not "a harder tap glows brighter," it is "a harder tap
crosses a threshold." §5's "nothing needs simplifying" is true of the
**recognizer and state machine** (`classify_valid_input`, `_TapCycleState` —
genuinely portable), but it is **not** true of the jolt's UX layer, which is
the part that took five real-hardware rounds to tune and is built entirely on
continuous amplitude.

The resolution is probably not to fight for continuous brightness here but to
**move the strength axis onto a different channel that clear glass doesn't
compress**:

| Channel | Viability on the stone | Note |
|---|---|---|
| Brightness (today) | Poor — the enum problem above | The whole 0.35–6.0× range collapses |
| **Duration** | Good | A harder tap holds the ACK longer. Time isn't attenuated by glass at all |
| **Pulse count** | Good | 1 pulse vs. 2 — discrete by nature, so it *composes* with a brightness enum instead of fighting it |
| **Hue** | Promising, untested | §3 already argues colour is the stone's strong axis; a strength→hue-shift is unexplored and cheap to try |

Worth deciding deliberately if this form factor is ever adopted, rather than
discovering it when the jolt is ported and reads as flat. Filed as an open
question (§8.9).

**A new contract paradigm is needed.** Not designed yet. Colour + pulsing +
2–3 brightness levels is the raw material. This is a real piece of scope, not
a config change.

---

## 4. The stand — the open question that blocks everything else

**Nothing else can be resolved before a candidate stand exists.** IMU
viability, NFC reader placement, JJY antenna siting, and the enclosure volume
budget all depend on it.

In keeping with the project's craft spirit (finding an object made for
something else and revealing it as something new — the same instinct behind
the honey-jar-that-is-actually-a-departure-board), candidates from Japanese
craft traditions:

| Candidate | Why | Watch out for |
|---|---|---|
| **Suiseki daiza (水石台座)** — carved wooden pedestal for displaying viewing stones | **Strongest match.** An entire craft tradition that exists specifically to cradle an irregular stone's exact base contour. Hardwood → RF-transparent for NFC, non-conductive, often already has a shaped cavity underneath | Custom-carved to a *specific* stone; may need commissioning. Cavity volume unknown |
| **Koro (香炉)** — metal/bronze incense burner | Real hollow volume, hides parts, "holds the stone on high" | **Conductive.** 13.56MHz NFC will not read through a bronze body (`docs/hardware.md` § NFC RF mounting). Reader would need an external position or a non-conductive top insert |
| **Chataku / small tea-ceremony stands (茶托・棚)** | Elegant, minimal, lacquered wood, good RF | Likely too shallow for XIAO + LEDs + reader |
| **Choco / masu (木製おちょこ・枡)** — square wooden sake cup | Cheap, available, wood, right scale | Aesthetically casual; may read as improvised rather than crafted |

**Recommendation:** pursue suiseki daiza first. It is the only candidate where
the tradition's *purpose*, not merely its look, already matches the physical
problem.

_(Buddhist statue pedestals — 仏像台座 — have a similar form language and were
raised in discussion, but repurposing a specifically ritual object for a
gadget deserves a deliberate decision rather than a casual one. Noted, not
recommended.)_

---

## 5. Interaction: IMU on a rigid mount

**The current gesture contract already fits this form factor without
modification.** `docs/contracts/gesture-envelope.md` scoped down — after ~15
sessions and two bottles — to single-tap-only, position-agnostic
tap-vs-noise detection, because multi-tap counting and position
disambiguation both failed to hold up at scale while tap presence stayed at
95–98%+ (`docs/insights.md` §8–9). "Single tap, no location disambiguation"
is what already shipped. Nothing needs simplifying.

**Two reasons to expect *better* data than the bottle gave:**

1. **The dominant noise source was the bottle's own rocking.** That is
   explicitly what broke 2-tap counting ("one tap plus rocking echo" vs. two
   real taps) and what made shoulder-vs-base separability drift 96.7% → 71.2%
   → 81.7% across three sessions on the same bottle. A dense solid mass
   rigidly fastened to a stand has far less freedom to wobble. Metal in
   particular is stiff and low-damping compared to a hollow glass wall.
2. **Base was the best position ever measured** — 98–100% for single-tap
   presence, the strongest number in the whole investigation, and the physical
   ordering (base > shoulder > body > neck) tracked distance from the grounded
   contact point. An IMU at the stone's contact point or on a stand leg *is*
   the base position.

**Caveats that must not be skipped:**
- **Absolute mg thresholds will not transfer.** This is the single most
  repeated finding in `docs/insights.md` §8: amplitude features are bound to a
  specific object's mass and geometry (cross-bottle position accuracy was
  **0%** — worse than random). Timing features generalised; amplitude never
  did. Budget a fresh `vibration_sandbox.py` session on the real stone+stand.
- **The joints matter as much as the sensor position.** A cushioned or loose
  stone-to-stand or stand-to-leg joint reintroduces exactly the damping the
  rigid mount is meant to remove.
- **n<30 or single-session results are hypotheses, not results** — the
  methodology lesson §9 states plainly after it cost real rework four times.

**Unused hardware worth trying here:** the LSM6DSV16X is 6-axis, but every
classifier built so far used **accelerometer features only**. A lateral swipe
across the stone's textured top plausibly produces a **gyro** signature a
vertical tap does not — and a rigid mount would transmit that distinction
cleanly instead of smearing it into wobble. Collect gyro alongside accel from
the first session.

---

## 6. MCU choice reopens

The bottle-neck bore is why the Pico 2W was set aside as a target
(`docs/insights.md` §5) despite being the better dev-ergonomics board and the
tentative V2 Rust choice (`dev-status.md` § Open decisions). A stand has room
for a board of nearly any size.

This does **not** automatically mean switching. The XIAO ESP32-C3 has passed a
real portability checkpoint on this exact firmware (v1.2, `docs/roadmap.md`)
and staying put has genuine value. But the selection criteria change shape:

- **Width stops being a criterion at all.**
- **Comms may stop being a criterion.** With JJY handling time and a book of
  NFC stickers handling provisioning, a board with no WiFi/BT at all becomes
  viable — and dropping the radio is often what buys a chip better analog, more
  RAM, or lower power at the same price.
- **An on-chip ML/DSP core becomes newly interesting** — see §7.

Worth an explicit look when the stand exists, not before. Note that the
LSM6DSV16X *already* contains an unused Machine Learning Core / Finite State
Machine in the sensor itself (`docs/hardware.md`) — some of the "want an ML
core" requirement may already be satisfied by hardware in hand.

---

## 7. Capacitive contact sensing + IMU — the pairing worth pulling forward

Full exploration: `docs/surface-as-input.md`. The short version, because it
bears directly on the gesture work rather than being a separate research
thread:

A single self-capacitance electrode under the stone can plausibly give a
binary **"the stone is being touched right now"** — no position, no gesture,
just contact state. That is precisely the signal an accelerometer cannot
produce, and it composes with the IMU:

| Event | IMU alone (today) | IMU + contact electrode |
|---|---|---|
| Deliberate tap | impulse | brief contact **+** impulse |
| Drag / swipe | ambiguous vibration | sustained contact **+** sustained micro-vibration |
| Mug set down nearby | impulse — the false-positive problem §8–9 spent 15 sessions on | vibration with **no contact at all** → rejected trivially |

That last row may be the real prize: a second, **physically independent**
signal that no amount of accelerometer feature engineering can synthesise.

**And this is prime material for the ML approach that already proved itself
here.** `docs/insights.md` §8's finding was specific: the trained classifier
earned its complexity exactly when the signal genuinely needed *multiple
features combined* (tap-count: 55% → 91–92%), and lost to a simple threshold
when one feature already sufficed (muji *position*, neck vs. body: 98.3%
threshold vs. 95–97% classifier). Two independent sensor modalities, plus a rigid mount that
removes the session-to-session drift which sabotaged the position work, is the
condition under which that finding predicts a classifier should do well.
Expect a **per-unit trained model**, though — that is already the accepted
plan for tap thresholds (§8's dev-time-calibration resolution), and a
different stone or stand would still shift the signal.

---

## 8. Open questions

1. **Find a candidate stand.** Blocks everything else. (§4)
2. **Design the new display contract** — colour + pulse + 2–3 brightness
   levels, replacing positionality. Not started. (§3)
3. **Does a rigid mount actually give cleaner IMU data?** Hypothesis with good
   mechanical reasoning, zero data. (§5)
4. **Can the IMU resolve tap vs. swipe** — and does gyro help? (§5)
5. **JJY sourcing and indoor reception** — `docs/jjy-time-signal.md`.
6. **MCU re-evaluation** once volume is known. (§6)
7. **Capacitive contact electrode** — cheap to falsify, do it early. (§7)
8. **Does the stone's optical character survive a real contract?** The bench
   check was one LED stick, cursory. `docs/insights.md` §3 is the precedent for
   how much a real enclosure assessment can change the plan.
9. **Which channel carries tap strength, if not brightness?** Duration, pulse
   count, and hue are the candidates; a brightness enum and continuous
   strength-scaling are mutually exclusive. (§3)

---

## 9. Relationship to existing docs

This does **not** supersede the bottle paradigm. `docs/roadmap.md` explicitly
frames form factors as parallel threads differentiated by dev barrier, not a
linear progression — eki-bin v1.1/v1.4 (the friend gift build) continues
independently and is unaffected by anything here.

What this *would* supersede, **if adopted**:
- `docs/concept.md`'s form factor, orientation/magnetometer mode selection, Qi
  power architecture, and the arc-of-light display principle.
- `docs/contracts/approach-contract.md` as the target paradigm (it remains
  correct and shipped for the bottle build).
- The battery/standalone research thread in `docs/roadmap.md`.

What carries over **unchanged**:
- The two-stage pipeline `time → LeaveSignal → DisplayContract → LEDs`. A new
  contract is a Stage 2 swap — exactly what the architecture was built for
  (`docs/insights.md` §2).
- `LeaveSignal`, urgency classification, walk-time subtraction, schedule
  handling — all Stage 1, all display-agnostic.
- The gesture recogniser and `_TapCycleState`
  (`docs/contracts/gesture-envelope.md`), modulo re-calibration.
- The host test suite.
- `docs/design-principles.md` #1 (ambient not demanding), #2 (lean into the
  physical medium — arguably *more* true here), #6–#10 (architecture).
