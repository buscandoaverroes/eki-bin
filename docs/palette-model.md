# Palette & brightness — three ways to stop getting this wrong

**Status: proposal. Nothing here is built, nothing is decided.** Written
2026-09-14 after `DAY_BRIGHTNESS = 0.85` was found to clip the anchor and
shift its hue — a bug that existed only as arithmetic, invisible in the
config that caused it and invisible on the strip until you knew to look.

---

## 1. What actually goes wrong, and why it keeps happening

Four failures so far, and they share a structure:

| what happened | why it was invisible |
|---|---|
| `MARKER_BRIGHTNESS 0.15 × BRIGHTNESS 0.15 × 80` = raw 1 → ticks read RED | the product is nowhere in the config |
| `MARKER_BRIGHTNESS = 0` set to hide the above | the workaround looked like a preference |
| `ANCHOR_BRIGHTNESS 1.6 × BRIGHTNESS 0.85` → (255,255,163), not (255,200,120) | per-channel clipping, so it *shifts hue* rather than just capping |
| `# = raw 3` comments that were true once | a derived value written down as a fact |

**The common cause: config is written in emitter space, and every
constraint lives in emitter space, but the user's intent lives in
relational space.** Nobody wants `MARKER_BRIGHTNESS = 0.25`. They want
*"ticks should recede behind the train"*. The number is a guess at how to
buy that, and whether the guess works depends on two other numbers set
elsewhere.

Note what the correct knobs already look like when stated plainly:

- the **day/night ratio**
- the **marker : train : station ratio**
- the **colour scheme**, which is really *"what does this glass allow"*

All three are relationships. None of them is a drive level.

---

## 2. Approach A — ratios in, drive levels out, rescale instead of clip

Config declares relationships plus one absolute request. A **placement
pass at boot** turns them into actual drive values, subject to the two
hard constraints: the low-PWM floor (measured, per strip) and 255.

```
BRIGHTNESS_DAY   = 0.62        # a REQUEST, not a guarantee
BRIGHTNESS_NIGHT = 0.45
ROLE_RATIOS = {"station": 1.6, "train": 1.0, "marker": 0.25}
```

**The property that makes this worth doing: if the brightest role would
clip, rescale the whole set rather than clamping one channel.** Ratios are
preserved by construction, so *clipping can never shift a hue again* —
because you never clip. The anchor bug becomes unrepresentable.

The honest cost: past a certain point "brighter" stops working, because the
scene's own headroom caps it. Requesting 0.85 with a 1.6 station might
deliver 0.62. That is not a limitation being hidden — it is the strip
genuinely unable to render *that scene* brighter without distorting it, and
the right response is to say so:

```
palette: requested 0.85, delivered 0.62 (station headroom)
         station 253,198,119   train 158,124,74   marker raw 10
```

### A′ — the stronger form: ordinal, not ratio

What the user actually wants is that markers **recede** and the station
**stands out**. That is an *ordering*, not a ratio — and an ordering
survives any monotonic mapping, so it cannot break. The strongest version
of A takes a ranked list and spaces the roles across the usable range
`[floor, 255]`:

```
ROLE_ORDER = ("station", "train", "marker")   # brightest → dimmest
```

Nothing to mis-set, nothing to clip, nothing to fall through the floor.
The cost is expressiveness: you lose "the station is *slightly* brighter"
versus "dramatically brighter", which may well matter.

---

## 3. Approach B — `palette_problems()`, and this codebase already has the pattern

`contracts.py` has `geometry_problems()`: a pure function returning a list
of reasons the config can't work, called at boot, printed, and escalated to
`_run_startup_failure_forever(CONFIG_ERROR_COLOR)`. It exists because a bad
geometry surfaced as `IndexError` three levels into the render loop,
pointing nowhere near `config.py`.

**Every palette failure above has exactly that shape**, and none of them
even produce an exception — they produce a wrong-looking jar.

```python
def palette_problems(brightness_levels, roles, floor=3):
    """Reasons the palette can't render correctly; [] means it can."""
```

Three checks, and the third is the one a human cannot do by inspection:

1. **Below the floor** — any role's raw value under the measured low-PWM
   floor, where channel matching collapses and neutral reads red.
2. **Clipping** — any channel of any role over 255, reported as the hue
   shift it causes rather than as a number.
3. **Across the whole reachable range, not the current value.** This is the
   point. A config can be perfectly valid at `NIGHT_BRIGHTNESS` and broken
   at `DAY_BRIGHTNESS`, and nobody reads a config at two brightnesses at
   once. Sweep day, night, and both tilt rails.

A fourth is tempting and should probably wait for evidence: **two roles too
close to distinguish**. §16 found exactly this failure in the motion
vocabulary — a shake ±5 reads as a lap of `around` — and the colour
equivalent is a marker that stops receding. It needs a perceptual distance
metric to be more than a guess.

**This is the cheapest of the three and the only one that is useful
regardless of what else happens**, including doing nothing else. It changes
no config surface; it converts silence into a printed sentence.

---

## 4. Approach C — config in perceptual space, and the vessel as a parameter

The deepest version: the user never writes RGB or linear multipliers.
Colours are hue + chroma; levels are perceptual steps. The firmware owns
gamma, the floor, and the ceiling.

What makes this specifically right for *this* project rather than generic
good practice: **§12 established that the glass is a filter.** Amber cuts
blue, collapsing the hue wheel onto the red-green axis, and that is why
thick brown supports 2-3 line colours while clear supports 5+. In a
perceptual model the vessel becomes an input:

```
VESSEL = "amber_thick"     # → the firmware spaces hues on the axis that survives
LINES = ["keihin", "tokaido"]
```

Instead of picking hues and discovering two of them look identical through
the bottle, you declare the vessel and get hues that are *maximally
separated after the filter*. That is the same move `ARC_ORIGIN` makes for
geometry — describe the physical situation, let the code do the mapping.

**Cost is real:** a colour model on-device, against MicroPython's memory.
This reads like a V2/Rust-era feature, which is consistent with where the
roadmap already puts the harder abstractions.

**But a cheap 80% exists now:** precompute the palettes on the host and
ship a table, the way `make schedule` already turns YAML into a device-side
JSON. No on-device colour maths, and `COLOR_SCHEME` is already the
indirection point it would hang from.

---

## 5. Recommendation, and the order

**B, then A, then C** — and the order is not just ascending cost.

1. **`palette_problems()` first.** Cheapest, matches an idiom already in
   the codebase, and it is the only one that pays off even if the other two
   never happen. It also *generates the evidence* for whether A is needed:
   if it fires constantly, the config model is wrong and A is justified. If
   it never fires, A is over-engineering.
2. **A (ideally A′) once B has made the case.** The rescale-instead-of-clip
   property is the single biggest structural win available, and it makes
   the user's own list — day/night ratio, marker:train:station ratio — the
   literal config.
3. **C when the vessel decision is settled**, since C's whole value is
   modelling a vessel and that choice is still open.

### Two things any of them needs first

- **The low-PWM floor must become a per-unit config value**, not a comment
  saying 3. `make low-pwm-test` measures it, §12 says it is per-strip, and
  every proposal here needs it as an input. It belongs in the unit's
  registry entry alongside `ARC_ORIGIN` and `SHAKE_CENTER`.
- **A boot-time palette report**, whichever way this goes. This codebase
  already announces its state — the memory table, `[DAY] brightness →
  0.62`, the geometry check. Palette is the one subsystem whose derived
  values are currently invisible, which is precisely why its bugs were.

### The rule to hold all three to

> **Every one of these should REMOVE config surface, not add it.**

The failure mode being fixed is too many interacting numbers. A proposal
that adds a knob to make the existing knobs safer has not fixed it.
