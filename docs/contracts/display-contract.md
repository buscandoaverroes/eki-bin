# Contract: display pipeline

**Implemented in:** `micropython/main.py`
**Shape:** `time → LeaveSignal → DisplayContract → LEDs`

The display is a two-stage pipeline with a deliberate seam between them:
*"what's the urgency?"* (Stage 1, pure logic) is computed independently of
*"how do we show it?"* (Stage 2, rendering). You can swap the entire visual
language by changing one line — `ACTIVE_CONTRACT` — without touching the time
logic.

```
  schedule + now
        │  next_departures()         minutes until each upcoming train
        ▼
   time_to_leave()  ── subtract WALK_TO_STATION_MINS, drop uncatchable ──┐
        │                                                                │
        ▼                                                                │
   LeaveSignal  { ttls:[…], primary, urgency }   ← ephemeral, per tick   │
        │                                                                │
        ▼                                                                │
   ACTIVE_CONTRACT.render(signal, phase_ms)  ──► np.write()              │
        ▲                                                                │
        └─ SandTimer / Color / Breathing … (strategies) ────────────────┘
```

---

## Stage 1 — time → abstract signal

Pure functions and value objects. No LEDs, no colour. Easy to unit-test on the
host (see the smoke test pattern: stub `machine`/`neopixel`/`config`, then call
`classify`, `time_to_leave`, `leave_signal`).

| Symbol | Role |
|---|---|
| `WALK_TO_STATION_MINS` | Time room→platform. Subtracted **once**, here. (`[→ NFC]` later from a station card.) |
| `time_to_leave(minutes_until)` | Departure → minutes until you must **leave**. Returns `None` if uncatchable (`ttl < 0`). |
| `classify(ttl)` | **Pure** `ttl → Urgency`. Thresholds only — no time math, no colour. |
| `Urgency` | Abstract level: `name` + `level` (0 = hidden, 1 = most urgent … higher = calmer). Singletons `HIDDEN/LEVEL_1/2/3`, compared with `is`. |
| `LeaveSignal` | Per-tick snapshot: `ttls` (catchable, soonest-first), `primary` (`ttls[0]`/`None`), `urgency` (derived). |
| `leave_signal(departures, now)` | Builds the snapshot for one direction. |

**Why two fields, `ttls` *and* `urgency`?** Urgency is discrete (a colour band).
A proportional arc or a pulse rate needs the **continuous** `ttl`. So the signal
carries both; each contract takes what it needs. Because arc length carries the
continuous precision, **few urgency levels are needed** — urgency just picks a
colour.

**Uncatchable trains are dropped.** `time_to_leave` returns `None` for any train
within `WALK_TO_STATION_MINS`, so the jar only ever shows trains you can still
make. A train "in 2 min" with a 2.5-min walk renders nothing.

**The signal is ephemeral.** It's rebuilt every tick from `(schedule, now)`,
owns no state, and survives nothing — there's no staleness to manage.

---

## Stage 2 — signal → pixels (display contracts)

A `DisplayContract` is a rendering strategy. The main loop treats every contract
identically: it calls `render(signal, phase_ms)` and honours `frame_ms`.

```python
class DisplayContract:
    frame_ms = None                      # see timing below
    def render(self, signal, phase_ms): ...
```

| Field / method | Meaning |
|---|---|
| `render(signal, phase_ms)` | Draw **one** frame. `phase_ms` = ms since this interval began (0 for static contracts). |
| `frame_ms = None` | **Static**: draw once, then the loop sleeps the interval. Deep-sleep-friendly (the V2 power path). |
| `frame_ms = <int>` | **Animated**: redraw every `frame_ms` across the interval. Cannot deep-sleep while animating. |
| `COLOR` | Per-contract urgency→`(r,g,b)` map. Defaults to module `PALETTE`. |

Shared helpers (don't reimplement):

| Helper | Does |
|---|---|
| `_arc_len(ttl)` | `ttl` → number of lit LEDs, **shrinking** toward 1 as the deadline nears; full arc at `ttl` beyond `MINUTES_PER_LED × NUM_LEDS`. |
| `_layer_mult(index)` | Relative brightness for the `index`-th train layer (`1.0` for the primary, `BACKGROUND_BRIGHTNESS ** index` beyond that). |
| `_paint_layers(layers)` | Composite multiple `(color, lit, mult)` arcs onto the strip in **one** frame — the paradigm-independent primitive everything below is built on. See "Multiple trains" below. |
| `_paint(color, lit, mult=1.0)` | Single-layer convenience wrapper over `_paint_layers` — light the first `lit` LEDs (index 0 = DIN end) at `BRIGHTNESS × mult`; rest off; one `np.write()`. |
| `clear()` | All LEDs off. |

### Built-in contracts

| Contract | `frame_ms` | Uses | `N_TRAINS`? | Behaviour |
|---|---|---|---|---|
| `SandTimerContract` | `None` | `urgency` + `ttls` | yes | Shrinking arc(s), colour by band. **Default.** All layers dim uniformly (`BACKGROUND_BRIGHTNESS`). |
| `ColorContract` | `None` | `urgency` | no | Full bar; only the colour changes. No arc geometry to layer a 2nd train onto. |
| `BreathingContract` (+`_exponent`/`_inverse`) | `FRAME_MS` | `urgency` + `ttls` + `phase_ms` | yes | Arc(s) that pulse brightness together; `breathe_fn` swappable per subclass. |
| `EchoContract` | `FRAME_MS` | `urgency` + `ttls` + `phase_ms` | yes | **Per-layer**, not uniform: primary is static/full brightness; every train beyond it is hue-shifted (`SECONDARY_HUE_SHIFT_DEG`) + gently breathing near-full brightness (`SECONDARY_BREATHE_*`). See "Per-layer treatments" below. |

`HIDDEN` is never in `COLOR`; contracts handle it first with `clear()`.

### Multiple trains (`N_TRAINS`)

`LeaveSignal.ttls` was designed from the start as a plain list of catchable
times-to-leave, soonest first — no geometry baked in — specifically so showing
more than one departure wouldn't require touching Stage 1 at all. Since later
trains always have equal-or-longer arcs (more time away = more relaxed = longer
arc), multiple trains render as **nested bands**, not separate/competing arcs:
the primary lights up bright out to its own length; each further-out train
extends a band beyond that (uniformly dimmer in `SandTimerContract`/
`BreathingContract`; hue-shifted + subtly animated in `EchoContract` — see
below).

```python
layers = [
    (color, _arc_len(ttl), _layer_mult(i))
    for i, ttl in enumerate(signal.ttls[:N_TRAINS])
]
_paint_layers(layers)
```

`_paint_layers` composites back-to-front (later `layers` entries painted
*first*, so earlier/brighter entries win where arcs overlap — including the
edge case where two trains round to the same arc length) and writes the strip
**once**, so temporal dithering stays coherent regardless of layer count.

**Why this is paradigm-independent:** every layer is still just a
`(color, lit, mult)` tuple flowing through the *same* `_physical()` seam a
single-train render would use. A bar, a ring, or a randomized "cosmos" layout
all consume `_paint_layers` identically — the only thing that would ever need
to change per paradigm is `_physical()` itself (see the HAL seam below), not
this compositing logic. `N_TRAINS = 1` (the default) reproduces the original
single-arc behaviour exactly.

### Per-layer treatments (`EchoContract`)

`SandTimerContract` and `BreathingContract` apply the *same* treatment to
every layer (uniform brightness falloff, or uniform breathing). Real-hardware
testing found that doesn't hold up (`docs/insights.md` §6): at low absolute
brightness, temporal dithering runs out of headroom (too few 8-bit codes to
blend between — visible as flicker) and the LED stops diffusing enough light
to read as ambient glow (visible as the die itself). Brightness alone can't
safely differentiate a background layer on this hardware.

`EchoContract` differentiates by **colour + subtle motion** instead, and gives
the primary a genuinely *different* treatment from every layer beyond it:

```python
for i, ttl in enumerate(signal.ttls[:N_TRAINS]):
    if i == 0:
        color, mult = base_color, 1.0                 # primary: static, full
    else:
        color = hue_rotate(base_color, _layer_hue_shift(i))
        mult = breathe_fn(phase_ms, SECONDARY_BREATHE_PERIOD_MS, SECONDARY_BREATHE_FLOOR)
    layers.append((color, _arc_len(ttl), mult))
```

Both `hue_rotate` (colour, layer C) and `breathe_fn` (motion, layer B) are
existing primitives — this contract composes them, it doesn't reinvent
anything. `SECONDARY_BREATHE_FLOOR` defaults high (`0.7`) deliberately: this is
a subtle differentiation pulse, not `BreathingContract`'s dramatic urgency
breath, so it gets its own config knobs (`SECONDARY_*`) rather than sharing
`BREATHE_FLOOR`/`BREATHE_PERIOD_MS` — tuning the primary breathing contract's
feel shouldn't also retune this one's.

Found via `led_sandbox.py` (a hue shift around 20° + a high-floor breath around
a 3s period), not derived analytically — this is exactly the kind of tuning
that needs eyes on real hardware, not just correct math.

---

## Layering: primitives → contracts → pixels

The full stack, top (abstract) to bottom (wires). A contract is a *strategy* that
**composes** reusable building blocks; it never touches `np[i]` directly.

```
  main loop (per tick)
      │   signal = leave_signal(...)            ← Stage 1 result (abstract)
      ▼
  ┌─────────────────────────────────────────────────────────┐
  │  DisplayContract.render(signal, phase_ms)                │  WHAT to show
  │    SandTimer · Color · Breathing(+variants)              │  (strategy)
  └───────────────┬─────────────────────────┬───────────────┘
                  │ composes                 │ composes
   ┌──────────────▼─────────────┐   ┌────────▼────────────────┐
   │ animation primitives       │   │ colour                  │  reusable
   │  A. phase_sawtooth·        │   │  PALETTE / SCHEMES       │  building
   │     tri01·sine01·square01  │   │  dim · lerp_color        │  blocks
   │  B. breathe·blink·pulse    │   │  D. gamma (perceptual)   │
   │     (elapsed → 0..1 mult)  │   └────────┬────────────────┘
   └──────────────┬─────────────┘            │
                  └────────────┬─────────────┘
                               ▼
       [(color, lit, mult), …] one layer per train (N_TRAINS)
                               ▼
              _paint_layers(layers) · _paint(...) · clear()   RENDER seam
                               │        (dithers, quantizes, one np.write())
                               ▼
                       _physical(logical)                     HAL seam
                               │   (ARC_ORIGIN today; a per-device
                               ▼    driver later: ring wrap, reversed…)
                          np[i] → WS2812B
```

Read it as: **time → signal → contract → N layers → `_paint_layers` →
`_physical` → LEDs.** Each horizontal line is a seam you can change in isolation.

### Animation primitives

Pure, LED-free, host-testable helpers (in `main.py`, candidates to move to
`animations.py`). Contracts compose them instead of re-deriving wave math.

| Layer | Functions | Returns |
|---|---|---|
| A — phase / shape | `phase_sawtooth(elapsed_ms, period_ms)`, `tri01(p)`, `sine01(p)`, `square01(p, duty)` | `0.0–1.0` |
| B — envelopes | `breathe(elapsed_ms, period_ms, floor, ceiling)` (+ `breathe_exponent`/`breathe_inverse`, same signature over a distorted phase), `blink(…)`, `pulse(…)` — all oscillate within `[floor, ceiling]`, `ceiling` defaulting to `1.0` | brightness `mult` `0.0–1.0` |
| C — colour | `dim(color, mult)`, `lerp_color(c0, c1, t)`, `hue_rotate(color, degrees)` | `(r,g,b)` |
| D — perceptual | `gamma(mult, g=GAMMA)` | `0.0–1.0`, reshaped for the eye's log response |

Example, `breathe()`:

```python
def breathe(elapsed_ms, period_ms=8000, floor=0.2, ceiling=1.0):
    p = phase_sawtooth(elapsed_ms, period_ms)      # Layer A: where in the cycle?
    return floor + (ceiling - floor) * sine01(p)   # Layer A wave → Layer B envelope
```

`ceiling < 1.0` caps how bright a layer's peak can get — useful for a
background/secondary layer whose peak shouldn't be mistakable for a primary at
full brightness (see `docs/insights.md` §6). Not yet wired into any contract's
default — still being tuned via `led_sandbox.py`.

A `BreathingContract` then reads as: `mult = breathe(phase_ms, ...)` →
`_paint(color, _arc_len(signal.primary), mult)`. The primitive owns the motion;
the contract owns the meaning. The same `sine01`/`phase_sawtooth` building blocks
are reusable across brightness (layer B), colour fades (layer C), or anything
else a future contract needs a 0..1 wave for.

### Render & HAL seams

- **`_paint_layers(layers)` / `_paint(color, lit, mult)` / `clear()`** — the
  *only* code that writes pixels (`_paint` is a single-layer convenience call
  into `_paint_layers`). This is the render seam; it's exactly the surface a
  hardware driver would expose. Also owns dithering (`DITHER`) and the
  perceptual `gamma()` curve — one `np.write()` per frame regardless of how
  many layers (trains) were composited.
- **`_physical(logical)`** — maps a logical arc position (0 = origin) to a physical
  LED index, honouring `ARC_ORIGIN`. The HAL seam: a future `led_drivers/<name>.py`
  takes this over to handle reversed strips, ring wrap-around, dead-pixel gaps —
  without any contract or the loop noticing. Multi-train layering doesn't add any
  new requirements here — every layer still just flows through this one seam.

---

## The update/render split (timing)

The "tick" (recompute the signal) is separate from the "frame" (draw):

- **Update** — `leave_signal(...)` runs once per loop iteration. The signal is
  then **fixed** for the whole interval.
- **Render** — `render_for_interval(contract, signal, seconds)`:
  - static contract → `render(signal, 0)` once, returns immediately, caller sleeps;
  - animated contract → frame loop, `render(signal, time.ticks_ms())` every
    `frame_ms`. The clock is **absolute**, not per-interval elapsed, so the phase
    is continuous across intervals (no snap-back to the breath floor every
    `LOOP_INTERVAL_SECS`). Safe because the phase functions do `(clock % period)`
    — integer modulo before the divide, so the large value costs no precision.

This is why "pulsing" is **not** a property of the state. A pulse is simply what
an animated contract *does* with `phase_ms`. The main loop knows nothing about it.

**V2 tension to remember:** animated contracts (`frame_ms` set) block deep sleep,
so they're incompatible with the ~2 mA sleep target. `frame_ms = None` contracts
stay sleep-friendly. Keep that boundary explicit.

---

## Adding a new contract

1. Subclass `DisplayContract`.
2. Set `frame_ms` (`None` = static, int = animated).
3. Implement `render(self, signal, phase_ms)`:
   - `if signal.urgency is HIDDEN: clear(); return`
   - otherwise compose `_arc_len` / `_paint` (single train) or build a `layers`
     list + `_paint_layers` (multiple trains, via `signal.ttls[:N_TRAINS]`) as
     you like. Not every contract needs `N_TRAINS` — skip it if the strategy
     has no arc/length axis to hang a second train on (see `ColorContract`).
4. Add it to the `CONTRACTS` registry, then point `ACTIVE_CONTRACT`/`CONTRACT`
   at it (config, no code change needed at flash time).

Test it without WiFi from the REPL:

```python
import main
main.ACTIVE_CONTRACT.render(main.LeaveSignal([6.0]), 0)   # a 6-min-to-leave frame
main.clear()
```

---

## Tuning knobs

All read from `config.py` via `getattr` (backward-compatible defaults — see
`docs/contracts/config.md` for the full reference table). The display-relevant
ones:

| Config field | Effect |
|---|---|
| `WALK_TO_STATION_MINS` | Shifts the whole "time to leave" frame; raises/lowers what counts as catchable. |
| `MINUTES_PER_LED` | Minutes-to-leave each LED represents (how early the arc starts shrinking). |
| `URGENCY_THRESHOLDS` | Where the colour bands fall (`classify()`). Tight bands = less colour movement with short headways; widen for more. |
| `BRIGHTNESS` | Global ceiling; ambient, not blinding. |
| `COLOR_SCHEME` / `PALETTE` | Urgency → colour. |
| `GAMMA` | Perceptual brightness curve — smooths dim-end banding. |
| `DITHER` | Temporal dithering — the other half of low-end smoothness, alongside `GAMMA`. |
| `FRAME_MS` | Animation frame duration (animated contracts only). |
| `BREATHE_PERIOD_MS` / `BREATHE_FLOOR` | Breath speed and how dim the trough gets. |
| `N_TRAINS` / `BACKGROUND_BRIGHTNESS` | How many trains render as nested arcs, and how much dimmer each further-out one is. |

---

## V1 → V2 (Rust)

| V1 (MicroPython) | V2 (Rust/Embassy) |
|---|---|
| `classify(ttl) -> Urgency` (singletons) | `enum Urgency` + `impl From<f32>` |
| `LeaveSignal` (per-tick object) | a plain struct value computed each loop |
| `DisplayContract` (duck-typed strategy) | `trait DisplayContract` + `dyn`/generic dispatch |
| `frame_ms is None` branch | the same seam decides `Timer::after` vs a frame loop |

See `docs/rust-migration.md` for the broader map.
