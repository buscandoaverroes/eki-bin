# eki-bin — Roadmap / Hardware Handoff

_Living roadmap from a planning session (2026-06-29). Captures form-factor
philosophy, the immediate v1.1 build, and the harder standalone/clock research
threads. Complements `dev-status.md` (near-term what/next) and `docs/concept.md`
(the "why"). Not a commitment to a single linear path — see below._

---

## Current State (2026-09-29)

- **Production unit:** XIAO RP2350 + DS3231 + IMU + 21-LED strip in a brown
  glass bottle, USB-powered, no radio. Runs `ApproachContract` with tap-to-cycle
  lines, tilt brightness, ceremonies. See `dev-status.md`.
- **What stands between it and givable:** the tap/tilt interaction problem, a
  wiring harness, and power — and the form-factor fork (strip-in-bottle vs
  chandelier) that could dissolve the last two.
- The v1 Pico-on-breadboard rig and the v1.1 XIAO C3 + Qi build below are
  historical stages, kept for their findings.

---

## Form-Factor Philosophy

Explicitly **not** a linear progression. Multiple variants/paradigms in parallel,
differentiated mainly by **dev barrier**, not by some "final" design.

### Bottle paradigm (MCU + ambient lights — current direction)
- **Easy** — current v1: MCU external, wired, lights only inside bottle.
- **Medium** — v1.1 (next step): everything inside, Qi-powered, still WiFi/NTP.
- **Hard** — fully encapsulated, no WiFi, battery-only (Nordic-class MCU, ~1+ year
  on a cell). Main open problem is **givability/onboarding** — not electronics.

### Clock paradigm (explicitly skeuomorphic, "magical clock")
- **Easy** — circular dial, 2–3 physical "hands" pointing at custom labels
  (Leave Now / Wait / Hurry) instead of numbers, driven by salvaged quartz-clock
  stepper movements.
- **Hard** — small circular e-ink or Sharp Memory LCD behind/instead of a dial;
  normal mode shows a clock face, plus a "magical" input mode where hands double
  as an input device and the display shows input targets.

Treated as **separate parallel research threads**, not sequential steps.

---

## v1.1: Qi-powered, in-bottle — ✅ confirmed 2026-07-13 (historical spec)

**Goal**: kill the visible wire, keep everything else the same. Always-on
lighting (no LiPo in the main power path).

> **Board update:** scoped originally as the ESP32-S3; the C3 is what's actually
> in hand (single-core RISC-V, cheaper/simpler — sufficient for WiFi + NTP +
> NeoPixel, no need for the S3's extra grunt or PSRAM here). Same XIAO form
> factor, so the bottle-neck fit argument below is unchanged.

| Part | Why | Source |
|---|---|---|
| Seeed XIAO ESP32-C3 | Narrow (~17.8 mm) fits an 18–19 mm bottle neck; keeps WiFi/BT for current NTP firmware; native USB (Serial/JTAG built into the chip) | Switch Science, Amazon.co.jp |
| Qi receiver coil module (regulated 5 V out) | Feeds XIAO 5V/VBUS directly — no LiPo, TP4056, or charge management | Akizuki, Amazon.co.jp / AliExpress |
| AE-WS2812B-STICK8 (owned) | Reuse as-is; isolate the power-path change as the only variable | — |
| Small diode (reverse-polarity protection) | Between Qi output and XIAO 5 V pin | Akizuki |
| Electrolytic cap (~100–330 µF) | Optional — only if ripple/flicker on Qi's rectified output | Akizuki |

**Wiring**: Qi 5 V → XIAO 5 V pin → XIAO GPIO → LED stick data pin, common
ground. No battery in the main line. Goes dark off the pad — acceptable, it lives
on the shelf/pad.

**Bottle-neck constraint**: standard wine bore ~18–19 mm at the lip, widening
below. A flat rigid board passes edge-first if its *narrow* dimension is under the
bore. Caliper the actual candidate bottle — ±1–2 mm matters. Sake necks vary;
measure directly.

### Firmware notes for the XIAO ESP32-C3 migration
MicroPython + WiFi/NTP carry over, but a few Pico-isms need adjusting — worth a
half-hour once the board arrives, not a rewrite. (This is exactly what the **v1.2
board-portability checkpoint** below validates before the Qi work lands.)
- **Heartbeat LED** — done: `HEARTBEAT_PIN` in `config.py` (default `"LED"`, the
  Pico-2W-only CYW43 alias). Set it to the XIAO's onboard-LED GPIO once confirmed,
  or `None` to disable — the console heartbeat (●/○) is unaffected either way.
  See `pinouts/xiao_esp32c3.md`.
- **`import network` / `ntptime`**: both exist in ESP32 MicroPython — fine.
- **Pin numbering**: XIAO GPIO labels differ from the Pico; set `LED_PIN` in
  config to the XIAO pin you wire the stick to. Physical mapping (D-label ↔
  GPIO number ↔ position): `pinouts/xiao_esp32c3.md`.
- **Power-on glitch**: WS2812B can latch a random first pixel at power-up; a
  `clear()` at boot (already effectively happens) plus the reverse-diode/cap on
  the Qi line should cover it. Watch for it during bring-up.

---

## v1.2 — Board Portability Checkpoint ✅ PASSED (2026-07-05)

XIAO ESP32-C3 ran the identical firmware via a `config.py` swap only (under an
hour). It proved **pin** assignments abstract across boards; it did *not* prove
**capability** differences do (no radio is a different program shape — that was
V1.6). Full log, including the `HEARTBEAT_PIN = "none"` and hardcoded
`led_test.py` `DATA_PIN` footguns:
`docs/archive/dev-status-history.md` § V1.2. Pin maps: `pinouts/`.

---

## Architecture: split "sensing" from "compute/power"

To avoid a wire-torsion/lag problem (a freely-hanging pendant won't track jar
rotation reliably):
- **Rigid, at/near the cork**: magnetometer (+ NFC antenna/reader — needs to stay
  near the tap surface). Fits inside/beside a standard cork. No heat concern.
- **Base of jar**: MCU, LED driver, Qi coil, regulator. No orientation awareness
  needed — just executes commands from the cork sensor.
- **Connection**: ~4 thin wires (I²C + power) between the two.

Wine-bottle punts are real but not a blocker — bottles rest on the outer rim,
where a (possibly annular) Qi coil would sit anyway.

---

## Hard Variant: Standalone / Battery-Only — Open Problems

### Battery power — the arithmetic (2026-08-25)

Modelled in `scripts/power_budget.py`. Run it rather than trusting the
numbers below; every unmeasured input is marked ESTIMATE in the file.

**The finding that decides the whole question: a WS2812B draws current when
it is BLACK.** Each pixel's constant-current driver IC is powered whenever
VDD is present, regardless of the colour latched in — roughly 0.7-1.0 mA
each. Twenty-one of them is **~17 mA continuously, displaying nothing.**

| configuration | idle | per day | 3× AA alkaline |
|---|---|---|---|
| strip permanently powered | **17.8 mA** | 504 mAh | **4 days** |
| strip on a load switch | 1.0 mA | 126 mAh | 16 days |
| + `AWAKE_MINUTES` 15→3, 4 taps/day, 2 lit | 1.0 mA | 36 mAh | **55 days** |

So a battery build **requires a P-MOSFET or load-switch IC cutting VDD to
the strip while idle.** That is not an optimisation, it is the difference
between four days and two months. (It also explains something already
observed: an unaddressed strip browned out the board — `insights.md` §13.
Same root cause, the strip draws on its own terms.)

**The second-largest lever is `AWAKE_MINUTES`, and it is free.** 15 → 3
minutes is +181% runtime, larger than any hardware change available. A tap
means "am I about to leave?", and that question is answered in well under
three minutes. Worth revisiting even on a mains-powered unit.

By contrast, MCU sleep current is worth only ~19% across a 10× improvement,
and lit-pixel count ~14%. **Effort spent chasing deep-sleep microamps is
misallocated** until the strip is gated and the wake window is short.

**Voltage constrains the pack.** WS2812B wants ≥3.5 V, so 2× cells is out
without a boost converter. 3× alkaline (4.5 V fresh, sagging to ~3 V) or
4× NiMH (4.8 V) are the practical arrangements — and NiMH's flat discharge
curve suits a fixed-threshold load better than alkaline's slope.

**What this buys beyond runtime**, which is the actual argument: Qi needs a
flat bottom (roughly 1 bottle in 5 qualifies), and a cable needs either a
cord out the top or a hole drilled in glass — no local fab has the tooling.
**Batteries free the vessel choice entirely**, which the colour work
(`insights.md` §12) has just made a first-class design variable rather than
a detail.

Cells fit through the mouth of even a narrow bottle and can be daisy-chained;
inverting the jar drops the pack out for replacement, needing no fixture.
The DS3231 keeps its own coin cell, so **the clock survives every pack
change** — which is what makes a months-long replacement interval tolerable
rather than a re-provisioning event.

### ⚠ Qi concern worth testing, not dismissing

Observed: the transmitter appears to keep delivering power with the MCU
asleep, and the giving side heats the glass noticeably. Neither is surprising
— Qi transmitters ping continuously to detect a receiver, and coupling losses
become heat — but the long-term effect of sustained local heating on glass,
and on a coin cell sitting inside, is untested. **Not a reason to abandon Qi;
a reason to run a multi-day thermal test before committing a gift to it.**

### Power
- **PN532 is the wrong NFC chip for battery** — ~100 mA standby (not a typo),
  dropping to µA only via finicky power-down/wake. For "passively wait for a tap
  for years on a coin cell," use a chip with **Low Power Card Detection (LPCD)** —
  NXP CLRC663 *plus* or ST ST25R391x — averaging ~17 µA by pulsing the RF field.
- **CR2032 math**: ~220–235 mAh but rated ~0.2 mA continuous. Fine for DS3231 RTC
  backup (µA). **Not viable** for MCU wake-cycles + lit LEDs (~1.5–2 mA avg ≈ ~5
  days, not months).
- **No BLE needed for time sync** — DS3231 drifts <1 min/year, so annual NFC-tap
  correction suffices. nRF52840 deep-sleep (~1.4–5.2 µA) and NFC-LPCD (~17 µA) are
  comparable anyway; the deciding factor is BLE needs an app, NFC doesn't.
- **Caution**: datasheet sleep numbers require shutting down *every* peripheral
  explicitly (SPI flash, sensors, dividers) — boards commonly get stuck at
  hundreds of µA from one un-shut-down part.

### Givability / Onboarding (the actually hard problem)
Giving the jar to a friend: they'd need to (a) load a station schedule, (b) sync
time once. The DS3231 removed the time-sync half of this. The schedule half is
the NFC workstream — **on hold and explicitly 2–3 versions out**; first
givability ships with a pre-loaded schedule (like a preloaded gift card).
The no-app "iOS Shortcuts" idea was ruled out on the bench (Shortcuts has no
NDEF content read/write action, and generic NDEF breaks on the ISO-15693 tag).
Bench record and the current candidate path: `docs/nfc-provisioning.md`. The
LPCD-reader research (CLRC663 plus, ST25R391x) is a separate, later variant for
a fully-encapsulated build.

---

## Clock Paradigm: Stepper-Hand Notes

- Cheap quartz movements (¥100–500, craft/DIY kits — search **時計ムーブメント**,
  not Akizuki/Sengoku) contain a **Lavet stepper**: single coil, PM rotor,
  geometric detent that holds position with *zero* standing power between pulses.
- **Hack**: open housing, find the coil's two leads on the driver PCB (black epoxy
  blob = stock driver), bypass it, wire coil leads to MCU.
- **Drive**: bipolar pulse (alternating polarity) to step. Two GPIOs direct to the
  coil (coil resistance limits current) or a small H-bridge (DRV8833) for
  robustness.
- **One direction only** (stator geometry) — fine for a needle sweeping a fixed
  arc (Leave Now → Hurry → Missed It).
- **Async by design**: pulse → step → done. No standing power/CPU between steps.
- **Hands-as-input**: feasible, but the coil can't sense position — add a magnet +
  magnetic angle sensor (AS5600) on the shaft. Detent torque is deliberately
  strong (~1.5× drive) so a manually-turned hand feels clicky, like a watch crown.
- **Mounting**: flat disc (~15–25 mm), a "base module" behind a dial, not
  neck-constrained.

---

## Display Alternatives (non-LED)

| Option | Static power | Update cost | Notes |
|---|---|---|---|
| E-ink (existing plan) | ~0 W | 3–5 mA for 0.3–1.5 s/refresh | ~10-min partial-refresh cadence is fine on a coin cell (~2 yr) *if* true partial refresh (not full-flash) |
| **Sharp Memory LCD (LS013B7DH03)** | 5–60 µW static | 15 µW at 1 Hz | 1.28", 128×128, 3 V, FPC. No flash on update (unlike e-ink), updates frequently. Specific serial protocol + COM toggle — more setup than e-ink |
| Lavet stepper + dial | ~0 between steps | µJ/step | Most literally "analog metaphor"; most fun to build |
| **Filament LED array** | n/a (lit) | continuous PWM | Not a drop-in — a filament is *one* light. Full design, cross-fade maths and the step-zero forward-voltage measurement already written up: `docs/hardware.md` § "Filament array" |

### The chandelier — a display with no orientation (2026-09-14)

Filament LEDs twisted into a suspended 3D form inside a larger bottle. The
culmination of design-principle #6 ("the object has no front"): not a
better mapping of time onto a line, but a display with no line to map
onto. Wired and always-on, which removes the wake/sleep model and turns a
tap from "wake" into "tell me more".

Needs no change to stage 1 — a new `DisplayContract` emitting (count,
temperature) rather than (position), which is the two-stage split earning
its keep on exactly the case it was designed for.

Gated on `hardware.md`'s forward-voltage measurement, and downstream of
the IMU work. Full write-up: `docs/chandelier-concept.md`.

### Hiding a display behind the label (2026-09-04)

A rigid rectangular display is the hardest thing to reconcile with design
principle #2 ("the reveal only works when the technology is hidden by the
material") — glass shows it for exactly what it is. **Except where a label
already is.** The label is a pre-existing opaque rectangle on an otherwise
organic vessel, socially invisible because every bottle has one, and it is
the one place a screen can sit without reading as a gadget bolted to a jar.

Two ways to use it, and they are very different products:

- **Behind, shining through** — a bright segment/matrix display whose *light*
  penetrates the label while the display body stays hidden. Needs a
  translucent-enough label stock and enough brightness to survive it; the
  payoff is that it still reads as glowing glass.
- **As the label** — an e-ink or Memory LCD sized and framed to *be* the
  label. Sharper, far lower power, but it stops being "light in glass" and
  becomes a small screen on a bottle. Whether that's a different product or
  the same one is a real fork, not a detail.

Untested. Cheapest falsification is the label stock, not the display: hold
any bright LED behind the actual label and see whether legible structure
survives it.

---

## Custom PCB (eventual v2/v3 miniaturization)

- **Tooling**: KiCad (free, plain-text S-expression files); Claude Code can work
  on KiCad projects via MCP/skills — placing, routing, DRC/ERC, Gerbers — reviewed
  before fab, not hands-off.
- **Fab**: JLCPCB ships to Japan in ~2–7 business days; ~$5–30 for bare boards, or
  ~$19/board small-batch SMT. No domestic fab needed.
- **Value**: shrink the footprint to exactly what's needed (e.g. a narrow strip
  for the cork-mounted sensor cluster).

---

## Open Questions / Next Experiments (priority order)

> Live status is `dev-status.md`. This list is the *hardware* ordering.

1. **Interaction: tap + tilt coexistence** — firmware, no hardware.
   `docs/imu-interaction-plan.md`. Blocks calling any unit givable.
2. **Wiring harness / lid-mounted unit** — conversation before code. Assemble
   outside the vessel, lower in. Shares the bottle-mouth measurement with the
   battery holder. Custom PCB for the cork/lid-mounted sensor cluster follows.
3. **Form-factor fork: bottle vs chandelier** — `docs/chandelier-concept.md`.
   A USB-powered lamp form dissolves the battery/Qi wall (see below) instead of
   engineering it away, and makes always-on sensing affordable.
4. **Battery + strip load switch** — only if the unit stays a wireless bottle.
   `docs/shopping-battery-power.md`.
5. **Provisioning manifest** — a record per physical unit.
   `docs/gift-registry.md`.
6. **NFC / sticker-book input** — 2–3 versions out, not needed for first
   givability. `docs/nfc-provisioning.md`.
7. **Stepper-hand clock branch** — independent research thread, can run in
   parallel.

Done: ~~v1.2 board portability~~ (2026-07-05), ~~v1.1 Qi power path~~
(2026-07-13; one caveat — full-brightness headroom — in `hardware.md`).
