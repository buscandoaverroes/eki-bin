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

## 7. Prerequisites, in order

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
