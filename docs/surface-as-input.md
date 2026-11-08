# Surface-as-input — research memo

_Opened 2026-08-16. **Parallel research thread, explicitly not eki-ishi v1
scope** — filed the same way `docs/roadmap.md` files the clock paradigm and
the battery-standalone variant: a real question worth a cheap bench test
someday, not a dependency for anything being built now._

**Depends on:** `docs/glass-stone-concept.md`.

---

## 1. The idea

If the eki-ishi form factor is adopted, the object the user touches is a solid
hand-blown glass pebble — irregular, textured, roughly softball-sized. The
question: **can that surface itself become the input layer?** Not a button
hidden nearby, not a gesture in the air above it — the object's own
craftsmanship and texture *being* the interface. Swipes, drags, a wheel-spin
around its circumference like an old click-wheel MP3 player.

This is the most aesthetically correct interaction this project has
considered. It is also, with accessible parts, mostly not achievable — but the
"mostly" hides one genuinely useful salvage (§5).

---

## 2. Why touchscreen technology does not transfer

Modern touch surfaces are one of two things, and neither survives an 8cm solid
irregular mass.

**Projected capacitive (PCAP)** — what phones and trackpads use. A fine grid of
electrodes sits directly under a thin cover glass; a finger's body capacitance
perturbs the coupling between electrode pairs (**mutual capacitance**), giving
fine position and multi-touch. Sensitivity falls off steeply with overlay
thickness. Phone cover glass is ~0.5–1mm. Mutual-cap degrades hard past a few
millimetres, and the electrodes would be nowhere near the touch point on a
rounded mass many centimetres thick.

**Surface acoustic wave (SAW)** — older kiosk touchscreens. Ultrasonic waves
are launched across a flat glass sheet by edge transducers; a touch absorbs
energy and the position is derived from the timing of the disruption. Requires
a flat, acoustically predictable, uniform sheet. **The internal bubbles and
waves that make this stone beautiful are exactly what would scatter and absorb
the acoustic signal unpredictably** — the same physical property working for
us optically and against us acoustically.

So the literal ambition — the whole rounded surface as an X-Y trackpad — is out.

---

## 3. IR gesture sensing — evaluated and ruled out

**The approach:** an IR gesture chip such as the **APDS-9960** (cheap,
off-the-shelf, purpose-built for swipe up/down/left/right) mounted in the
stand, facing up through the base of the stone. Four IR photodiodes read the
relative pattern of reflected light as a hand crosses them; direction comes
from the left-right / up-down asymmetry in when each quadrant sees the
reflection. Since the stone is *clear* rather than frosted, an unobstructed
optical path was plausible.

**The proposed fix for the stone's scattering, and why it doesn't work.** The
idea raised in discussion: measure the stone's static refraction at startup,
zero it out, and read deltas from there. The instinct is sound and it is
standard practice — every capacitive touch chip auto-baselines at power-on and
drift-compensates continuously.

But it does not rescue this case, and the reason is worth keeping: **baseline
subtraction removes a constant offset; scattering is not an offset problem, it
is an information-destruction problem.** The APDS-9960 infers direction from
*which quadrant sees what, when*. Internal bubbles and waves randomise the
direction of returning light, so all four quadrants see a smeared version of
the same thing. Subtracting a well-measured baseline cannot restore a
directional mapping that has been scrambled — you would get a clean,
well-calibrated "something moved" and no reliable "which way."

Two further objections, both raised in the same discussion and both correct:

- **It breaks the premise.** A sensing zone 1–5cm *above* the stone means the
  interaction is a hand-wave near an object, not a touch of it. The whole point
  was for the surface to be the input.
- **False triggers.** A hand passing overhead while reaching for something else
  on the shelf would read as input.

**Verdict: ruled out.** Not merely deprioritised — the failure is structural,
not a tuning problem.

---

## 4. Capacitive sensing through thick glass — precedent exists

The question asked directly: is there precedent for capacitive sensing through
substantially thick glass? **Yes, several** — and one technical distinction
reframes what is and isn't possible.

### Precedents

| Precedent | Overlay | Notes |
|---|---|---|
| **Induction cooktop controls** | ~4mm ceramic glass | Utterly ubiquitous, decades of field proof |
| **Shop-window touch foils** | 10–30mm+ | The strongest thick-glass case: a PCAP foil laminated inside a storefront window senses touch on the *outside* of the full pane |
| **Industrial capacitive proximity sensors** | Through glass/plastic tank walls | Used for liquid level sensing at centimetre ranges |
| **Touch lamps, appliance/fan touch buttons** | 1–5mm plastic typically | The cheap `TTP223`-class sensors already familiar from consumer goods |

### The distinction that matters: self-cap vs. mutual-cap

- **Mutual capacitance** measures coupling between a TX/RX electrode pair.
  Gives fine position and multi-touch. **Degrades fast with overlay thickness.**
  This is what phones use, and why "phone touchscreen through 8cm" fails.
- **Self capacitance (load mode)** measures a single electrode's capacitance to
  ground and asks only "did a finger add to it." Much stronger signal, **far
  more overlay tolerance**, but weak on position and multi-touch.

Sensing range roughly scales with electrode size — a large plate can project a
field several centimetres. Mildly in our favour: **glass has a dielectric
constant around 5–7 versus air's 1**, so a solid glass path couples better than
the same thickness of air.

### Why the precedents still don't give us a wheel

All of them share a geometry the stone does not: **a flat sheet of uniform
thickness, with the electrode parallel to and close to the far surface.** Our
case is an irregular ~8cm mass with the electrode at the base and the finger at
the summit.

**The honest reframing: at that thickness you lose *position*, not
*detection*.** Spatial resolution collapses long before raw detection does.

### And the click-wheel is ergonomically wrong anyway

A ring of 6–12 self-cap electrodes around the stone's base footprint would, in
principle, let a finger tracing the base perimeter activate them in sequence —
genuine click-wheel mechanics, inferred from activation order and timing. But,
as raised in discussion: **a finger tracing the base of a stone at ground level
is an unnatural motion**, and the stand itself (a suiseki daiza cradles the
stone's contour; a koro holds it aloft) would physically obstruct the very ring
the sensor needs. The technology is the lesser problem here; the ergonomics
kill it independently.

---

## 5. What survives — and it is worth pulling forward

A **single self-capacitance electrode under the stone**, giving a binary
*"the stone is being touched right now."* No position. No gesture. Just
contact state.

This is cheap (a few dollars — an MPR121, AT42QT1010, or similar), falsifiable
in one bench afternoon, and it delivers something the IMU structurally cannot.
**Accelerometers see impulses, not sustained contact.**

| Event | IMU alone (today) | IMU + contact electrode |
|---|---|---|
| Deliberate tap | impulse | brief contact **+** impulse |
| Drag / swipe | ambiguous vibration | sustained contact **+** sustained micro-vibration |
| Mug set down nearby | impulse — indistinguishable in principle | vibration with **no contact at all** → trivially rejected |

That last row is likely the real prize. Rejecting handling noise is the problem
`docs/insights.md` §8–9 spent roughly fifteen sessions and two bottles on,
reaching 98.4% with accelerometer feature engineering alone. A second,
**physically independent** modality is not more of the same signal — it is
information no amount of accelerometer feature engineering can synthesise.

**This is also the condition under which this project's own ML finding predicts
a classifier should do well.** `docs/insights.md` §8 was specific: the trained
classifier earned its complexity exactly when the signal needed *multiple
features combined* (tap-count 55% → 91–92%), and **lost** to a plain threshold
when a single feature already sufficed (muji *position*, neck vs. body: 98.3%
threshold vs. 95–97% classifier). Two independent modalities, on a rigid mount that removes
the session-to-session drift which sabotaged all the position work, is exactly
that first case.

Standard caveats from §8–9 still apply and are not optional: expect a
**per-unit trained model**, treat anything validated at n<30 or in a single
session as a hypothesis, and expect amplitude thresholds not to transfer
between objects.

---

## 6. Recommendation

| Idea | Verdict |
|---|---|
| Whole surface as X-Y trackpad | **Out.** Structural, not a tuning problem (§2) |
| IR gesture (APDS-9960) | **Out.** Scattering destroys directional information; also breaks the touch-the-object premise (§3) |
| Capacitive click-wheel at the base | **Tabled.** Technically marginal, ergonomically obstructed (§4) |
| **Single contact-state electrode** | **Pull forward.** Cheap, falsifiable, improves the gesture work already built (§5) |

The first three stay parked here. The fourth belongs with the IMU work in
`docs/contracts/gesture-envelope.md` — it makes an existing, extensively
validated feature better rather than depending on anything new.

---

## 7. Open questions

1. Does a single electrode under ~8cm of glass actually register a finger on
   top? (Bench test, cheap, do it early.)
2. Does the stone's contact area with the stand affect the reading — i.e. does
   the electrode need to be at the contact point, or can it be near it?
3. Does a contact-state signal measurably improve handling-noise rejection over
   the current 98.4% accelerometer-only baseline, or is the remaining 1.6% not
   the kind of error a contact signal catches?
4. Does contact state make tap-vs-swipe tractable where accelerometer features
   alone were not? (Pairs with the unused **gyro** axes —
   `glass-stone-concept.md` §5.)

---

## 8. The bottle is not the stone — the geometry ruling was geometry-specific (2026-09-04)

Everything above evaluates the **glass stone** (`glass-stone-concept.md`): a
solid puck on a stand, where the only free surface is the base and the hand
covers the top. Proposed since, for the **bottle**: slide a finger up and
down the side for brightness, and distinguish shoulder taps from base taps.

The bottle changes two of the assumptions the ruling rested on:

- **§4's click-wheel was tabled partly on ergonomics** — the base is where the
  object sits, so the electrode is under the contact patch and the finger has
  to reach beneath. A bottle's side is the *most* accessible surface it has.
  That objection does not carry over.
- **§2's "no X-Y position" still holds, but a slide doesn't need X-Y.** It
  needs *one* axis, coarsely. Three or four electrodes stacked vertically
  give an ordered sequence of contact events — which is direction, without
  ever resolving position. This is closer to §5's surviving contact-state
  idea (repeated N times) than to the trackpad that was structurally ruled
  out.

So the bottle version is **not** a re-litigation of §6's verdict; it's a
different problem that the verdict didn't cover. It is still gated on §7
question 1 — *does one electrode read a finger through this glass at all* —
which is the same cheap bench test, and answering it for bottle glass
(thinner, curved) is a prerequisite either way.

**Shoulder vs. base taps are already partly answered, and not by capacitance.**
`docs/insights.md` §8 measured tap *position* on the muji bottle with the IMU
alone: neck vs. body separated at **98.3% with a plain threshold**, beating a
trained classifier. What did not survive was cross-session stability — the
thresholds drifted between mountings. That is the actual open problem for
position-by-tap, and a contact electrode does not obviously fix it.
