# eki-bin — Dev Status
_Updated manually. Running log of what's done, what's next, and open decisions._

---

## Current phase: v1.1 Qi power **confirmed, self-contained in a bottle** → NFC next

> **Milestone (2026-07-13):** the whole unit — XIAO ESP32-C3 + 120-LED WS2812B-4020
> tape + unbranded Qi receiver — placed in a wide-mouth glass pitcher and run off a
> Qi pad *through the glass*, `led_test.py` driving all 120 LEDs. First time the
> full "MCU + lights inside, powered wirelessly, no visible wire" concept ran
> self-contained. The core v1.1 hardware thesis is proven. Bring-up details +
> the one open caveat (full-brightness power headroom untested) in
> `docs/hardware.md`. **Next: NFC** for app-free settings/station provisioning.

V1 is a stable freeze point: full `time → LeaveSignal → DisplayContract → LEDs`
pipeline, five display contracts, the animation/smoothing stack (gamma + dither +
seamless clock), ~19 config knobs, and a host test suite guarding it. Remaining V1
work is **tuning and in-jar validation**, not features.

**v1.2 — passed (2026-07-05)**: the XIAO ESP32-C3 runs the exact same firmware
as the Pico 2W — `config.py` swap only (`LED_PIN=2`, `HEARTBEAT_PIN=None`), zero
`main.py` changes beyond the already-landed board-abstraction knobs. WiFi
connect, NTP sync, and the full display pipeline (`BreathingInverseContract`,
schedule loading, urgency classification) all confirmed working. Board swap
took under an hour, start to finish — the firmware's board-agnostic design held
up under real hardware, not just in theory. Chip + lights now both physically
fit inside the bottle (unsoldered) — the mechanical core of v1.1, proven ahead
of the Qi coil arriving. Full writeup: `docs/roadmap.md`; pin mapping:
`pinouts/xiao_esp32c3.md`.

---

## V1 — MicroPython on Pico 2W

### ✅ Done

- [x] MicroPython v1.28.0 flashed via picotool
- [x] WiFi connection + NTP time sync working
- [x] Schedule loaded from `schedule.json` on device filesystem
- [x] Weekday/weekend detection (UTC→JST day boundary handled correctly)
- [x] Urgency logic: `time_to_leave` → `classify` → `Urgency` (superseded the
      original DIM BLUE / GREEN / AMBER / RED string model)
- [x] Console output: heartbeat ●/○, timestamp, period, next 3 departures per direction
- [x] `config.py` / `config.example.py` split (creds gitignored)
- [x] Schedule pipeline: YAML (human) → `convert_schedule.py` → JSON (device)
- [x] Makefile: `setup`, `flash-micropython`, `schedule`, `led-test`, `test`, `upload`, `run`, `screen`
- [x] `make screen` with device auto-select / interactive picker (bash 3.2 compatible)
- [x] Contracts documented: `schedule-json.md`, `config.md`, `display-contract.md`
- [x] `CLAUDE.md` written for Claude Code handoff (Rust phase)
- [x] Hardware memo: `docs/hardware.md`

### ✅ LED integration (Steps 1–2 done; Step 3 in-jar tuning ongoing)

**Step 1: Hello world blink (AE-WS2812B-STICK8)** ✓
- [x] Wire stick to Pico 2W: VBUS→VCC, GND→GND, GP6→DIN
- [x] Verify 3.3V signal drives stick reliably — works on breadboard
- [x] `micropython/led_test.py` — colour cycle + fading chase; `make led-test`

**Step 2: Integrate LED output into main.py** (architecture in `docs/contracts/display-contract.md`)
- [x] Two-stage pipeline: `time → LeaveSignal → DisplayContract → LEDs`
- [x] Stage 1: `time_to_leave` (subtract `WALK_TO_STATION_MINS`, drop uncatchable)
      → `classify` → `Urgency` → `LeaveSignal` (pure, host-tested)
- [x] Stage 2: `DisplayContract` strategy + working `SandTimerContract` (shrinking
      arc, colour by urgency); update/render split via `frame_ms` + `phase_ms`
- [x] Night gate: quiet hours (configurable; default 23:00–06:00, no LDR yet)
- [x] Lift tuning to `config.py` via `getattr` defaults: brightness, walk time,
      `URGENCY_THRESHOLDS`, `MINUTES_PER_LED`, `COLOR_SCHEME`, `CONTRACT`,
      `LED_PIN`/`NUM_LEDS`, quiet hours (back-compatible — old config.py still works)
- [x] Color schemes: `default` / `sunset` / `mono` selectable from config
- [x] `ARC_ORIGIN` flag + `_physical()` HAL seam — flips the arc for an
      upside-down strip without touching contracts (verified near→[0,1,2], far→[5,6,7])
- [x] Animation primitives complete (phase/shape, envelopes, colour helpers,
      `gamma`) — pure + host-tested; see layering diagram in `docs/contracts/display-contract.md`
- [x] Five contracts: `sandtimer`, `color`, `breathing` (+ `_exponent` / `_inverse`)
- [x] Smoothing stack: `gamma()` (perceptual curve) + temporal dithering (`DITHER`,
      sigma-delta in `_paint`) for low-end banding — both config-driven + tested
- [x] Seamless breath: envelope phase driven by the **absolute** `ticks_ms()` clock,
      so it no longer snaps back to the floor each `LOOP_INTERVAL_SECS`
- [x] All display tuning is config-driven (~19 knobs): `FRAME_MS`, `GAMMA`,
      `BREATHE_PERIOD_MS`/`_FLOOR`, `DITHER`, palette, thresholds, arc geometry…

_Remaining V1 (polish, not blocking a freeze):_
- [ ] Tune `URGENCY_THRESHOLDS` / brightness / scheme in the brown jar (ongoing)
- [x] ~~Two-train contract~~ — see **v1.3** below

**Step 3: Validate in-jar (pre-solder)** — ongoing (findings in `docs/insights.md` §3, §5)
- [x] Pico + stick placed in jar via ~10cm jumpers; brown jar = V1 reference
- [x] Diffusion / colour UX assessed across clear / medium / thick jars
- [ ] Dial in brightness + contract + scheme for the brown jar (live tuning)
- [ ] Flip `ARC_ORIGIN` once mounting is decided (strip currently hangs upside-down)

---

## V1.2 — Board Portability Checkpoint ✅ PASSED (2026-07-05)

Full scope + exit criteria: `docs/roadmap.md`. Pin mapping: `pinouts/`.

- [x] `HEARTBEAT_PIN` config knob — `Pin("LED")` was Pico-2W-only (CYW43 alias);
      now board-configurable (GPIO number or `None`), console heartbeat unaffected
- [x] `pinouts/` directory created — `pico2w.md` and `xiao_esp32c3.md`,
      **both ✅ verified** against physical silkscreen (5V/GND/3V3/D10–D7 on the
      XIAO's right side, D0–D6 on the left — read clockwise from top-right)
- [x] USB-serial enumeration widened — `scripts/detect_port.sh` (shared by
      `make screen` and the new `make flash-esp32-c3`) globs `usbmodem*` +
      three common ESP32 USB-serial bridge prefixes, not just `usbmodem*`
- [x] `make flash-esp32-c3` — esptool-based flash target for the XIAO (the Pico
      target stays picotool-based; `esptool` added to `requirements.txt`).
      Firmware in hand: a "preview" build (expected — no stable release yet)
- [x] Flashed MicroPython, wired per `pinouts/xiao_esp32c3.md`, `make led-test`
      confirmed the stick lights up on D0/GPIO2 (after fixing `led_test.py`'s
      hardcoded `DATA_PIN` — it's a standalone bring-up script, deliberately
      not config-driven; a one-line manual edit per board, by design)
- [x] Caught a real footgun: `HEARTBEAT_PIN = "none"` (quoted string, not
      Python's `None`) is truthy → `main()` would try `Pin("none", ...)` and
      fail. Added `test_heartbeat_pin_not_a_null_like_string` to
      `tests/test_real_config.py` — runs before every `make upload`
- [x] `make upload` + `make run`: WiFi connected, NTP synced, full pipeline
      confirmed live (`BreathingInverseContract`, schedule loading, urgency
      classification `LEVEL 3` for `leave in [6.5, 9.5] min` — all correct)

**Exit criteria met.** Zero `main.py` changes beyond the board-abstraction knobs
landed during this checkpoint (`LED_PIN`, `HEARTBEAT_PIN`, `_heartbeat_pin()`,
the widened USB glob) — everything else (Stage 1/2 logic, WiFi/NTP, NeoPixel)
ported unchanged. Board swap, start to finish: under an hour.

**Deferred, non-blocking** (optional polish, not required for v1.1):
- [ ] Confirm/correct onboard-LED GPIO for XIAO C3 (not among the 14 broken-out
      pins found on the silkscreen — `HEARTBEAT_PIN = None` is a perfectly fine
      permanent choice for this board, not just a placeholder)

**Next**: v1.1 proper — Qi coil (in transit) + reverse-diode + soldering the
XIAO/stick into the bottle permanently. See `docs/roadmap.md`.

---

## V1.3 — Multiple upcoming trains (firmware feature, no hardware)

Motivated by a live UX pain point, not a nice-to-have: *"OK I won't make this
next one, but what's the one after?"* Built while waiting on the Qi coil.

- [x] `N_TRAINS` config (default `1` — original single-arc behaviour unchanged)
      + `BACKGROUND_BRIGHTNESS` (geometric brightness falloff per train index)
- [x] `_paint_layers(layers)` — new paradigm-independent compositing primitive;
      `_paint` is now a single-layer convenience call into it. Zero changes to
      Stage 1 (`LeaveSignal.ttls` was already a plain list — designed for this)
- [x] Nested-band rendering: further-out trains extend a dimmer band beyond the
      primary's arc (not separate/competing arcs — later trains always have
      equal-or-longer arcs, so nesting is the natural composite). Same colour
      across layers, per spec
- [x] Wired into `SandTimerContract` and `BreathingContract` (+ its exponent/
      inverse variants, via inheritance); `ColorContract` deliberately left
      alone — no arc/length axis to layer a 2nd train onto
- [x] Compositing is overlap-safe: verified the primary wins even when two
      trains round to the *same* arc length (a real edge case, not just the
      common monotonically-nested case)
- [x] 7 new tests in `tests/test_multi_train.py` (falloff math, nested bands,
      equal-extent overlap, `N_TRAINS=1` regression, short-`ttls` no-crash,
      `ColorContract` correctly ignores it, breathing × layer-falloff composition)
- [x] `docs/contracts/display-contract.md` given a proper pass while in there —
      several stale references fixed (old primitive names, "stub" labels on
      long-finished contracts, a leftover duplicated section, an outdated
      tuning-knobs table missing half the real knobs)

**Paradigm-independence, the actual design question**: every layer is a
`(color, lit, mult)` tuple flowing through the *same* `_physical()` seam a
single-train render already used — a ring or a randomized "cosmos" layout would
only ever need to change `_physical()`, never this compositing logic. See
`docs/contracts/display-contract.md` § Multiple trains.

**Field-testing finding (see `docs/insights.md` §6)**: brightness-only
differentiation (`BACKGROUND_BRIGHTNESS`) didn't hold up on real hardware —
flicker at low dithered brightness + visible LED die instead of ambient glow,
confirmed with both static and animated contracts. Resolved by building a new
differentiation axis:

- [x] `hue_rotate(color, degrees)` — new colour primitive (proper HSV
      round-trip), preserves saturation/brightness, only shifts hue
- [x] `ceiling` param added to all envelope functions (`breathe*`, `blink`,
      `pulse`) — caps how bright a layer's peak can get, defaulting to `1.0`
      (fully backward-compatible)
- [x] `micropython/led_sandbox.py` — new general-purpose tool, `import main`s
      the real primitives for fast side-by-side A/B comparisons on real
      hardware without WiFi/schedule/the full loop
- [x] **`EchoContract`** (`CONTRACT = "echo"`) — primary static/full brightness,
      trains beyond it hue-shifted + gently breathing near-full brightness.
      Genuinely new per-layer render logic (not expressible via the existing
      uniform-per-layer modifier), composing existing primitives
      (`_arc_len`, `breathe`, `hue_rotate`) rather than duplicating them
- [x] New config: `SECONDARY_HUE_SHIFT_DEG` (20), `SECONDARY_BREATHE_PERIOD_MS`
      (3000), `SECONDARY_BREATHE_FLOOR` (0.7) — kept separate from
      `BreathingContract`'s own `BREATHE_*` knobs on purpose
- [x] 6 new tests in `tests/test_echo_contract.py` + 6 more for `hue_rotate`/
      `ceiling` in `test_primitives.py` (50 total, all passing)

---

## V1.5 — Round PCB LED ring (still MicroPython)

- [ ] Solder OSTW3535C1A SMD chips onto AE-27mm-TH round PCB in ring formation
- [ ] Test 3.3V IO tolerance on OSTW3535C1A (spec min 3.5V — may need level shifter)
  - If needed: 74AHCT125 buffer, 3.3V→5V, ~¥50 at Akizuki
- [ ] Same GP6 data line — NeoPixel chain just gets longer
- [ ] Fit round PCB into jar, secure with cork or mounting hardware

---

> **Hardware roadmap** (v1.1 Qi/XIAO build, form-factor threads, standalone/NFC
> power research, clock-paradigm notes): see `docs/roadmap.md`.

---

## V2 — Rust (Embassy) on Pico 2W or ESP32-C3

> Prerequisite: V1 hardware validated, all LED behaviours confirmed in MicroPython.
> Migrate to Rust as a learning exercise. See `CLAUDE.md` for teaching directive.

### Firmware rewrite targets

- [ ] Embassy project scaffolding (`rust/` directory, `Cargo.toml`, `.cargo/config.toml`)
- [ ] Blink onboard LED in Embassy (hello world)
- [ ] WS2812B output via PIO (RP2350 has PIO; better than bit-banging)
- [ ] Replace WiFi+NTP with DS3231 RTC over I2C
- [ ] Deep sleep between updates (30s → `Timer::after` in Embassy)
- [ ] Schedule as `const` arrays compiled in from JSON via `build.rs`
- [ ] NFC (PN532) for schedule card reads and time sync taps
- [ ] Magnetometer (QMC5883L) for orientation/mode selection
- [ ] E-ink display (Waveshare 2.9") for departure time label

### MCU decision (open)
| Option | Pro | Con |
|---|---|---|
| Stay on Pico 2W (RP2350) | Already have it; Embassy RP2350 support mature; PIO for WS2812B | WiFi chip different from final V2 concept |
| Move to ESP32-C3 | Matches final design doc; smaller | Embassy ESP32 support less mature; no PIO |

**Tentative:** stay on Pico 2W for V2 Rust learning; migrate hardware later if needed.

---

## Open decisions

| Decision | Status | Notes |
|---|---|---|
| Level shifter for OSTW3535C1A | ⏳ test first | 3.3V may work in practice |
| Jar form factor | ⏳ leaning thick+coloured | Brown jar = V1 reference; clear/medium read badly (see `docs/insights.md` §3) |
| Cork vs screw cap | 🔲 open | Cork aesthetic; screw cap practical for access during dev |
| LED direction / HAL abstraction | 🔲 open | Logical arc origin + reverse; full `led_drivers/` HAL deferred to ring arrival (`docs/insights.md` §4) |
| Multi-train modality | 🔲 open | Spare LEDs show 2nd-closest train; data already in `LeaveSignal.ttls` |
| Qi WCR viability | ✅ confirmed (2026-07-13) | Bare unbranded receiver, no FOD rejection on Belkin pad, works through glass, drives 120 LEDs. See `docs/hardware.md` bring-up log |
| WCR power at full brightness | 🔲 new open | Only tested at `BRIGHTNESS=0.15`. 800 mA WCR ceiling vs. full-white 120-LED draw (~40 mA/LED) not yet stress-tested — needs a higher-brightness follow-up |
| LED tape mid-cut connector handling | 🔲 deferred | Until a soldering iron is in hand; factory pigtail + jumper-pin-in-innie trick is sufficient for bring-up (`docs/hardware.md`) |
| MCU for V2 | ⏳ tentatively Pico 2W | See above. ESP32-C3 now in hand for v1.1/v1.2 (MicroPython) — real board-portability data from that checkpoint may inform this, though V2 Rust/Embassy support maturity is the separate deciding factor |
| E-ink source in Japan | 🔲 open | Waveshare 2.9" on Amazon.co.jp; flex version TBD |
| Station card storage | 🔲 open | Dish / card holder / pinned to noticeboard |

---

## Known issues / notes

- `OSTW3535C1A` IO voltage min is 3.5V; Pico outputs 3.3V. Test before assuming compatibility.
- WiFi creds in `config.py`: gitignored plaintext, edited by hand (or on-board via Thonny). Encrypted/vault storage tabled for V1 — acceptable for a single-user device with no secure enclave.
- Schedule JSON is gitignored (generated from YAML). CI would need to run `make schedule` first.
- No soldering iron yet — V1 hardware is breadboard-only until that changes.
- **Quiet hours gotcha:** after `QUIET_START_HOUR` (default 23:00) the strip is dark by design — looks identical to a bug. The loop now prints `(quiet hours — display off)`; to test at night set `QUIET_START_HOUR=24, QUIET_END_HOUR=0`. Regression-tested in `tests/test_quiet_hours.py`.
- Host test suite in `tests/` (`make test`, runs before `make upload`). Covers Stage 1, render geometry, primitives, quiet hours, and validates the real `config.py` selectors. Physical/brightness/diffusion behaviour is **not** unit-testable — that stays a hardware judgement call.
- LED strip hangs **upside-down** inside the jar (jumpers from breadboard) — fine for testing, needs the LED-direction abstraction before a real unit.
- REPL poking via `make screen` lands in a fresh namespace; use `import main` (not bare names). `main.py` is the boot script so it auto-runs the loop — consider a `scratch.py` for visual iteration.
