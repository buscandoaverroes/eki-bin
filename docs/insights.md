# Insights & Field Notes

_Running log of **why** decisions were made and **what we learned** — especially
from physical testing. Distinct from `dev-status.md` (what's done / next) and from
the contracts (how it works now). Park half-formed ideas here before they harden
into code._

---

## 1. Time-to-leave, not departure time

The jar answers **"when must I leave?"**, not "when does the train depart?" We
subtract `WALK_TO_STATION_MINS` once, in Stage 1, so every downstream stage
reasons in *minutes until you must move*.

Consequences:
- Trains you can no longer catch are **hidden** (not shown greyed-out).
- A train "in 2 min" with a 2.5-min walk shows **nothing** — correct; you've
  already missed it.
- The single knob (`WALK_TO_STATION_MINS`) is where "this commute" lives; later
  it can come from the NFC station card instead of config.

See `docs/contracts/display-contract.md`.

---

## 2. The abstraction philosophy

`time → LeaveSignal (abstract) → DisplayContract (render) → LEDs`. "What's the
urgency?" is decoupled from "how do we show it?"

Why it keeps paying off:
- Swap the entire visual language by changing one config line.
- Test the time logic on a host with no LEDs (we do).
- New **inputs** (NFC, magnetometer) slot into Stage 1; new **outputs**
  (ring, e-ink, different jar) slot into Stage 2 — neither disturbs the other.

Two extensions this is pulling us toward (not yet built):
- **Below** the contracts: a hardware abstraction layer (the only code touching
  `np[i]` today is `_paint` / `clear` — that's already the seam).
- **Above** `_paint`: reusable animation primitives (blink / pulse / breathe /
  colour helpers) that contracts compose, instead of each contract re-deriving
  wave math.

---

## 3. Jar physics & colour UX — field notes (2026-06-28)

**Setup:** Pico on breadboard, ~10 cm M–F jumpers running into the jar, 8-LED
stick (headers + stick don't fit inside, hence the jumper extension).

**Enclosure comparison:**

| Jar | Result |
|---|---|
| Clear glass vase | **Bad.** No translucency, no colour mixing → you just see wires + bare LEDs. Ruins the ambiance entirely. |
| Medium (light-blue ribbed, translucent) | Same problem, milder — internals still too visible. |
| **Thick brown** | **Best so far.** Colours distinguishable; usable. → the V1 reference enclosure. |

**Headline takeaway:** translucency and glass physics are a **feature to lean
into, not a constraint to tolerate**. The "reveal" only works when the technology
is hidden by the medium.

**Brown-jar specifics:**
- Less diffusion than expected — across the room you can still **count N LEDs**
  individually (good for multi-LED arcs; less "soft glow" than hoped).
- Adjacent lit LEDs make **red vs. orange ambiguous** — without a reference,
  hard to tell which urgency colour is showing.
- Some colours read **natural**, others **artificial**: amber (LEVEL_2) sits
  beautifully with translucent brown; red (LEVEL_1) looks like "an LED in a jar."
  A real UX signal, not just taste.
- Colour fidelity needs a **higher baseline brightness** than the bench `0.15`.
  May end up leaning on **brightness / pulsing** more than hue in thick jars.

**Implications:**
- Palettes should be tuned **per enclosure** (`COLOR_SCHEME` already supports this).
- Through diffusion, **arc length** is a more reliable signal than hue — but brown
  diffuses little, so counting works too.
- Strip **orientation** matters physically: hung downward into the jar, the LEDs
  end up upside-down. Fine for testing, not for a real unit → motivates a
  logical LED-direction abstraction (see §4).

---

## 4. Parked ideas (not yet decided)

- **LED direction / origin abstraction + HAL.** Add a *logical* arc origin
  ("which end is LED-0 of the arc") independent of physical wiring, so the same
  firmware works upside-down, on a ring, or on a different stick. The `_paint` /
  `clear` pair is the natural HAL boundary. Lighter first step: a single
  `reverse`/origin flag mapping logical→physical index. Fuller step: a
  `led_drivers/` module per hardware. _Recommend doing the full HAL when the ring
  hardware actually exists, so it's validated against a real 2nd device._
- **Reusable animation primitives.** `blink`, `slow_blink`, `sine_pulse`,
  `breathe`, colour-lerp — local building blocks shared by contracts.
- **Sub-minute urgency.** "< 30 s to leave → blink/breathe." Needs finer timing
  than the 30 s loop and minute-resolution schedule currently provide.
- ~~**Two-train modality.**~~ **Done (v1.3)**: `N_TRAINS` config +
  `_paint_layers` render further-out departures as a dimmer nested band beyond
  the primary's arc, realising concept.md's "two arcs." Directly motivated by a
  live UX pain point ("I won't make this one, what's the one after?"), not just
  the wasted-pixels observation below it originally was. See
  `docs/contracts/display-contract.md` § Multiple trains.
- **Power-budget-aware brightness cap.** Field finding (§6-adjacent, logged in
  `docs/hardware.md` 2026-07-13): at 120 LEDs, `BRIGHTNESS=1.0` froze the Qi path
  and tripped MacBook USB overcurrent; `0.15` is the safe ceiling. Total draw
  scales with `NUM_LEDS`, but `BRIGHTNESS` is a flat per-device knob today — so a
  bigger strip is a silent footgun. Idea: derive an *effective* brightness ceiling
  from a configured current budget and `NUM_LEDS` (roughly `budget_mA /
  (NUM_LEDS * mA_per_led_at_full)`), clamping `BRIGHTNESS` down automatically. Also
  note the *practical* draw is far below worst-case — ambient contracts rarely
  light all N at full white — so a budget based on realistic frames, not all-white,
  is the useful version. Empirical constants (mA/LED, safe budget per power source)
  needed before implementing; don't guess them.
- **Bottle-colour "bin filter" presets.** The brown gift-jar bottle noticeably
  shifts perceived LED colour (white → soft orange-white, forest green →
  yellow-green, dim gray → yellow — see `docs/hardware.md`'s 2026-07-23
  bring-up log). 2–3 pre-shift colour presets ("bins") could compensate for
  (or lean into) a given bottle's cast. Not built — parked until colour
  fidelity through glass matters again, e.g. a different/less-tinted bottle.
- **Multiple eki-bins as a shelf display.** Floated during Qi bring-up
  (2026-07-25): several jars, each independently configured for a different
  favourite line/station, sitting dark and decorative on a shelf — placing
  *one* on the Qi pad both powers it and selects it as "the line I'm
  watching today," and removing it from the pad is a more natural "off"
  gesture than a switch or unplug. Directly validates the wake/sleep design
  in `docs/contracts/wake-interaction.md` as a real interaction model, not
  just a power-saving trick — not something to build now, no code implication
  beyond what that doc already covers, just a product-vision note worth
  keeping.

---

## 5. V1 UX notes — living with it ~36 h (2026-06-29)

**Framing: the UX *is* the product; the primitives are plumbing.** This is a
clock that sits in a room 24/7 — every small detail compounds. The current focus
on building blocks is necessary but secondary to how the thing *feels* in the room.

### Trust is the killer feature
- The 2.5-min offset nailed it: left home with **1 LED lit**, walked at a normal
  pace, made the train with **~45 s to spare.** That repeatable accuracy is the
  whole game.
- A clock you know runs 3 min fast is worse than no clock; a thermometer that's
  off gets ignored. **Accuracy → trust → use.** This outranks every other feature.
  _(→ promote to design-principles.)_

### Make it a clock, not a timer
- **Analog vs digital feel.** A digital clock is explicit, ubiquitous, faintly
  authoritative, faintly soulless. An analog clock is implicit at a glance, has
  character, is innocent. The central question: **how do we get an analog-clock
  UX out of digital components?** _(→ promote to design-principles.)_
- **Clock vs countdown timer.** A timer manufactures urgency / anxiety /
  suspense. We don't want that — there's almost always another train in a few
  minutes (except the last). Right now the shrinking arc reads as a *timer*; we
  want it to read as a *clock*. _(→ promote to design-principles.)_
- The **two-train modality** now has a UX justification beyond "use spare LEDs":
  showing the *next* departure alongside the current one **softens the timer
  feeling** — it says "and there's another coming," which is calming.

### Break the line — spatial character
- LEDs-in-a-line reads mechanical/digital. Arrangement could add the "character /
  innocence" of an analog object:
  - **"Galaxy":** mount LEDs in **random physical positions** on the round PCB
    (keep the *logical* order fixed underneath, so rendering is unchanged). Use
    **more LEDs than strictly needed** for richer patterns, and pick a **random
    arrangement on each reset** → an intentional non-order.
  - **3D / "nest":** LEDs on a flexible substrate for a non-planar cluster.
  - Note: this lives entirely behind the `_physical()` / driver seam — logical
    arc position → arbitrary physical placement is exactly what that seam is for.

### Ambient brightness & when to be lit
- Too bright **even in the brown bottle**.
- We already have Unix time → modulate brightness by **sunrise/sunset**.
- Later: **IMU "shake to adjust brightness"** if glare is the main complaint.
  **Grown into a full design (2026-07-25)**, motivated by real Qi bring-up
  findings (thermal cutoff on long runs; "off 80% of the time" as the actual
  desired aesthetic, not a compromise) — see
  `docs/contracts/wake-interaction.md`: a bounded wake window per tap/boot,
  single vs. double tap doing different things, and the boot ceremony's
  burst reused as a "waking up" cue rather than rebuilt.
- Be prudent about *when* it glows at all: if **no train within "N-LED" reach**,
  go dark — no reason to shine at 3 a.m. This is smarter than fixed quiet hours
  (the schedule itself defines the on/off envelope).

### Startup / "boot ceremony" vs the clock paradigm
- Could the LEDs double as a quiet **debug indicator** — e.g. a `breathe` while
  connecting WiFi, a distinct cue on NTP success, then "clock on"?
- **Open tension:** a boot animation may **break the clock illusion**. A real
  clock doesn't perform a startup sequence — it just *is*. Is it OK to hold the
  paradigm "in suspense" during connection, or should boot be invisible/instant?
  Park this; it's a genuine design fork, not just an implementation detail.
- **Resolved toward "yes, have a ceremony" (2026-07-23):** a concrete v1.4
  boot-sequence design was proposed — power-on indicator → WiFi/NTP "loading
  circle" spin → success burst → crossfade into the live contract, with a
  persistent all-red breathe on failure. Framed as answering the open tension
  above, not sidestepping it: the ceremony is bounded (power-on → clock-on),
  never recurs during normal operation, and a real clock *does* have an
  analogous moment (setting it after a power cut) — it's the "always visible
  countdown timer" framing that would've broken the clock illusion, not a
  one-time boot cue. See `dev-status.md` § V1.4 for the implementation status.

### Form factor / hardware size
- Pico 2W was the right call for dev ergonomics. But it **won't fit most bottle
  tops**, and the headers add width for pins we barely use.
- Consider small **I²C / Qwiic / STEMMA**-class boards for size down the road.
- Near-term: Pico on **long jumpers**, only the lights inside the bottle — fine
  for the next few versions.

> **Candidates to promote to `design-principles.md`:** trust/accuracy as the
> top principle; "analog soul from digital parts"; "a clock, not a timer."

---

## 6. Brightness can't differentiate a second train (v1.3 field test)

Built `N_TRAINS`/`_paint_layers` to show a further-out train as a *dimmer* band
beyond the primary's arc (§4's parked "two-train modality," realised). Swept
`BACKGROUND_BRIGHTNESS` on real hardware (bare stick, both `SandTimerContract`
and `BreathingContract`): `0.35` → visible flicker + individual LED die visible
("nerdy lights in a bottle," not ambient glow); `0.5` → still not clean; `0.75`
→ flicker gone but now barely distinguishable from the primary. **No brightness
value in between looks right.**

**Why, mechanically — two compounding physics problems, not a tuning gap:**
- **Dithering needs headroom to look smooth.** At `mult≈0.35`, a channel value
  is only ~2–3 discrete 8-bit codes. Dithering toggles between neighbouring
  codes to hit the average, but a 2→3 step is a 50% *relative* jump — visible as
  flicker rather than a blend. Dithering only reads as smooth when many codes
  are available so each step is a small fraction of the whole; there's a hard
  floor below which no amount of dithering fixes it.
- **Diffusion needs a lumen budget.** Below some brightness, an LED stops
  scattering enough light through the material to read as ambient wash — you
  see the point source (the die) instead of a soft glow. Confirms/extends §3's
  finding that thick jars need a *higher* brightness floor: this is the floor's
  *lower* edge.
- **Confirms it's brightness, not motion, that's broken**: static
  `SandTimerContract` looks just as bad as animated `BreathingContract` at low
  `BACKGROUND_BRIGHTNESS` — rules out "disable breathing for N>1" as a fix.

**Resolved.** Built `led_sandbox.py` (see below) specifically to A/B compare
directions on real hardware fast, without a full config/reflash cycle per
attempt. Winning combination, found empirically: primary train **static, full
brightness**; every train beyond it **hue-shifted** (`hue_rotate`, ~20°/index)
**and gently breathing**, but with a deliberately *high* floor (~0.7) so it
never dips into the flicker zone — colour + subtle motion, brightness staying
high throughout. Two-tone alone (no motion) also read fine; adding the gentle
breath was judged "the best balance of readability, no 'emergency' feeling,
and fun."

Shipped as **`EchoContract`** (`CONTRACT = "echo"`) — new config knobs
`SECONDARY_HUE_SHIFT_DEG` / `SECONDARY_BREATHE_PERIOD_MS` /
`SECONDARY_BREATHE_FLOOR`, kept separate from `BreathingContract`'s own
`BREATHE_*` knobs so tuning one doesn't fight the other. See
`docs/contracts/display-contract.md` § Per-layer treatments.

One correction to the reasoning above: a genuinely new contract *was* the
right call here, not a modifier — the primary and the background layers need
**different render logic** (static-vs-animated, same-colour-vs-shifted), which
`_layer_mult` alone (a single number applied uniformly per layer) can't
express. What still holds from the original reasoning: it composes existing
primitives (`_arc_len`, `breathe`, `hue_rotate`) rather than duplicating them —
the new contract is ~20 lines because everything it needs already existed.

**Also built**: `micropython/led_sandbox.py` — `import main`s the real
primitives (so whatever looks good there renders with the exact math a real
contract would use) and lets you paint arbitrary LED ranges with independent
colour/animation for quick side-by-side comparison, without WiFi/schedule/the
full loop. General-purpose now, not just for this one decision.

---

## 7. iOS's generic NDEF API breaks on Type-5 tags (NFC bench, 2026-07)

The whole "give it to a friend, no app" plan hinged on iOS Shortcuts writing the
ST25DV tag. It doesn't work — and the *reason* is a reusable trap worth keeping:

- **The tag is fine.** Raw ISO-15693 block read/write (CC file, NDEF TLV, a full
  hand-encoded NDEF Text record) all verified byte-perfect over RF. Not a hardware
  or encoding problem.
- **The generic high-level API is the problem.** Apple's `NFCNDEFReaderSession` —
  which backs iOS Shortcuts, ST's "NFC Tap" NDEF tab, and third-party rewriter
  apps — times out / fails to detect NDEF specifically on **ISO-15693 / NFC-Forum
  Type-5** tags. Documented multi-year iOS pattern. The low-level
  `NFCTagReaderSession` + `NFCISO15693Tag` path works every time.
- **Lesson:** "does NFC work?" is the wrong question — *which API layer* is
  everything. Most consumer NFC tooling targets Type-2 (NTAG-style) tags; Type-5
  is a different world, and the convenient high-level tools silently don't cover
  it. Also: Shortcuts has **no NDEF content read/write action at all** (only a
  UID-keyed trigger), so it was never a real writer regardless.
- **Consequence:** a minimal first-party app became unavoidable — not a failure of
  the no-app principle, just the reality of this tag class on iOS. Decision +
  tag data contract: `docs/nfc-provisioning.md`.

---

## 8. Tap-gesture tuning: hardware-informed limits, not assumed ones (2026-08-04)

**Setup:** built `micropython/vibration_sandbox.py` (batch data collection —
position × tap-count reps, streamed to flash as JSON Lines) and
`scripts/analyze_taps.py` (peak magnitude / ring-down / hysteresis-based tap
counting on the host) to answer "what tap gestures can this hardware actually
support" empirically, instead of assuming `docs/contracts/wake-interaction.md`'s
original single-vs-double-tap design would just work. This sandbox is what
will inform that contract's still-stubbed `_imu_tap_detected()`.

Muji glass jar, blue-tack mount, 240Hz sampling, 60 clean reps (10 per
position×tap-count combo, controlled technique — pad only, bottle secured
without a bracing hand):

| Signal | Result |
|---|---|
| Position (neck vs. body), best single threshold | **98.3%** (~390mg cutoff) |
| 1-tap | **100%** |
| 2-tap | 70% overall — **80% at neck, 60% at body** |
| 3-tap | 40% overall — 50% at neck, 30% at body |

**Headline takeaway:** position (neck vs. body) is a far more reliable signal
than tap-count beyond one tap. The original design leans on the *weaker* of
the two axes (single vs. double tap). "Single tap at neck" vs. "single tap at
body" would likely be both simpler to implement (no timing-based counting)
and more reliable (98%+ vs. 70%) than double-tap. Not yet decided whether to
redesign around this — see open questions below.

**Why 2-/3-tap degrade:** looks like an algorithm limit so far, not a hard
sensor one. The hysteresis-based peak counter can't split two strikes that
happen close enough together that the signal never drops back below
threshold between them. Ring-down itself is fast (4-10ms), and successful
2-tap reps cluster at 232-327ms spacing — so real taps spaced like that
should be resolvable in principle. Not yet confirmed whether faster failures
are a fixable detection gap or a human motor-control floor.

**Methodology notes** (matter for reading the numbers above):
- Absolute peak magnitudes are ~3-5x larger at 240Hz than an earlier 60Hz
  pass on the *same* bottle — finer sampling catches a fast transient's true
  peak that 60Hz was under-sampling. **Thresholds are ODR-dependent — don't
  mix data collected at different sample rates.**
- Tap technique (nail vs. pad, whether a hand braced the bottle) measurably
  moves position separability — an uncontrolled-technique run on this same
  jar showed neck/body ranges overlapping; only the controlled-technique run
  above hit 98.3%.

**Open questions (mid-investigation — testing a wine bottle next):**
- **How much generalizes across bottles?** Glass mass/thickness/geometry
  plausibly shifts the *absolute* mg thresholds per bottle (this jar's
  ~390mg cutoff probably won't transfer). The *relative* pattern (neck >
  body — less material near the neck to absorb the shock) might generalize
  even if the absolute numbers don't. A second, physically different bottle
  is the first real data point on this either way.
- **Where does calibration happen?** If thresholds are bottle-specific,
  something has to set them per unit: **(a) dev-time** — the maker runs this
  same sandbox once per physical jar, bakes the result into that unit's
  `config.py` (fits the existing ~19-knob config philosophy, zero runtime
  complexity); **(b) runtime** — the device self-calibrates from a few taps
  on first boot (robust to bottle swaps/drift, but needs a real on-device
  calibration UX with no laptop in the loop). Leaning toward (a) for V1.5
  given the scale (a handful of gift units, not a product line) — (b) reads
  more like a V2/Rust-era feature, and would be a natural use for the
  LSM6DSV16X's onboard MLC/FSM (deliberately unused so far — see
  `docs/hardware.md`).
- **Would ML "solve" the heterogeneity?** Skeptical on principle: a model
  trained on raw absolute features inherits the same bottle-specificity
  hardcoded thresholds have — it has no more physics knowledge than the data
  it's given. The more promising lever is *feature engineering* (e.g.
  normalizing peak magnitude against a same-session reference tap, so it's a
  ratio rather than a raw mg value), independent of whether the final
  classifier is a threshold or a trained model. Whether a normalized feature
  actually generalizes across bottles is itself an empirical question the
  multi-bottle testing will answer — not something to assume either way.

**Update (2026-08-04, later same day) — the classifier earns its keep once
the features are right.** Rebuilt the matrix based on the findings above:
dropped 3-tap (consistently the worst result everywhere), kept neck (best
position separator despite being the worst tap-count position), added
**shoulder** (the neck/body transition — angled tap vector, hypothesized to
excite less rocking) and **base** (grounded contact point, same reasoning).
Built `scripts/prepare_tap_dataset.py` (raw signal → engineered-feature CSV:
energy, duration, spacing regularity, etc. — deliberately *not* reusing
`detected_taps`, since training on that would just teach a model to imitate
the hysteresis algorithm's mistakes) and `scripts/train_tap_classifier.py`
(cross-validated comparison against the hand-tuned baselines).

Chianti bottle, 240 clean reps (60 per position, 120 per tap-count), 5-fold CV:

| Question | Hand-tuned baseline | Trained classifier (random forest) |
|---|---|---|
| Tap count (1 vs. 2) | ~55% (hysteresis peak-counter) | **91-92%** |
| Position (4-way: neck/shoulder/body/base) | ~73-100% pairwise, weakest at neck-vs-shoulder | **85%** (single 4-way model) |

Tap-count result is the headline: the classifier didn't just edge out the
threshold approach, it solved a problem the threshold genuinely can't —
distinguishing "one tap plus rocking echo" from "two real taps" needs
*multiple* signal properties considered together (spacing regularity, total
energy, crossing count), which a single hysteresis threshold has no way to
combine. Feature importances confirm this isn't black-box magic: the top
features are exactly the physics-motivated ones (`spacing_mean_ms`,
`spacing_stdev_ms`, `energy`) designed specifically around the rocking
discovery above — **the feature engineering did the real work; the
classifier's contribution was combining several such features into one
decision, which a threshold structurally cannot do.** This refines rather
than contradicts the earlier "ML isn't a shortcut" take: on muji (clean,
non-rocking, single dominant feature) the simple threshold still *beat* the
classifier (98.3% vs. 95-97%) — the classifier only earns its complexity
when the underlying signal genuinely needs more than one feature to explain,
which rocking-prone bottles apparently do and calm ones don't.

Position-by-tap-count breakdown, same session — extends the original "is
1-tap reliable" question with data the earlier 2-position matrix didn't
have:

| | 1-tap | 2-tap |
|---|---|---|
| base | **100%** | 73% |
| shoulder | 83% | 60% |
| body | 47% | 33% |
| neck | 23% | 23% |

Clean physical ordering (base > shoulder > body > neck) matching distance
from the grounded contact point. Base and shoulder clear the 80-90%
reliability bar for 1-tap; neck and body don't, and 2-tap doesn't clear it
anywhere (though base at 73% narrows the gap a lot). Note: **neck is the
best-*separated* position but the worst for tap-count *reliability*** — the
two properties don't track together, so "pick the most distinctive-looking
position" isn't the same question as "pick a position where tap detection
actually works."

**Cross-bottle generalization test — added `--train-bottle`/`--test-bottle`
to `train_tap_classifier.py` (train on one bottle entirely, test on another
entirely, no pooling/shuffling across — stricter than k-fold on pooled data,
which can leak bottle identity across folds).** Trained on chianti-3 (240
reps), tested on muji's original session, restricted to the positions/tap-
counts both bottles actually share (neck/body, 1-2 taps); confirmed first
that both sessions ran at the same effective sample rate (~215Hz) so this
isn't just the earlier ODR-mismatch problem resurfacing:

| Target | Cross-bottle accuracy (train chianti-3 → test muji) |
|---|---|
| Position (neck/body) | **0%** — worse than random guessing |
| Tap count (1 vs. 2) | **85%** (random forest) |

This is a real, decisive answer to the "universal vs. per-bottle" question,
not just a hint, and it splits cleanly along feature *type*, not target
difficulty: **position relies on amplitude features (peak magnitude,
energy), which are bound to a specific bottle's glass mass/geometry — a
boundary learned on chianti's scale is meaningless on muji's (muji's
absolute magnitudes run 3-5x higher at the same position, entirely
different range). Tap-count relies mostly on timing features (spacing
regularity) — how fast a human physically taps twice doesn't depend on the
bottle's physical response, so it survives the bottle swap.** Practical
read: amplitude-based classification (position) needs per-bottle
calibration, no way around it; timing-based classification (tap-count) may
not, or may need much less. Worth testing directly once a matching
shoulder/base muji session exists — this test so far only covers the two
positions/tap-counts the two bottles happened to already share.

**Follow-up (same day) — a dedicated shoulder+base, 1-tap-only, n=80/side
session landed, and it complicates the shoulder/base pairing specifically,
while strongly confirming tap-count reliability:**

- **Tap presence: 157/160 = 98.1%.** Rock solid at scale — the base/shoulder
  choice for reliable single-tap detection holds up completely.
- **Shoulder-vs-base separability dropped from 96.7% (chianti-3, n=60/side)
  to 71.2% (chianti-4, n=80/side) on the same bottle.** Checked whether this
  was small-sample luck or real drift by comparing the two sessions' raw
  numbers directly: shoulder mean 265mg→193mg, base mean 65mg→115mg — the
  ordering held (shoulder > base, both sessions) but the *gap* narrowed
  substantially. That's genuine session-to-session variability in the
  physical measurement, not a sampling artifact — matches the pattern
  already seen with the neck/body 3-tap flip between the two earlier
  chianti sessions (§8 above). **Pooling both sessions gives ~81.4%**,
  probably the more honest current estimate than either session alone.
- Tried normalizing each capture's peak magnitude against that session's own
  median before pooling, hoping to cancel out the drift — **didn't help**
  (still 81.4%). Should have seen that coming: a per-session linear rescale
  doesn't change a distribution's *relative* overlap, so it can't move a
  best-threshold split. The drift isn't a simple scale/offset the two
  sessions disagree on — more likely genuine variability in exact tap
  location/technique within "shoulder" and "base" as target zones, which
  normalization can't fix.
- **Practical implication:** shoulder-vs-base, at ~81% pooled, is currently
  a weaker position pair than neck-vs-body (100%), neck-vs-base (93%),
  shoulder-vs-body (100%), or body-vs-base (91%) — though those are each
  still only a single session's read, and this same finding says single-
  session reads can't be trusted at face value. **Open question, not yet
  answered:** whether those other pairs hold up as well as shoulder/base
  didn't once tested across multiple independent sessions the same way.

---

## 9. Tap/gesture envelope — final synthesis (2026-08-04)

§8 above is the full field log — a sandbox toolchain
(`micropython/vibration_sandbox.py`, `imu_test.py`, `handling_test.py`,
`orientation_test.py`, plus host-side `scripts/analyze_taps.py` /
`prepare_tap_dataset.py` / `train_tap_classifier.py`) built and run across
~15 sessions and two physically different bottles (muji jar, chianti wine
bottle) to answer "what can this hardware actually support" empirically
instead of assuming the original wake-interaction.md design would just
work. This section is the decision-ready summary. The design built on it
lives in **`docs/contracts/gesture-envelope.md`**.

**The winners:**

| Modality | Reliability | Recognizer | Hardware dependency |
|---|---|---|---|
| Flip/orientation (upright/horizontal/upside-down) | Visually unambiguous, steady-state | Hardcoded: dominant axis + sign | Wired power only — Qi breaks on flip |
| Tap presence @ base | 98% (167/170) | Hardcoded: peak-magnitude threshold | none |
| Tap presence @ shoulder | 95% (161/170) | Hardcoded: peak-magnitude threshold | none |
| Flick vs. soft tap | 91-94% | Hardcoded: peak-magnitude threshold | none |
| Flick vs. hard handling | 100% via `spacing_stdev_ms` (magnitude alone caps ~80%) | Hardcoded threshold, but on a *shape* feature, not magnitude | none |
| Position: shoulder vs. base | ~81.5% pooled across 3 sessions (71-97% range per session) | Hardcoded ≈ trained classifier — no ML benefit found | optional/toggle, per-bottle calibrated |

**What didn't pan out — kept here so it isn't silently re-attempted:**
- Tap presence @ neck (23%) and @ body (51%), un-held — ruled out.
- 2-tap and 3-tap counting — never cleared a usable reliability bar at any
  position on either bottle; replaced by gesture-*type* (tap/flick) instead
  of tap-*count* as the second signal dimension.
- `grab_and_tap` — an n=10 pilot showed 51%→90% reliability at body,
  genuinely exciting; **did not replicate at n=30 across all 4 positions**
  (neck improved 23%→63% but still weak; shoulder, body, and base all got
  *worse*; position-discrimination *within* grab_and_tap collapsed further
  than free-tap's). A trained classifier didn't rescue it either (75% vs.
  free-tap's 85% for position). Root cause unconfirmed — likely the same
  session-to-session technique drift seen elsewhere, not a settled physical
  effect. Parked, not built on, until the inconsistency is understood.
  One piece *did* generalize: separating a deliberate held-tap from
  accidental handling via `energy` scored 90-98% regardless of position —
  reusable as a general noise-rejection technique even though the specific
  gesture didn't pan out.

**The recurring methodology lesson, worth stating once, plainly, since it
showed up at least four separate times in §8:** a small sample (n=10) in
this investigation *consistently* looked better than it turned out to be
at scale — shoulder-vs-base separability alone swung 96.7% (n=60) → 71.2%
(n=80) → 81.7% (n=60) across three independent sessions on the same
bottle, and `grab_and_tap`'s exciting n=10 pilot reversed at n=30. **Treat
anything validated at n<30 or in a single session as a hypothesis, not a
result** — this cost real rework more than once here, and the fix each
time was the same: collect more, pool across sessions, and only trust
numbers that hold up when re-checked.

---

## 10. ACK/CONFIRM LED jolt — real-hardware iteration (2026-08-16)

§9's fuller gesture vocabulary (position, flick-vs-tap, etc.) didn't get
built on directly — real-hardware testing the day after §9 was written
found that every one of its harder problems was *additional*
discrimination on top of tap-vs-noise, which was never actually
unreliable (95-98%+). Scoped down instead to a minimal "light switch"
contract: tap wakes, tap cycles, timeout sleeps. Full design + rationale:
`docs/contracts/gesture-envelope.md` §11 ("Scope pivot"). This section is
the field-note synthesis of what came after that pivot — designing and
tuning the LED response to that contract, across five real-hardware
rounds in one day, once `main.py`'s recognizer + state machine were
already validated on their own.

**The core UX finding — brightness has to bridge the gap, not just mark
the endpoints:** the two-phase design (instant ACK the moment a tap is
felt, ~1.2s later a CONFIRM once the recognizer has a verdict) is
necessary — that gap is however long the recognizer actually takes to
decide, not a rendering choice, and no capture window shorter than that
stays accurate (§11's own latency/accuracy table: ~94-98% at 1200ms down
to ~70% at 50ms). But the *naive* rendering of that gap — ACK flashes,
drops to black, CONFIRM flashes later — read as two disconnected blips
with a stall in between, not one continuous gesture. Fix: ACK settles
onto a dim-but-non-zero "continental shelf," held for the rest of the
gap, that CONFIRM then rises *from* instead of from black. The shelf is
doing real communicative work ("still here, deciding") that a hard cut to
off can't.

**"Hardware-defined software" as a genuine UX win, not just a slogan:**
tap strength (`dev`, the triggering sample's deviation from baseline —
the only signal available before `energy` is known) scales both the ACK
peak *and* the shelf level, so a harder tap reads brighter on both the
"up" and the "down." Took real tuning to land, though — the brightness
range needed widening **three separate times** as testing moved from a
bare LED strip to inside the actual frosted jar: 0.5-1.0x (2x spread,
imperceptible) → 0.4-1.6x (4x, worked bare) → 0.35-2.2x (in-bottle, the
frosted glass compresses contrast a bare strip never showed) → pulled
back to 0.35-6.0x after a saturation bug was found (see below). **The
in-bottle jump is the one to remember**: a diffuser you haven't tested
through yet will always make a bare-strip-tuned range look flatter than
it is — 駅瓶's whole premise is the frosted glass, so bare-strip numbers
were never more than a rough starting point.

**Two real rendering bugs, both traced to the same root cause — gamma
correction misapplied to a low-brightness or held value:**
- A brightness ceiling that looked fine in isolated tests (`10.0x`)
  turned out to **clamp every hard tap to identical pure white** past
  roughly 65% strength — losing exactly the differentiation the whole
  feature exists for. Not obvious from watching single taps one at a
  time; only showed up comparing two different hard taps side by side.
  Fixed, then **hardened with a pytest regression test**
  (`tests/test_gesture_sandbox.py`) checked against the actual
  historical bad value — the saturation point is a pure property of the
  brightness constants + `BRIGHTNESS`/`STARTUP_COLOR`, fully verifiable
  without hardware, unlike whether real taps' `dev` values *cluster* in
  practice (that's empirical, stays a documented on-hardware thing to
  watch, not something a unit test can know).
- The ACK's descent (rendered through the normal gamma+dither path)
  visibly dove to near-black *before* reaching the shelf's own
  (deliberately linear, un-gamma'd) brightness, then jumped back up once
  the static shelf write took over — "dive underground to 0, then back
  up to a plateau." Root cause: `gamma(mult)` for `mult` below roughly
  0.3 is *much* smaller than `mult` itself, and the ACK's whole range
  sat mostly in that zone. Fixed by rendering the whole ACK shape without
  gamma correction — the same fix already used for the shelf itself
  (`MARKER_BRIGHTNESS`'s precedent, approach-contract.md), just extended
  to cover the animated approach to that value, not only the held value.
  **General lesson for this codebase, worth stating past this one
  feature:** gamma correction is for genuinely wide, actively-perceived
  brightness swings — apply it reflexively to a value that's mostly
  *low* or *about to be held static*, and it actively works against you
  instead of smoothing anything.

**A real hardware-fragility finding, not a firmware bug:** `OSError EIO`
from the IMU read, twice, both correlated with physical handling (moving
the bottle, a fumbled tap) — the same "connection shaken loose by
tapping" `vibration_sandbox.py` diagnosed first (§8). An initial read
that it correlated with *light* taps specifically didn't hold up on more
data — another small-sample-mislead instance, see above. `gesture_sandbox.py`
now catches it, skips the one bad sample, and only escalates to a visible
LED cue (a new, distinct persistent-breathe colour) if a read hasn't
succeeded in over a second — a deliberate consequence of
`led-status-messages.md`'s "errors are persistent and unambiguous, not
almost-normal" principle: a brief flash for a single dropped sample would
have worked against that, not honored it.

---

## 11. ESP32-C3 WiFi memory: two heaps, and only one of them counts (2026-08-17)

Bringing the gesture dev unit up on the XIAO hit `OSError: Wifi Out of
Memory` from `connect_wifi()`. Worth writing up because **two plausible
diagnoses were wrong before the real one**, and the debugging method
(measure the right pool) generalises well past this bug.

### What it wasn't

- **Not credentials.** `WIFI_SSID = config.WIFI_SSID` is direct attribute
  access, so a missing value raises `AttributeError` at import — nowhere
  near WiFi.
- **Not (only) `mpremote run`.** `make run` ships the whole ~115KB source
  over stdin to be held in RAM *and* compiled there; the traceback said
  `File "<stdin>"`. Running from flash instead (`make upload` + soft reset)
  was a genuine improvement and is now the documented path for a file this
  size — but it did **not** fix the error. Right practice, wrong root cause.
- **Not MicroPython heap exhaustion.** The obvious check says the opposite:

  ```
  gc.mem_free() → 155,824      GC total 175,872, used 37,632
  ```

  `main.py` — all 2355 lines — is **37KB of live data in a 172KB heap**.
  There is no bloat problem in the sense you'd assume.

### What it is

**There are two separate heaps, and `gc.mem_free()` measures the wrong
one.** MicroPython's GC heap holds Python objects. ESP-IDF's `malloc` heap
is entirely separate, and `esp_wifi_init()` allocates from *that*. The two
compete for the same physical SRAM, and on the ESP32 port MicroPython's GC
heap **grows on demand by splitting chunks off the IDF heap and never
returns them**.

The right instrument is `esp32.idf_heap_info(esp32.HEAP_DATA)`, which
returns one `(total, free, largest_free, min_free)` tuple **per region** —
ESP-IDF manages SRAM as several disjoint ranges, not one pool, and a given
`malloc` must be satisfied within a single region.

Measured on a bare boot, bringing WiFi up by hand:

| Region | free before | free after | WiFi took |
|---|---|---|---|
| 1 | 5,664 | 5,664 | 0 |
| 2 | 10,160 | 4 | **10,156** |
| 3 | 115,624 | 111,568 | 4,056 |
| 4 | 26,448 | 32 | **26,416** |
| | | **total** | **40,628** |

**The distribution matters more than the total.** WiFi drained regions 2
and 4 to 4 and 32 bytes while leaving 111KB untouched in region 3. That
isn't the allocator being lazy — those buffers need DMA-capable internal
SRAM, which region 3 doesn't provide. **Region 3's 111KB is essentially
useless to WiFi.** Only regions 2 and 4 count.

Which produces the number worth remembering: at a bare boot region 4 has
26,448 bytes free and WiFi wants 26,416. **Thirty-two bytes of margin.**
WiFi on this chip was always at the edge; compiling a `main.py` that had
roughly doubled in size grew the GC heap ~5.5KB into region 4 and pushed it
over. The IMU code didn't break it so much as consume the last slack.

### How the allocator picks regions, and how much we can steer it

`heap_caps_malloc(size, caps)` walks the registered heaps in a fixed
priority order from the SoC's memory-layout table and takes the first that
both satisfies the capability mask and has a large enough free block. It is
**deterministic** for a given firmware and allocation sequence — but the
sequence is exactly what changes between runs, which is why order matters
so much here.

From MicroPython, direct control is **not available**: you cannot request
capabilities, and WiFi's allocations are internal to ESP-IDF. What is
controllable:

- **Ordering** — allocate the big, capability-constrained thing (WiFi)
  before the flexible things (Python objects). Implemented; see below.
- **Total pressure** — anything that stops the GC heap growing.
- **Build-time `CONFIG_ESP32_WIFI_*`** — RX/TX buffer counts, static vs.
  dynamic. This is the only real lever on WiFi's 40KB appetite, and it
  needs a custom firmware build.

### Fixed now (the cheap half)

`main()` brings WiFi up **before** `load_schedule()`. The 8KB JSON parses
into a much larger object graph that was previously held across WiFi init,
costing ~5.5KB of precisely the contested region. Reordering lets
MicroPython grow into what's left rather than the reverse.

This buys margin. **It does not create headroom** — a fix that works by
reclaiming 5KB against a 32-byte baseline margin is one feature away from
breaking again.

### The real fix, deliberately deferred

Compiling a 115KB module on-device is a transient allocation spike that
permanently enlarges the GC heap. Removing that spike is the durable
answer, in rough order of effort:

1. **Precompile to `.mpy`** (`mpy-cross`), with a two-line `main.py` that
   imports it. No firmware build required.
2. **Freeze into firmware** — bytecode lives in flash, not RAM. Biggest
   win, needs a custom MicroPython build.
3. **Split `main.py`** into modules so no single compile is huge. Helps
   partly; the combined bytecode still lands in RAM.
4. **Trim docstrings in hot modules.** Worth knowing: *comments are
   stripped at compile time, docstrings are not* — they become live string
   objects. This codebase's deliberately long docstrings therefore have a
   real RAM cost, which is a genuine tension with its documentation ethos.
   A marginal lever, listed for completeness rather than recommended.

Deferred on purpose: `feature/gesture-envelope` is about getting gestures
working on the XIAO, and the reorder unblocks that. Also worth noting the
project's own roadmap retires this problem — V2 drops WiFi for a DS3231
RTC, and gesture work needs no network at all (`GESTURE_DEBUG_ENABLED`
already runs WiFi-free).

---

## 12. Low-PWM colour collapse, and colour in a real bottle (2026-08-18)

First full in-bottle run of the assembled unit (XIAO C3 + IMU + 21-LED strip,
approach contract, line-cycling on tap). Two findings, one a bug and one a
constraint.

### The bug: `(1,1,1)` is not gray

Marker ticks were rendering **yellow**, not the dim neutral they're specified
as. The arithmetic:

```
BRIGHTNESS 0.15 × MARKER_BRIGHTNESS 0.15 = 0.0225
MARKER_COLOR (80,80,80) × 0.0225 → (1, 1, 1)
```

**One PWM step out of 255 per channel.** At that level WS2812B channel
matching collapses — the R/G/B dies have different efficiencies and different
minimum-drive behaviour, so equal values stop meaning neutral. Red and green
dominate blue at the very bottom, and `(1,1,1)` reads warm yellow-green.

**This was already in `docs/hardware.md`** as a brown-glass observation
("Dim neutral gray → Yellow"). It was mis-attributed: the glass wasn't the
cause, low PWM was. The glass merely made it easier to notice.

**Generalised rule, worth applying anywhere a dim neutral is used:** below
roughly 4-5/255 per channel, *hue is not controllable on this hardware*. It
isn't a dithering artifact (it persisted with `DITHER = False`) and it isn't a
dead pixel (`led-test` showed a uniform strip). Plan brightness so any colour
that must read as a specific hue lands above that floor, or accept that it
will skew warm.

**Debugging note worth more than the bug.** Three plausible theories were
wrong before the right one: urgency-driven colour (ruled out — the approach
contract never reads `urgency`), the anchor washing an adjacent dot (ruled
out — the anchor is nowhere near the affected LEDs), and a defective LED
(ruled out by `led-test`). What actually settled it was a single observation
— *every* LED on one arm was affected, not one — which immediately excluded
anything per-pixel. **The reasoning was slower than the measurement, again.**

### The constraint: tinted glass compresses the palette, as predicted

Confirmed directly, and it's the thing §11's line-colour design most depends
on: through the opaque brown bottle, **only near-opposite hues are reliably
distinguishable** — blue vs. yellow/red. Adjacent hues collapse, exactly as
§3 predicted from the red-vs-orange finding.

Implications for the line palette:
- **Cap the practical line count at what the glass supports**, not at what
  the data model allows. Three widely-separated hues is plausible; six is not.
- **Brightness needs to go up in the bottle** — the bench-tuned `0.15` is too
  dim once diffused, consistent with `hardware.md`'s earlier note that brown
  glass allows `BRIGHTNESS` toward `0.5`. That also lifts markers out of the
  low-PWM danger zone above, so the two findings share one fix.
- Clear glass would sidestep this entirely — the argument
  `glass-stone-concept.md` §3 already makes.

### Incidental, useful

- **The opaque brown bottle hides the electronics well** — the "reveal" the
  concept doc wants, confirmed on the real assembly rather than in theory.
- **An IMU simply resting inside the bottle, unfastened, detects taps fine**
  for testing, and stays removable. Rigid mounting can wait for the
  permanent build; it is not a prerequisite for gesture iteration.

---

## 13. A corrupt filesystem can make a board look physically dead (2026-08-23)

Cost most of a morning. The symptom was as severe as hardware failure gets:
`mpremote`, `screen` and Thonny all failed to open a session, macOS showed
**no `/dev/cu.usbmodem*`, no node in the USB tree, and no BOOTSEL device**,
and the onboard LED sat dim instead of bright. Two cables and two ports
behaved identically. Everything pointed at a damaged board.

The board was fine. So were both cables and both ports.

### The chain

1. An LED strip on the 5V pin loaded the rail hard enough to brown out the
   MCU **during a file write** (`mpremote cp`). That first event is a
   separate, genuine power fault — see the LED-strip note below.
2. The brownout left the **littlefs filesystem corrupt**, mid-write.
3. On the next boot MicroPython hung in `_boot.py` **mounting** that
   filesystem — which happens *before* USB CDC is brought up. No enumeration
   ever occurred, so the host saw nothing at all.
4. **Reflashing the firmware did not fix it.** Firmware and filesystem live
   in separate flash regions and `picotool load` only writes the former, so
   the corrupt filesystem survived every reflash intact.
5. `picotool erase -a` followed by a reflash fixed it immediately.

### Why this is worth writing down

The failure impersonates dead hardware almost perfectly, and the two obvious
recovery moves both fail in ways that *reinforce* the wrong diagnosis:
reflashing appears to succeed and changes nothing, and swapping cables and
ports changes nothing either. Each innocent result pushes you further toward
"the board is damaged."

**The discriminating test is BOOTSEL.** It runs from mask ROM and cannot be
affected by anything in flash. So:

| BOOTSEL enumerates? | Meaning |
|---|---|
| **No** | Genuinely physical — cable, port, connector, or board |
| **Yes**, but MicroPython doesn't | Flash contents. The hardware is fine. |

The second row was the case here, and it inverts the conclusion completely.
Note the ordering trap: BOOTSEL working feels like reassurance, so it's
tempting to read it as "board is fine, must be something else" and keep
chasing physical causes. It is not reassurance — **it is the positive result
that rules the physical layer out.**

### What changed

`make flash-micropython BOARD=... WIPE=1` now erases all of flash before
loading (`scripts/flash_firmware.sh`). Opt-in, because it also destroys the
on-board `config.py`. Reach for it the moment a board is unreachable over
serial *and* BOOTSEL works — that combination is this bug until proven
otherwise, and a plain reflash will never clear it.

Also: `make upload` now writes `main.py` **last**. It's the boot script, so
once on the device it auto-runs and competes with `mpremote` for the serial
link — a separate failure (`could not complete raw paste: b'\x01'`) that
truncated `config.py` and muddied this diagnosis considerably.

### The underlying power fault — ✅ RESOLVED, and it was a config typo

The trigger recurred: an 8-LED WS2812B strip on the XIAO's 5V pin **stopped
the board enumerating and blocked BOOTSEL entirely**, twice. Disconnecting
it restored both immediately.

Eight LEDs should not be able to do that — `hardware.md` records 120 running
fine off USB at `BRIGHTNESS = 0.15`. **The resolution is that `BRIGHTNESS`
was never reaching them.** `config.py` had `LED_PIN = 3` while the strip was
wired to GPIO1, so nothing ever addressed it — and an unaddressed WS2812B
holds whatever state it powered up in, which here was near full white.
Eight at full white is ≈480mA off VBUS. `hardware.md`'s 120-LED figure
doesn't contradict this because that measurement had data arriving.

Confirmed on the bench 2026-08-23: the strip lit blazing the instant it was
connected with nothing driving it, then ran a full `make led-test` cycle —
`fill WHITE` included — with no brownout at all once addressed at 15%.

### ⚠ A wrong `LED_PIN` is a POWER fault, not a display bug

This is the part worth carrying forward, because the failure is wildly
disproportionate to its cause and nothing in the symptom points at config:

```
one wrong digit in LED_PIN
  → strip never addressed
  → holds power-up state (potentially full white, ~480mA)
  → board browns out
  → brownout lands during an mpremote write
  → littlefs corrupted
  → MicroPython hangs in _boot.py before USB CDC
  → board presents as DEAD HARDWARE, survives every reflash
```

A one-character config error consumed a morning and looked like a destroyed
board at every step. **`BRIGHTNESS` cannot protect you here** — it is a
property of data you are not sending. The strip's idle draw is set by
whatever it powered up holding, and it will happily sit there at maximum.

Practical rules:

- **Verify `LED_PIN` against `pinouts/<board>.md` before connecting a strip**,
  not after. `make led-test` (which carries its own `DATA_PIN`) is the cheap
  confirmation that the wiring works, independent of `config.py`.
- **Bring a strip up under `mpremote run`, never during `make upload`.**
  `make led-test` / `make run-file` execute from RAM and touch no files, so
  a brownout costs you a reset. The same brownout during a write costs you
  the filesystem.
- **A strip lighting up before any code runs is a warning**, not a nice sign
  that the wiring works.

### A second presentation: enumerates, but never answers (2026-08-23)

The same corruption recurred with a **different symptom**, worth knowing so
it isn't mistaken for something else:

| | first occurrence | second |
|---|---|---|
| `/dev/cu.usbmodem*` | absent | **present** |
| BOOTSEL | worked | worked |
| `mpremote exec` | "no device found" | **opens, then 15s of silence** |

So a device node existing does **not** mean the board is reachable. The RP2
runtime brings USB CDC up before `_boot.py` runs, so a filesystem too
damaged to mount leaves you with an enumerated port and no Python behind it.

There's a trap in how this surfaces. `make screen` interrupted with Ctrl-C
produces a traceback ending in `self.serial.open()` → `os.open(...)`, which
reads exactly like a busy port held by another process. It isn't — that is
just where mpremote was waiting. Check before believing it:

```bash
lsof /dev/cu.usbmodem*        # who holds it (usually: nobody)
ls -la /dev/cu.usbmodem*      # does the node exist at all
```

**The discriminating test is a timed probe**, not a REPL attempt:

```bash
.venv/bin/mpremote exec "print('alive')"   # under a ~15s timeout
```

Node present + no answer = this bug. Recover with `WIPE=1`.

### A third presentation: the file reads back as the FILESYSTEM (2026-08-24)

The worst one, because every check passes. `diag.py` uploaded, verified at
the correct 4,011 bytes, and then failed to compile:

```
File "diag.py", line 1
SyntaxError: invalid syntax
```

Line 1 is a comment. Reading the file on the device showed why:

```python
>>> print(repr(open('diag.py','rb').read()[:90]))
b'\x03\x00\x00\x00\xf0\x0f\xff\xf7littlefs/\xe0\x00\x10\x01...\x11config.py...'
```

That is **littlefs's own superblock** — its magic string, then directory
entries for other files. The inode's size was right; its data pointers were
aimed at the filesystem's internal structures instead of the file's content.

What makes this the nastiest variant so far:

| | mount | size check | reads back |
|---|---|---|---|
| §13 original | ✗ fails, board looks dead | — | — |
| second presentation | ✗ hangs before USB CDC | — | — |
| **this one** | **✓ fine** | **✓ correct** | **✗ wrong data** |

Nothing announces a problem. The board boots, the filesystem mounts, the
upload verifies, and the failure surfaces as a *syntax error in your own
source* — pointing at a code bug that does not exist.

**Rule: when a reported error cannot be true of the source you wrote, stop
debugging the source.** A SyntaxError on a line that is a comment — a
comment byte-identical in style to ones in every module that loaded fine
moments earlier — is not a language problem. The file being read is not the
file you wrote.

**This is why upload verification now hashes CONTENT, not size**
(`scripts/upload.sh`). A size check passes here and actively misdirects: it
prints `✓ verified` over a file that is entirely wrong. A check that passes
for the wrong reason is worse than no check.

**Recovery is a wipe, not a re-upload.** Do not trust a filesystem that
returns its own superblock as file content — rewriting into a damaged
structure is a coin flip:

```
make flash-micropython BOARD=xiao-rp2350 WIPE=1
make upload
```

⚠ **Three corruption events in one day is not normal**, and they share a
suspect: this board is on a breadboard, and breadboard contacts are already
the leading explanation for the intermittent transfer failures below. Flash
writes are the operation least tolerant of a power glitch. If it recurs
after a wipe, treat it as evidence for soldering the unit rather than as
bad luck.

### ROOT CAUSE FOUND: the filesystem is bigger than the flash (2026-08-24)

**`make doctor` on a bare XIAO RP2350 reports a 3072 KB filesystem. The chip
has 2048 KB of flash, ~320 KB of which is the MicroPython image.** The
filesystem is 1.78× larger than the space that physically exists.

This is a **known, filed, fixed defect**, not a quirk of one unit:

- **raspberrypi/pico-sdk#2834** — the XIAO RP2350 board header declares
  `PICO_FLASH_SIZE_BYTES` as 4MB; the board ships a 2MB (16-Mbit) part.
  Confirmed against `picotool info -a` (`flash size: 2048K`), the P25Q16H
  datasheet, and Seeed's own documentation. The report notes it propagates
  to anything relying on that constant — MicroPython included.
- **micropython/micropython#18839** — the downstream issue, reproducing the
  identical numbers: 768 blocks, 3072 KB total, 3064 KB free.
- **Fixed** in pico-sdk 2.3.0, plus a MicroPython follow-up trimming the
  filesystem to 1408k to match SEEED_XIAO_RP2040. Both land **after** the
  v1.28.0 (2026-04-06) build this project was running.

That a brand-new second board failed identically is exactly what a wrong
compile-time constant predicts: it is wrong for every unit of this board.

**Why this likely explains the corruption, not just the wrong number.** The
failures land at 87–145 KB, far below any boundary, so "ran off the end of
the chip" does not fit on its own. The stronger hypothesis is the
filesystem's *start offset*: partition layout typically computes it as
`flash_size − fs_size`, so a phantom 4MB figure can map the filesystem at
the wrong physical address entirely — corrupting from early writes, at
unpredictable points. That matches the most damning symptom exactly: a
file's data pointer resolving to littlefs's own superblock is a **block
address miscalculation**, not the half-written-page damage a power glitch
produces.

**Not yet confirmed.** The test is to flash a build with the corrected flash
size and see whether corruption disappears independent of write count.
`make doctor` now fails the board outright when the filesystem exceeds the
physical flash, so this can never again be mistaken for bad luck.

Also fixed as a direct consequence: `scripts/flash_firmware.sh` used to glob
the firmware directory and take the **first** match, which sorts to the
OLDEST build — it would have silently reflashed v1.28.0 over a preview
installed specifically to test this fix. It now takes the newest, says so
when there is a choice, and accepts `FIRMWARE=<path>` to pin one.

### The variable is the NUMBER OF WRITES, not size or tool (2026-08-24)

Narrowed by two experiments that finally isolated it.

**`make doctor` on a freshly wiped board passes everything** — 4KB, 24KB and
40KB written locally by the device, then the same three transferred from the
host via `mpremote cp`, all content-verified. Six write operations, no
failures. So flash, littlefs and the serial transport are each fine in
isolation, at sizes larger than any real module.

**Thonny hangs too.** Uploading the firmware by hand through Thonny — a
different tool with its own transfer implementation over the same USB CDC —
wrote clock, config, contracts, diag, gestures, leds, main and net, then
hung on the ninth file.

| | board | tool | outcome |
|---|---|---|---|
| `make doctor` | original | mpremote | ✓ 6 writes, all pass |
| Thonny | original | Thonny | ✗ hung on the 9th (~145 KB in) |
| `make upload` | **brand new, out of the box** | mpremote | ✗ died on the 6th (~87 KB in) |

**A second, unused board fails the same way**, which settles it: the first
board is not damaged, and today's three corruptions were symptom rather than
cause. Two boards, two host tools, two cables, two USB ports, on and off the
breadboard — the only surviving variable is the platform itself
(MicroPython 1.28.0 on RP2350, its littlefs, and USB CDC).

Note it is not a fixed file count OR a fixed byte count — 6 files/87 KB on
one board, 9 files/145 KB on the other. Both land in the same band, which is
what a block-reclamation pause would look like rather than a hard limit.

So it is **not mpremote**, and **not the board**. What is left is the
accumulation of flash writes within one session.

The leading explanation is littlefs garbage collection: after enough writes
it must compact and erase blocks, and on RP2 a long flash operation is
exactly the thing that starves USB CDC. Not confirmed.

**This reframes the V1.6 split's cost.** Going from 3 files to 13 did not
make transfers *slower*, it pushed them past a threshold that had always
been there — which is why occasional failures became reliable ones on the
same day the module count quadrupled.

Two things follow, one of which is a genuine fix:

- **`make dev` avoids the problem entirely.** `mpremote mount` serves
  `micropython/` over the serial link as the device filesystem, so the
  firmware runs from the working copy with **zero flash writes**. For
  iteration this is strictly better; a real standalone unit still needs
  `make upload`.
- **`make upload` now skips files whose content already matches**, so a
  typical run writes one or two modules rather than thirteen — staying
  under the threshold by doing less work.

### Upload failures: free space ruled out, overwrite is the suspect

The intermittent `make upload` failures outlived every physical fix — new
cable, new port, off the breadboard entirely. Two things narrowed it:

**Free space is not the cause.** `os.statvfs('/')` on the XIAO RP2350
returned `(4096, 4096, 768, 716, 716, ...)` — 716 of 768 4KB blocks free,
**93% empty**, both before and after a full upload. (Net-zero because the
files already existed and were replaced.)

**The pattern was: works immediately after a WIPE, fails on later uploads.**
That points at littlefs having to erase and garbage-collect blocks in order
to *overwrite* an existing file — flash erase on RP2350 blocks for tens of
ms at a time, and a long enough stall breaks mpremote's raw-paste timeout.

`scripts/upload.sh` now does `mpremote rm` before each `cp`. The first
upload after that change succeeded **on the breadboard, without a wipe**,
which had been failing consistently. That is **n=1 against an intermittent
fault** — suggestive, not proven. If failures return, the next measurement
is whether a tiny file succeeds while `main.py` fails; that would confirm
write duration as the variable.

Independent of the stalling, `rm`-then-`cp` is worth keeping for a
different reason: a failed overwrite can leave a truncated blend of old and
new content, whereas a failed write after removal leaves the file **absent**
— which fails loudly at import instead of running as subtly-wrong code.

**File size is now the strongest signal.** On the upload that triggered the
second corruption, every smaller file went through and only the big one
failed:

| file | bytes | result |
|---|---|---|
| `diag.py` | 4,011 | ✓ |
| `primitives.py` | 9,353 | ✓ |
| `config.py` | 16,806 | ✓ |
| `settings.py` | 23,415 | ✓ |
| `testbench.json` | 28,582 | ✓ |
| **`main.py`** | **122,011** | **✗ ×3** |

That fits a roughly constant per-unit-time failure probability, where
exposure scales with transfer duration — and it explains why `config.py`
failed *sometimes* earlier rather than never. It predicts that **uploads get
more reliable as V1.6 shrinks `main.py`**, which is a claim this project can
confirm by construction rather than argument.

Two consequences worth acting on:

- **Each failed retry is another chance to corrupt the filesystem.**
  `upload.sh` tries three times, so a doomed large write gets three
  attempts to damage littlefs. Both corruptions to date followed a failed
  large write.
- **A `.mpy` shortcut exists if this stays painful.** `mpy-cross` compiles
  to bytecode a fraction of the source size, with a tiny `main.py` shim to
  import it. Not done — V1.6 shrinks the file anyway, and one mechanism is
  better than two.

### Rule of thumb

Brownouts don't only interrupt the write in progress — they can leave
persistent state that outlives the power event, the reflash, and every
cable you try next. When a board goes unreachable during a write, suspect
the filesystem before the silicon.
