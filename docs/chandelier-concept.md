# The chandelier — a display with no orientation

**Status: proposal. Nothing built, nothing scheduled.** Written 2026-09-14.

Three threads that were recorded separately turn out to be the same idea:

- `insights.md` §5's parked **"Galaxy" / "3D nest"** — LEDs at random
  physical positions, logical order preserved behind the `_physical()` seam.
- `hardware.md` § **Filament array** — five filaments plus PWM cross-fade
  giving twenty-plus *perceived* positions, gated on one forward-voltage
  measurement.
- `design-principles.md` #6, arrived at only yesterday (§20): **the object
  has no front; don't pretend otherwise.**

The third is what makes the first two urgent rather than decorative.

---

## 1. The thesis, taken to its conclusion

A bottle is radially symmetric. §20 established that imposing a front on it
is at best an honest declaration (the anchor) and at worst a performance of
a symmetry it does not have (a left-to-right sweep).

**But the strip itself still has ends.** Every renderer written so far maps
time onto a *line* — an arc with an origin and a far end, with `ARC_ORIGIN`
and the arm A/B question existing purely to reconcile that line with an
object that has no matching axis. Four combinations, none derivable from
the object, a whole doc section on which face you are viewing from.

The culmination of the no-front thesis is therefore not a better mapping.
**It is a display that has no orientation to map onto.**

## 2. The form

Three to eight filament LEDs on their own leads, twisted into a suspended
three-dimensional form — a small chandelier hung inside the bottle, with the
MCU and everything else hidden in the neck, or behind a label where there is
one.

Fit only for **larger vessels**, 1 litre and up. Which is a feature as much
as a constraint: more glass is more surface to tap, which the gesture work
has repeatedly wanted (`insights.md` §8 — tap reliability is a function of
where you can reach).

## 3. The hard problem: with position gone, what is left?

This is the real question and it deserves to be answered before any parts
are bought. **An orientation-free display has exactly three channels.**

### Count — and it is better than it sounds

How many filaments are lit. Rotation-invariant by construction: counting
does not care which way you are standing.

Naively that is only 3–8 states. But **PWM makes the count continuous** —
a partially-lit filament reads as a fraction, so five filaments span 5.0 →
0.0 smoothly. That is a genuine analog readout with no direction at all,
and it is the same cross-fade trick `hardware.md` already proposes for the
linear array, used for a different purpose.

*n* filaments ≈ *n* units of time left. The sand-timer feel, without a
sand-timer's axis.

### Colour temperature — and the vessel does not eat it

White → warm white is a second dimension, and an unusually well-chosen one
for this project: **§12 measured amber glass as a blue-cut filter that
collapses hue onto the red-green axis.** A warm/cool axis *lives on* that
axis, so it survives the vessel that destroys most palettes. Cool reads as
relaxed, warm as urgent, with no learning required.

Note what this changes: in the strip design, colour is a *secondary*
channel carrying line identity. Here it is promoted to primary, because
position is gone. That is a different contract, not a reconfiguration.

### Grouping — orientation-free, unlike an axis

The two-direction problem (arm A and arm B) looks fatal without position.
It is not: **a set is not an axis.** Two interleaved populations of
filaments — or a nested inner and outer form, which is radially symmetric —
are distinguishable by *which* are lit, never by *where*. No front is
implied.

### ⚠ And one idea that quietly undoes the thesis

A **"bright bulge" travelling the 3D form** is the obvious way to
reintroduce a sense of movement. It should be treated with suspicion: a
bulge travels a *path*, a path has a direction, and a direction is a front.
A helix has two ends.

It may still be worth doing — motion is the channel §14 found most survives
diffusion — but it is a *retreat from* principle #6, not an expression of
it, and should be adopted knowing that.

## 4. What it changes upstream

**Wired, always on.** Filaments are not cheap to light — `hardware.md`'s Vf
question decides how expensive, and the Edison-standard family (60–100 V)
would be disqualifying on its own. Several of them, continuously, is
mains/USB territory. The battery work does not apply here.

**Which removes the wake/sleep model entirely** — and that is more
interesting than it sounds. If the display is always on, a tap is no longer
"wake". It becomes *"tell me more"*: a request for detail from something
already speaking. That is a better interaction than the one we have, and it
only becomes available once power stops being scarce.

## 5. The architecture already supports this, which is the point

This needs **no change to stage 1 at all.** `LeaveSignal` is an abstract
snapshot — "what is the urgency?" — deliberately decoupled from "how do we
show it?" (`design-principles.md` #9). The chandelier is a new
`DisplayContract` that consumes the same signal and emits **(count,
temperature)** instead of **(position)**.

That is the two-stage split earning its keep on exactly the case it was
designed for, four months after it was written. Worth saying plainly,
because it is the strongest evidence so far that the abstraction was real
and not decorative.

## 6. The cheaper cousin: addressable micro-LEDs on wire

The "fairy light" / seed-light strings sold for shoving decoratively into
glassware. Programmable versions do exist — search:

| term | finds |
|---|---|
| `WS2812B ストリング` / `ピクセルストリング` | addressable strings, though often 12mm bullet pixels — too big |
| `LEDジュエリーライト` / `ワイヤーライト` | the decorative ones; **usually NOT addressable** — check before buying |
| "addressable fairy lights" / "individually addressable string" | the English listings, where the distinction is stated more often |

**And here is the convergence worth noticing:** if you shove an addressable
string randomly into a bottle, its *logical* order has no relation to its
*physical* position. §5 anticipated exactly this — "keep the logical order
fixed underneath, so rendering is unchanged" — and `_physical()` is the seam
built for it.

But the deeper consequence is that **position-based rendering becomes
meaningless**, so you would render by count and colour anyway. The random
micro-LED version and the filament version arrive at the same contract from
opposite directions, which is a reasonable sign the contract is the right
one.

## 7. Parts and search terms

`shopping-battery-power.md` § "Making the light look like light" — filament
families and the Vf trap, warm/cool pairs, addressable strings and the
pixel-size trap, plus the two things that make a clear vessel viable at
all: **ジュンフロン線** (ultra-thin ETFE wire) and **テグス** (fishing line,
for invisible suspension).

It opens with the problem this concept exists to solve, which is worth
restating here because it is principle #6 read from the other side:
**a bottle with no front also has no back.** There is no angle that is
"behind", so a strip's PCB, traces and solder pads are always somebody's
view. Opaque brown glass has been hiding that, which is the only reason it
has not come up yet.

## 8. Prerequisites, in order

1. **The forward-voltage measurement** (`hardware.md` § Filament array,
   "step zero"). 9 V battery and a 1 kΩ resistor. This single measurement
   decides whether the whole family is usable, and it is cheaper than any
   design work that would depend on it.
2. **The IMU investigation.** This is a capstone, not a detour — it wants
   more tapping and less lifting, and tapping is precisely what is still
   unreliable (`on-board-detection.md`). A larger vessel gives more surface
   to tap, which helps; it does not fix the classifier.
3. **A vessel.** 1 litre or more, and the colour decision becomes different
   here — a warm/cool axis needs less hue headroom than a multi-line
   palette does, so a *more* opaque bottle may become viable rather than
   less.

---

## Addendum (2026-09-29) — the lamp reframe, and a bird's nest

Two things said in conversation that belong here.

**The costume change solves the power and harness walls instead of
engineering around them.** A bottle is expected to be wireless and to sleep;
that expectation is what makes the battery build (load switch, `AWAKE_MINUTES`,
wake windows — `shopping-battery-power.md`) and the Qi flat-bottom constraint
necessary. A **lamp** is expected to be on a cord and always on. Reframe the
object and the wall moves: **USB power enters through the top**, into a
custom **neck/lid unit** that carries the MCU, IMU, RTC and the filament
drivers as one assembly — built outside the vessel and lowered in, which is
also the wiring-harness answer (`dev-status.md`). Being "a light that is
always on" is also more forgiving of the parts of the display that are
currently wrestling with idle states (the anchor/markers promise, the horizon
ceremonies): an always-lit lamp does not owe the viewer a sleep/wake story.

**A trade with the IMU wall.** Always-on power is what makes always-on
inference (`on-board-detection.md`) reachable — models that a battery build
could never afford. So the two walls trade off: engineering discipline
(load switches, short wake windows) saves you on battery, ML saves you on wall
power. Caveats that do not go away: per-unit calibration (§8 of `insights.md`,
0% cross-bottle), and a **lid-mounted IMU is a different signal** from the
base-mounted one every recorded dataset was collected on. Fix the
*arbiter* first (`docs/imu-interaction-plan.md`) — it transfers; thresholds do
not.

**A bird's nest as an alternative to a designed chandelier.** Instead of
three to eight filaments deliberately twisted into a form, an irregular tangle
of filament wire, with the logical→physical mapping deliberately arbitrary.
This is the strongest possible reading of design principle #6 and of the
`scatter` ordering already shipped (`insights.md` §20): if the data has no
order and the object has no front, the mapping *should* look like it. Cost:
the count/temperature channels (§3) are all that survive, so the display
vocabulary must be built on those rather than on position — same constraint as
the chandelier, taken further. Untested; the cheap test is a tangle of
addressable-LED pigtails before any filaments are bought.

**Input vocabulary may shrink.** Tilting a corded, hanging lamp is odd; tap on
the vessel probably survives. If tilt goes, the IMU plan shrinks to "make tap
robust to being nudged" — still the same arbiter and replay harness.

---

## Demo build (2026-10-19) — nOOds-style filaments, flower on a canopy

Written after an assessment of Adafruit's *nOOds* flexible filaments as the
chandelier's light source. **Still a proposal; nothing built.** The sections
below are in the order you would actually do them: debug the unmarked
filament in hand first, then know what the reference part is, then the shape,
then the electronics.

### A. Debugging the unmarked filament

`hardware.md` § Filament array step zero asks which of three voltage families
a bare filament belongs to. For the Adafruit part that is already answered
(3 V family, below). For a **found filament with no markings** it is not —
and you cannot tell by looking. Do these in order and stop at the first
step that tells you what you need.

**0. Look and feel — no power.**
- Flexible, silicone-coated, ~2 mm thick, metal tabs at the ends → candidate
  for the 3 V family.
- Rigid glass or ceramic stick (Edison-bulb style) → almost certainly the
  60–100 V family. **Don't force it** — it snaps, and it is not usable here.
- Note which end has a small hole in the tab: on nOOds that is the anode.

**1. Diode-test mode — the meter is the current source.** Set the multimeter
to the diode symbol and touch the probes to the two tabs, then swap them.
The meter pushes about 1 mA through the part.

| Reading | Likely meaning |
|---|---|
| ~2.3–3 V one way, `OL` the other | Parallel-wired dies, **low-voltage family** — what this design needs. Often a faint glow; dim the room |
| `OL` both ways | Many dies in series (high-voltage family) **or** a broken filament. The meter can only drive ~2.5–3 V so it cannot tell them apart |
| ~0 V | Short — discard |

Caveat: this is the drop at ~1 mA, so it *classifies* the family but is
**not** the operating voltage (that is higher at the real current).

**2. Resistor ladder — the real I–V curve.** Supply (+) → series resistor →
filament → supply (−), meter in **voltage mode across the filament only**.
Current is not measured, it is calculated: `I = (V_supply − V_filament) / R`.
The resistor is what makes this safe: a 3 V-class filament's curve is steep
(see the reference table), so a bare supply with no resistor turns a small
voltage error into a large current.

| Supply | Resistor | Approx. current if it is a 3 V-class part |
|---|---|---|
| 5 V (USB) | 1 kΩ | ~2–3 mA |
| 5 V | 470 Ω | ~5 mA |
| 5 V | 220 Ω | ~10–12 mA |
| 5 V | 100 Ω | ~20–25 mA |
| 5 V | 47 Ω | ~45–50 mA (¼ W resistor is fine; ~0.12 W) |

Write down the filament voltage at each rung. Compare against the reference
table below: a match at 20 mA ≈ 2.5 V means it behaves like a nOOds.

**Bench supply instead:** set the current limit to 5 mA, start at 0 V, raise
until the limit holds, record the voltage; repeat at 10, 20, 50 mA. **Never
exceed 50 mA** until the curve is known — Adafruit's own guidance for their
part is to limit to 50 mA.

**Don't:**
- Use the meter's **current (A/mA) mode across a supply** — it is a near-short
  and blows the meter's fuse.
- Drive the filament from a **fixed supply with no resistor**.
- Test an unknown filament on **mains** to find out. Ever.

**Reading the result.**

| Outcome | What it means |
|---|---|
| Glows at 5 V via ≥100 Ω, voltage ≈ 2.5–3 V | 3 V family. Usable. Record the curve under this section |
| Dark at 5 V via 47 Ω, `OL` in diode mode | High-voltage family or dead. Park it; buy the reference part instead |
| Lights but voltage near 12 V | The 12 V family (series strings, like Switch Science 9117). Usable on its own 12 V rail, **not** mixed with 3 V ones |

*Fallback from `hardware.md`:* 9 V battery + 1 kΩ in series limits to <9 mA
whatever the part is. If it glows, it is a low-voltage type.

### B. The reference part and where to get it

**Adafruit nOOds, 3 V family.** Dozens of micro-LEDs wired in parallel on a
flexible metal backing, silicone-coated; ~1.7 × 1.9 mm cross-section; bend
limit ~1 mm radius, twist rated 360° per ~25 mm; **PWM-dimmable, not
addressable**. Anode = the metal tab with the small hole. Published curve
(Adafruit, for the 130 mm warm white):

| Supply V | 2.5 | 2.6 | 2.7 | 2.8 | 2.9 | 3.0 |
|---|---|---|---|---|---|---|
| Current (mA) | 20 | 40 | 90 | 140 | 190 | 230 |

Another vendor lists ~300 mA for the same size, so size the supply for 300 mA
per filament *if ever driven unlimited*; the design drives them at 50–100 mA.

| Part | Source | Note |
|---|---|---|
| nOOds 130 mm warm white, 3 V | [Adafruit 5504](https://www.adafruit.com/product/5504); Switch Science **8403** | double-ended |
| nOOds 300 mm warm white, 3 V | [Adafruit 5503](https://www.adafruit.com/product/5503); [Switch Science 9116](https://www.switch-science.com/products/9116) (ADA-5503) — **¥1,100 incl. tax**, ~285 mm lit | double-ended; the domestic option |
| nOOds 600 mm warm white, **12 V** | Switch Science **9117** | different electrical family — own rail, not mixable |
| **Single-ended** nOOds (both tabs at one end) | Adafruit [6141](https://adafruit.com/product/6141) (25 mm warm), [6146](https://adafruit.com/product/6146) (300 mm natural white), [6148](https://adafruit.com/product/6148) (300 mm cool white), 6150 (red), 6151 (green) | hang from the lid, nothing at the bottom |
| Flexible filament 300 mm, 3 V | [Kitronik](https://kitronik.co.uk/products/flexible-led-noodle-filaments-300mm-3v) | same idea; ~200 LEDs |
| Flexible filament 130 mm, 3 V, 2200 K | [Elecrow via RobotShop](https://eu.robotshop.com/products/elecrow-130mm-flexible-led-filament-3v-2200k-led-filament) | rated <80 mA |
| DFRobot flexible filament 260 mm, 2200 K, 5-pack | [RobotShop JP](https://jp.robotshop.com/en/products/dfrobot-フレキシブル-led-フィラメント-3v-260mm-2200k-5-個パック) | listing blocked automated fetch — **price and stock unchecked** |

*Prices and stock as seen on 2026-10-19; nothing was ordered. Searches of
Akizuki, Marutsu and AliExpress found nothing — which means not found, not
that they do not carry it.* Japanese search terms: `フレキシブル LEDフィラメント 3V`,
`LEDフィラメント 電球色 フレキシブル`, `nOOds`.

**Only warm white is stocked domestically** (as far as seen). A warm↔cool
axis (§3) therefore means importing natural/cool white, or deferring it.

### C. What one filament can express

**One filament is one channel.** Every die inside it sees the same voltage, so
brightness is uniform along its length — no gradient within a filament, no
colour, no addressing. Per channel the only live variable is brightness *over
time*.

| Axis | Needs | Notes |
|---|---|---|
| Brightness over time | one filament | breathing rate, pulse shape, flicker — the five motion words (`light-language.md`) live here |
| Count / which are lit | several | rotation-invariant; the sand-timer axis of §3 |
| Warm↔cool | a warm and a cool filament **twisted together**, cross-faded | per-spot tunable white; needs imported cool filaments |
| Physical form | build time only | length, coil, position change each filament's weight in the picture; not live |

**Test the cheap pair first:** count + time, using warm-only local parts
(4–5 × Switch Science 9116 ≈ ¥5,500). If time-remaining reads from those two
alone, add cool white only if you then want a third channel.

### D. The shape: loops, not lines

A **double-ended filament folded in half is electrically a single-ended one**:
both tabs together at the top, a petal hanging below. Consequences:

- **The whole object hangs from one point** — no lower mount, no return path
  to the bottom, no structure in the vessel.
- **A loop cannot show a front.** Brightness is uniform, so both sides of a
  petal always match. This is the *mirrored / two-way 3D effect* — a feature:
  it is symmetric by construction. Fades happen **between petals**, not along
  them.
- **6–8 channels doubled over = 12–16 visible strands**, for the pin and pad
  cost of 6–8.
- ⚠ A fade rippling petal 1 → 2 → 3 around a ring is the travelling bulge of
  §3 again — a direction. Fine if chosen knowingly.
- At the tabs: space the two tabs of a loop apart and heat-shrink each; a
  bridged pair shorts the supply. Never let a filament's weight hang from its
  solder joint; strain-relieve every tab. Hang with `テグス` around the silicone
  body, not the tab.
- **Untested:** whether the metal backing holds a bent shape (a flower) or
  springs back (a jellyfish needing a spreader ring or fishing-line splay), and
  how many squeezes a tab survives if the bloom is compressed to pass through
  the neck.

### E. The demo build

**Layout.** A *canopy* sits on top of the neck holding the electronics; only a
slim stem and the filament loops go into the vessel. A typical neck bore is
~18–25 mm and a XIAO alone is ~21 × 18 mm, so MCU + RTC + IMU + drivers
probably do not fit inside the neck. For the demo, solder the XIAO, IMU, RTC,
resistors and MOSFETs on a **round perfboard** (`丸型 ユニバーサル基板`; measure
the bore first, buy ~3 mm smaller) and run the loop pads off its rim. Then
learn how much must move into the bottle. Seal the neck with a stopper
(`シリコン栓`, `ゴム栓`) that carries the load so the cable is strain-relieved.
USB-C comes up the top — a lamp is expected to be on a cord.

**Channel budget.** `pinouts/v1.6-rp2350-production-unit.md` lists eight free
pins (D0–D3, D6, D8–D10); D7 (strip data) frees up with no strip → nine.
Keep one for the IMU interrupt → **eight PWM channels**. NFC on SPI
(D8–D10) would take three of them. Beyond eight: an I²C PWM expander such as
the PCA9685 (16 ch) — but its outputs are ~25 mA, so each channel still needs
a MOSFET. Do not do this until the 8-channel version has taught you what to
want.

**Power and heat.** 8 × 100 mA ≈ 0.8 A. Plain USB is only guaranteed 500 mA,
so plan on a ≥1 A charger; **whether the XIAO's USB-C port negotiates above
500 mA with a C-to-C cable is unchecked.**

Correction to the earlier "nothing needs ventilation": the MOSFETs barely warm,
but at 5 V with a series resistor for a 3 V filament the **resistor burns ~40%
of the power**: ~0.2 W per channel at 100 mA, ~1.7 W across eight, inside a
small cap. Warm, not dangerous, but design for it:

- Run at **~50 mA per filament** (~0.1 W per resistor, <1 W total), ½ W parts.
- Or a shared buck converter to ~3.1 V so the resistors have little to burn.
- Keep resistors away from the IMU so its temperature reading is not theirs.

Resistor value comes from the *measured* curve: `R = (5 V − Vf@I) / I`, with
Vf at the target current read off §A step 2.

**Hardware safety — first line of defence, software second:**

1. Resistors sized so the worst case (PWM stuck at 100 %) is safe.
2. **Gate pull-down on each MOSFET** (e.g. 10 kΩ), so a crashed or
   unprogrammed MCU leaves the lights **off**.
3. A polyfuse on the 5 V input.
4. A watchdog, so a hung program resets instead of freezing a channel on.
5. *Then* the thermal cutoff: the RP2350's on-die temperature sensor and the
   LSM6DSV16X's temperature output, with the sensor placed next to the
   resistors. It only protects while the MCU runs — hence it is last.

MOSFET choice: any **logic-level** N-channel with Rds(on) specified at
Vgs = 3.3 V (not 4.5 or 10 V). Candidate families to check, *not verified
against this design*: AO3400A (SOT-23), IRLZ44N (through-hole, overkill).

**Swapping bottles.** The canopy-plus-bloom assembly lifts out, so a unit can
move between vessels. Relevant to `docs/gift-registry.md`: a provisioning
record is then per *unit*, not per bottle.

### F. To measure before building further

1. §A on the found filament — and record the I–V curve beside the table in §B.
2. Whether a filament holds a bent shape; how many compressions a tab survives.
3. The lowest usable PWM duty in the bottle's glass (the strip's floor was 3;
   filaments will differ — `make low-pwm-test` is the template).
4. USB-C current negotiation on the XIAO.
5. Cool-white sourcing, only if §C's cheap test says a third channel is wanted.
