# eki-bin — Roadmap / Hardware Handoff

_Living roadmap from a planning session (2026-06-29). Captures form-factor
philosophy, the immediate v1.1 build, and the harder standalone/clock research
threads. Complements `dev-status.md` (near-term what/next) and `docs/concept.md`
(the "why"). Not a commitment to a single linear path — see below._

---

## Current State

- **v1 architecture**: Pico 2 W (MicroPython) on breadboard, sitting outside the
  bottle on a shelf, connected via jumper wires to an AE-WS2812B-STICK8 LED strip
  inside the bottle. WiFi + NTP for time sync.
- **Working now**: schedule loading, urgency classification (`LeaveSignal`),
  display-contract pipeline, config-driven tuning, colour schemes, quiet hours,
  animation primitives (breathing, gamma) + host test suite.
- **Verdict on v1 as-is**: genuinely fine to keep running as the dev/proof-of-
  concept rig. "MCU outside, only lights inside" is a legitimate way to keep the
  dev loop fast — sequencing the constraints, not cheating them.

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

## Immediate Next Step: v1.1 (Qi-powered, in-bottle, WiFi retained)

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

**Goal**: prove the firmware runs identically on the XIAO ESP32-C3 *before* the
Qi power-path work lands, so integrating Qi isn't also a first-time board
bring-up. Scoped narrowly on purpose — if something breaks during v1.2, it's
unambiguously a board/firmware issue, not tangled with power changes.

**Result**: passed, start to finish in under an hour. `make upload` + `make run`
on the XIAO — same `main.py`, `config.py` swap only (`LED_PIN=2`,
`HEARTBEAT_PIN=None`) — connected to WiFi, synced NTP, and ran the full
`time → LeaveSignal → DisplayContract → LEDs` pipeline correctly
(`BreathingInverseContract`, `LEVEL 3` urgency for a real schedule, correct ring
direction). Two real bugs surfaced and got fixed along the way (see below) —
neither was a firmware-logic problem, both were config/tooling gaps, exactly as
the narrow scoping was meant to isolate. Chip + LED stick now both physically
fit inside the bottle (unsoldered) — the mechanical core of v1.1, proven ahead
of the Qi coil's arrival.

- **Same rig, board swap only**: same breadboard, same LED stick, swap
  Pico 2W ↔ XIAO C3, swap only `config.py`. Confirm WiFi connect, NTP sync, and
  visual output via the active `DisplayContract` are indistinguishable.
- **Explicitly out of scope**: Qi coil, diode, second LED strip — anything
  power-path. That's v1.1 proper, after this checkpoint passes.
- **Mechanical approach**: no soldering yet — spring-loaded test clips / pogo-pin
  grabbers on the XIAO's castellated pads, reversible. A second XIAO C3 as a
  sacrificial dev unit is cheap insurance if clip leads prove fiddly enough that
  soldering starts to look necessary.
- **Structure**: one shared `main.py` (unchanged), one `config.py` per board
  swapped in by hand at upload time — **not** a `boards/` directory, and `upload`
  /`run`/`screen`/`led-test` stay untouched (they go through `mpremote`, which is
  already board-agnostic). The one genuinely new Makefile target is
  `flash-esp32-c3` — firmware flashing is the one step that *is* board-specific
  (ESP32 uses a serial bootloader via `esptool`; the Pico uses `picotool` +
  mass-storage `.uf2`), so it gets an explicit second target rather than an
  auto-detecting one. This is a temporary two-board swap to *retire* the Pico rig
  once the XIAO is validated, not an ongoing multi-rig setup; a `boards/`
  directory is worth building only if a third board or a genuinely different
  display type shows up and ≥2 rigs need to stay alive long-term (same reasoning
  as deferring the LED `led_drivers/` HAL until the ring hardware actually
  arrives — see `docs/insights.md` §4).
- **Two things likely to surprise you, neither a firmware bug**:
  - ~~`scripts/select_port.sh` only globs `/dev/cu.usbmodem*`~~ — **fixed**:
    port detection now lives in `scripts/detect_port.sh` (shared with
    `flash-esp32-c3`), globbing `usbmodem*`, `wchusbserial*`, `SLAB_USBtoUART*`,
    and `usbserial*`. Still worth an `ls /dev/cu.*` with the board plugged in to
    confirm which prefix it actually uses.
  - WS2812B timing is port-specific under the hood (RP2 uses PIO; ESP32 typically
    uses RMT) — same `neopixel` API, different signal-generation backend. **Turned
    out to be a non-issue**: the stick lit up correctly on GPIO2 on the first try,
    even on a "preview" (non-stable) firmware build — no colour/timing glitches.
  - `micropython/led_test.py` is **not** config-driven (`DATA_PIN` is a hardcoded
    module constant) — **this one did bite**: `make led-test` "succeeded" with no
    error while silently driving the wrong physical pin (`DATA_PIN` was still `6`,
    which is D4/SDA on the XIAO, not the D0/GPIO2 wired to DIN). No LEDs, no
    error message — the giveaway was that identical, unmodified code "worked" on
    the Pico only because `6` happened to coincide with its real wiring. Fix:
    hand-edit `DATA_PIN` per board — deliberately not made config-driven, since
    this is a one-off bring-up script, not part of the pipeline.

**A second bug, not predicted in advance**: `HEARTBEAT_PIN = "none"` (a quoted
string) is truthy, so `main()` tried `Pin("none", Pin.OUT)` instead of treating
it as Python's `None`. Caught by `tests/test_heartbeat_pin_not_a_null_like_string`
in `tests/test_real_config.py`, which now runs before every `make upload`.

**Exit criteria — met**: XIAO C3, its own `config.py`, zero `main.py` changes
beyond the board-abstraction knobs that landed during this checkpoint
(`LED_PIN`, `HEARTBEAT_PIN`, `_heartbeat_pin()`, widened USB-serial glob),
connected to WiFi, synced NTP, and rendered the active `DisplayContract`
indistinguishably from the Pico 2W. Ready to receive the Qi coil and move into
v1.1's power-path integration without a board-bring-up variable in the mix.

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
time once — both **without an app.**

> **⚠ Superseded (2026-07).** The "no custom app, iOS Shortcuts" resolution below
> was **ruled out on the bench**: iOS's generic NDEF API breaks on the ISO-15693 /
> Type-5 ST25DV tag, and Shortcuts has no NDEF content read/write action anyway.
> Current plan is a **minimal first-party iOS app** on the low-level ISO-15693 API.
> See **`docs/nfc-provisioning.md`** for findings + decision. The reasoning below is
> kept as the record of what was tried and why it didn't pan out.

**Resolution direction (tried — did not pan out, see banner above)**:
- **iOS Shortcuts has a built-in "Set NFC Tag" action** — writes plain text/URL
  NDEF natively, no third-party app. Plausibly covers:
  1. **Station data transfer** — high confidence, standard use.
  2. **Time sync** — same action writing a Unix timestamp. *Lower confidence*:
     needs the *jar* to present as a writable NFC target (tag-emulation on the
     reader chip). **Flagged as the one thing to test early on real hardware.**
  3. **Direct settings editing** (brightness, pattern — currently `config.py`) —
     one Shortcut branching to JSON payloads tagged by a `type` field.
- **Android**: Web NFC — a browser API, tap-to-write from a page, no install.
- **Ideal omiyage flow**: *"Here's the bottle, and this Shortcuts file if you want
  to change settings — tap the time one once a year."* No app/account/dev env.
- **Softer fallback**: giver pre-loads station cards before gifting (like a
  preloaded gift card); recipient never writes a tag. Given <1 min/yr drift, time
  correction may not need solving within a gift's lifespan.

**Next concrete step** (~~no-app Shortcuts crux~~ — resolved, see banner): the
provisioning path is settled → build the minimal iOS app (`docs/nfc-provisioning.md`).
The LPCD-reader / battery-standalone research (CLRC663 plus, ST25R391x) remains a
*separate, later* variant — it was about a passively-powered reader for the
fully-encapsulated build, distinct from the ST25DV dynamic tag used now.

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

1. ~~**v1.2 board-portability checkpoint**~~ — ✅ **passed 2026-07-05.**
2. ~~**v1.1 Qi power path**~~ — ✅ **confirmed 2026-07-13**: XIAO + 120-LED tape +
   Qi receiver ran self-contained in a glass pitcher off the pad. One caveat
   (full-brightness power headroom — 0.15 ceiling) logged in `docs/hardware.md`.
3. **NFC provisioning**: bench pass done — no-app/Shortcuts route ruled out,
   decision is a minimal first-party iOS app on the low-level ISO-15693 API.
   Next: build the app + the ST25DV I²C driver. See `docs/nfc-provisioning.md`.
4. Prototype the stepper-hand clock branch — independent, can run in parallel.
5. Custom PCB for the cork-mounted sensor cluster — later, once Qi/NFC validated.
