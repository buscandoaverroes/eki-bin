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
