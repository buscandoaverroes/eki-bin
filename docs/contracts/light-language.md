# The light language — struck glass

**Status: design, nothing implemented.** Written 2026-09-04 out of the 24-hour
field session on the v1.6 production unit (`docs/insights.md` §14). This doc
names the general pattern; `docs/contracts/led-status-messages.md`'s catalog
of errors and acknowledgments is a **subset of it**, not a rival — the same
relationship that doc has to the boot ceremony it found already existing.
Nothing here supersedes it. When the two disagree, that's a bug in this doc.

---

## 1. The premise: the bottle already answers

A glass bottle responds to a tap. It rings, and the ring decays. That is a
real, universal, pre-digital affordance that every person who will ever hold
one of these already knows.

So the LEDs are **not a new interaction.** They are an augmentation of one
that exists. This is the whole design constraint, and it resolves the
question that prompted the doc — *do we want digital-world references in a
hardware-defined project?* — without having to answer it in the abstract:

> **Every light response is the physics of struck glass.**
> Impulse in → energy propagates → energy decays.
> A resonance, not a notification. A struck bell doesn't blink.

Everything below is that one physics under different boundary conditions.

## 2. Why motion, and not more colour

From `insights.md` §14. Four expressive channels exist; three are spent:

| Channel | Currently carries | Free? |
|---|---|---|
| Position | time-to-leave — the entire paradigm | no |
| Hue | line identity + urgency — and §12 measured that **thick brown glass allows only 2–3 hues at all** | no |
| Brightness | urgency, anchor, marker, and now day/night | no |
| **Motion** | boot burst, CHASE, breathe — used, never systematised | **yes** |

Motion also survives the enclosure best. Thick glass blurs *position* and
filters *hue*; change-over-time passes through diffusion intact. The colour
measurements in §12 don't merely permit this conclusion, they force it.

**Corollary worth stating:** a ring of LEDs inside a bottle is an
under-tapped resource. Almost everything built so far treats the strip as a
*line* that happens to be bent. The circumference is a dimension nothing
currently uses.

## 3. The five words

| Word | Physics | Means | Exists today? |
|---|---|---|---|
| **inward** | energy converging | a train approaching — the core paradigm | yes, `ApproachContract` |
| **outward** | energy radiating from the strike point | *"I felt that"* — the ACK | yes, boot burst is this shape |
| **around** | energy travelling the circumference, decelerating to rest | a transition completing | partly, CHASE |
| **shake** | energy reflecting off a boundary, going nowhere | *"no"* — the action isn't available | no |
| **breathe** | energy sustained, not decaying | something unresolved — an error persisting | yes, failure breathe |

Four of five already exist in the code. This mostly names them.

### inward
Unchanged. What trains always do: both arms converge on the anchor, because
distance from the anchor *is* time (`approach-contract.md`).

### outward
**Radiates from the station** — the anchor, not the strip's centre and not
`STATUS_LED_INDEX`. The strike point is the thing the object is about.

Two quantities should scale with the tap, because that is what glass does:

- **brightness** ∝ strike force (`dev_mg`, already measured and already
  passed into `_handle_tap`)
- **outward propagation speed** ∝ strike force

A harder tap rings brighter *and* faster. This makes "proportional ACK" a
consequence of the metaphor rather than a feature bolted onto it.

### around
The transition verb. See §5 — this is the one with the skeuomorphism trap.

### shake
The "no". Motion that fails to complete is a better negative than a colour,
because it needs no vocabulary learned in advance — it is the universal
gesture for refusal, and it works the first time someone sees it.

**Implementation is deliberately small:** bounce between the two LEDs
closest to the label boundary. Two constants, or one `[a, b]` pair, tuned
once per unit at provisioning and never touched again.

```
SHAKE_BOUNDS = (a, b)   # physical LED indices flanking the label edge
```

This is the same kind of per-unit physical fact as `ARC_ORIGIN` and the
arm A/B orientation — established with the bottle in hand, recorded in the
unit's registry entry (`dev-status.md` § Gift registry), not derivable from
code. It joins the provisioning routine at the same step.

### breathe
Full ring. **TBD** — kept as the error/unresolved verb it already is, but
its non-error uses are open. Note the tension: breathe is the one word whose
energy *doesn't* decay, which is exactly why it reads as unresolved. Don't
spend it on anything that should feel finished.

## 4. The restructure: the acknowledgment IS the transition

Today the sequence is three events:

```
ACK flash  →  ~1.2s capture gap  →  CONFIRM jolt  →  repaint
```

`insights.md` §10 spent a real session fighting the symptom that produces —
*"two disconnected blips with a stall between"* — patched by holding a
brightness shelf across the gap.

The new shape is two events:

```
ACK (outward, ∝ force)  →  ~1.2s capture gap  →  [motion] that IS the new display arriving
```

**ACK stays a flash.** Its job is the tactile "click" of the button — it
must fire immediately, before anything is classified, and it must feel like
a consequence of the strike.

**CONFIRM stops being a flash.** It becomes whatever motion the resolved
action calls for, and that motion *delivers the new state* rather than
announcing that new state is coming:

| Tap resolves to | Response |
|---|---|
| wake from asleep | outward → transition into the first train display |
| cycle to another line | **around** → arriving at the new line's display |
| cycle, but only one line exists | **shake** |
| woke, but nothing to show | (see `led-status-messages.md`'s no-data ack) |

Motion carries continuity across the capture gap in a way a held brightness
cannot, so this is plausibly a better fix than the shelf was.

**⚠ The 1.2 s capture window is not negotiable.** Truncating it was tried
with data (`gesture-envelope.md`): 300 ms → 83.9%, 150 ms → 80.6%. The gap
exists regardless of how it's dressed. ACK's only job is to make it feel
intentional instead of broken.

**⚠ The current code has the defect this fixes.** `_handle_tap` plays CONFIRM
*before* `main.py` checks `len(lines) > 1`, so a single-line unit says
"yes, done" and changes nothing. A confident acknowledgment of a no-op is
worse than silence. The fix belongs inside `_handle_tap`, which must know
whether the action is available before choosing its response.

## 5. The skeuomorphism rule: deceleration, not rotation

The worry is real — a spin can read as a loading spinner, which is a
digital-world reference this project has no reason to import. But the tell
is not that it rotates:

| | Loading spinner | Physical rotation |
|---|---|---|
| Angular velocity | **constant** | **decelerating** |
| Duration | indefinite | definite, ends somewhere specific |
| Feels like | a machine waiting | a roulette wheel, a combination lock, a coin settling |

Same shape, opposite connotation, and the entire difference is easing plus a
definite end.

> **Rule: no unbounded constant-velocity motion.** Rotation is allowed;
> spinners are not.

This is directly testable and should be the sandbox's first A/B: the same
`around` motion run linear, then eased-to-rest. If the rule is right, one
reads as a machine thinking and the other as an object moving.

## 6. Tilt — the native continuous input

Sliding a finger up and down the bottle is the smartphone paradigm wearing a
bottle. **Tilt is not.** Tilting a bottle is what bottles are *for*, the IMU
already provides the gravity vector, and it needs no new hardware.

Proposed interaction (as designed in conversation):

1. **Pick up** → engages an adjustment mode (brightness first)
2. **First tilt in any direction** defines the axis on the fly, and always
   means *up*
3. **Tilting back the opposite way along that same axis** means *down*

Zero calibration, works regardless of how the unit was assembled or which
way the label faces.

**The consequence to test: you must go up before you can go down.** In a
dark room, "brighten before you can dim" is a glare flash — the exact
failure the day/night work exists to prevent. It is probably a brief
overshoot rather than a sustained one, but **this is the thing to test in
the dark**, not on a bench at noon.

**The alternative, if it does bite: the label is the bottle's front.** A
bottle is radially symmetric and has no intrinsic front — except the label,
which the `shake` word is already about to turn into a config value. One
more provisioning constant gives absolute tilt directions and removes the
go-up-first rule entirely. Recommended only if the sandbox says the
on-the-fly version is annoying; it costs a calibration step the simple
version doesn't need.

## 7. What has to be sandboxed before any of this is committed

None of this is decidable on paper — the feel of light in a specific bottle
is the whole question. `micropython/led_sandbox.py` already exists for
exactly this (A/B animation comparison, jolt-shape prototyping on real
hardware), so this extends it rather than starting something new.

1. **`around`, linear vs. eased.** Tests §5's rule directly.
2. **All five words, back to back,** in the actual bottle — are they
   distinguishable through this glass, or does diffusion collapse them?
3. **ACK force-proportionality** — is the difference between a light and a
   hard tap legible, or does the glass flatten it?
4. **The ACK → gap → motion sequence** as one continuous thing, against
   today's ACK → shelf → CONFIRM.
5. **Tilt, in the dark** — specifically the go-up-first overshoot.

## 8. Open

- `breathe`'s non-error vocabulary (§3).
- Whether `around` should travel the *shorter* way to its destination, or
  always the same way. Shorter is more physical; always-the-same is more
  legible as a signal. Untested.
- Whether the five words survive a vessel change, or are per-enclosure the
  way brightness and hue turned out to be (`insights.md` §14, §12).
