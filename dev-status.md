# eki-bin — Dev Status
_Updated manually. Running log of what's done, what's next, and open decisions._

---

## Current phase: gesture envelope (branch `feature/gesture-envelope`, not yet pushed)

> **Supersedes the wake/sleep interaction layer below** — same sensor
> (AE-LSM6DSV16X), a redesigned interaction model. Real-hardware testing
> (many sessions, two bottles, a sandbox toolchain built specifically to
> answer "what can this hardware actually support") found the original
> multi-gesture wake-interaction design's harder pieces (position
> disambiguation, flick-vs-handling) genuinely unreliable, while tap-vs-noise
> discrimination alone was consistently strong (95-98%+). Scoped down to a
> minimal "light switch"-reliable contract instead of the fuller vocabulary —
> full rationale in `docs/contracts/gesture-envelope.md`'s "Scope pivot"
> callout and §11. IMU is now **physically wired and extensively validated**
> on the Pico 2W + AE-WS2812B-STICK8 (not the stub `wake-interaction.md`
> describes) — see the new subsection below, after "Wake/sleep interaction
> layer," for the full account. 185 tests passing. **Not yet pushed**, **not
> yet on the XIAO/full LED tape/actual bottle** (that's the next step before
> merge to `dev`).

> **Provisioning pivot (2026-07-23):** the NFC-via-custom-iOS-app plan
> (`docs/nfc-provisioning.md`) is **on hold, not active** — see Open decisions
> below. Immediate work is unrelated to provisioning: a new positional/approach
> display paradigm (`docs/contracts/approach-contract.md`) for a friend gift
> build. Concept doc has the *what/why*; this section has the *when/how*.

> **Milestone (2026-07-13):** the whole unit — XIAO ESP32-C3 + 120-LED WS2812B-4020
> tape + unbranded Qi receiver — placed in a wide-mouth glass pitcher and run off a
> Qi pad *through the glass*, `led_test.py` driving all 120 LEDs. First time the
> full "MCU + lights inside, powered wirelessly, no visible wire" concept ran
> self-contained. The core v1.1 hardware thesis is proven. Bring-up details +
> the one open caveat (full-brightness power headroom untested) in
> `docs/hardware.md`.

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

## V1.4 — ApproachContract + crossfade (friend gift build)

Concept/design reference: `docs/contracts/approach-contract.md`. This section
is the dev plan only — sequencing, hardware, config, and test order for this
specific build session(s).

**Scope note:** this is a new build for a friend gift, on a new XIAO, alongside
the new positional/approach paradigm intended to eventually replace arc-based
contracts for the "which train, how close" job. **Not in scope this pass:**
line-color palettes, IMU, NFC/any provisioning, Matter/Embedded Swift rewrite,
e-ink — later phases, don't over-engineer hooks for them beyond what naturally
falls out of clean config-driven design.

### Hardware (physical work, not firmware)

- [x] New XIAO ESP32-C3, fresh flash
- [x] WS2812B tape cut to **21 LEDs** (confirmed 1-LED-per-segment cut points —
      no rounding needed); `make led-test` confirms all 21 light. Brightness
      bench findings (0.15–0.2 = full, 0.005 = ideal floor) in `docs/hardware.md`
- [x] Mount LEDs **face-up**, not downward-facing as originally planned —
      tested both, face-up refracts/diffuses better through this bottle. Pure
      mounting decision, no `ARC_ORIGIN`/`_physical()` flip needed in code
- [ ] Direct solder to XIAO (no connector) — ~300–470Ω series resistor near
      LED #1, ~1000µF bulk cap across 5V/GND at strip start (no dev-board
      buffering on a direct-solder setup)
- [ ] Alligator-clip test **before** committing to solder, fully outside the
      bottle
- [ ] Power via USB-C throughout; Qi-into-bottle fit is a separate mechanical
      test, decoupled from firmware, **not this pass** (step 9 below)

### Firmware build order

1. [x] Alligator-clip strip to XIAO, outside bottle, home WiFi/dev `config.py`
2. [x] Sanity-check LED indexing on the new 21-LED length (`make led-test`,
       all 21 confirmed)
3. [x] `ApproachContract` phase-1 implemented on `feature/positional-display`
       (`ANCHOR_INDEX=0`, `ARM_A_LEN=20`, `ARM_B_LEN=0`) + 24 host tests, all
       passing — `docs/contracts/approach-contract.md`,
       `tests/test_approach_contract.py`. `micropython/config_friend1.py`
       created with starting tuning values. **Still needed:** validate on the
       actual device (host tests only so far)
4. [x] Iterate `FLOOR_BRIGHTNESS` / `FLOOR_COLOR` on real hardware — first pass
       found the floor **flickering with visible multicolour "sparkle"**, not
       a smooth glow: the same low-brightness dithering artifact
       `docs/insights.md` §6 already documented for `EchoContract`, now
       showing up on a constant/idle pixel instead of an animated one. Fixed
       by adding a STATIC render path (`_write_frame`, `main.py`) — no gamma,
       no dither — for pixels that don't change frame-to-frame (floor, anchor,
       a settled train position); only genuinely mid-crossfade pixels use the
       gamma+dither ANIMATED path. `FLOOR_BRIGHTNESS` is now a direct linear
       multiplier (not gamma-shaped), corrected default `0.15`. Also added
       `ANCHOR_BRIGHTNESS` (default `1.6`) so the anchor reads brighter than a
       normal "full" position, not just differently coloured — colour alone
       wasn't a strong enough cue on the real strip. See
       `docs/contracts/approach-contract.md` § Floor / idle state.

       **Second-pass finding:** retuning `FLOOR_BRIGHTNESS` down (still too
       bright at `0.10`) revealed the crossfading dot's brightness was
       coupled to it too — a single shared scalar was governing both
       "how dim is idle" and "what's the dot's fade floor," so tuning one
       moved the other. Split into fully independent knobs:
       `MARKER_BRIGHTNESS` (settled dot mult, default `1.0`) and
       `MARKER_FADE_FLOOR` (dot's own fade-envelope floor, default `0.3`) —
       `FLOOR_BRIGHTNESS` now *only* affects genuinely idle LEDs.

       **Third-pass finding, real jar (not clear bench):** the brown bottle
       shifts perceived colour noticeably (white anchor → soft orange-white,
       green train → yellow-green, gray idle ticks → yellow — "not bad,"
       logged in `docs/hardware.md`) and its added darkness means brightness
       can go *up* from the clear-air bench numbers (`BRIGHTNESS` toward
       `0.5`, `ANCHOR_BRIGHTNESS` toward `2.0`). Also: **face-up beats
       downward-facing** for this bottle — reverses the original mounting
       plan.

       **Fourth-pass: terminology rename.** A bug report ("MARKER_BRIGHTNESS
       doesn't change the other 19 markers") surfaced that the actual mental
       model in use — **anchor** = the "0"; **marker** = the idle tick LEDs
       (what code/docs had been calling "floor"); "where the train is" = just
       `BRIGHTNESS` itself, no separate knob at all — was simpler than what
       got built, and is what should have been designed from the start.
       Renamed throughout: `FLOOR_BRIGHTNESS`/`FLOOR_COLOR` →
       `MARKER_BRIGHTNESS`/`MARKER_COLOR`; the old train-dot
       `MARKER_BRIGHTNESS` knob removed entirely (train now always renders at
       `BRIGHTNESS`, `mult=1.0`); `MARKER_FADE_FLOOR` → `LINE_FADE_FLOOR`;
       `MARKER_SATURATION` → `LINE_SATURATION`. Net: three independent
       brightness surfaces (`ANCHOR_BRIGHTNESS`, `MARKER_BRIGHTNESS`,
       `BRIGHTNESS`) instead of four knobs across two confusingly-named
       concepts. Also added `LINE_SATURATION` (genuinely muted train colour,
       not just dimmer — a "few notches darker" request turned out to be
       identical to brightness under the render pipeline's linear math, so a
       real muted look needed the new `desaturate()` primitive instead —
       `docs/contracts/approach-contract.md`).
5. [x] Iterate the transition feel — found the brightness-blend crossfade
       flickering ("withering") at its low point on real hardware; replaced
       with the CHASE transition (see below) — gamma/brightness-blend no
       longer part of this contract's transition at all. `TRANSITION_MS`
       duration itself still open to live taste-tuning
6. [ ] Solder properly once satisfied (no more alligator clips)
7. [ ] New `config_friend1.py` (friend's WiFi creds + hardcoded single
       line/station) — keep separate from dev `config.py` rather than editing
       it, so home dev config stays intact when swapping creds for handoff
8. [ ] Final validation on friend's actual network before handoff
9. [ ] *(Not this pass)* Physical fit test: Qi coil in bottle vs. wired
       fallback — mechanical, independent of firmware work above

### Startup sequence ("boot ceremony") ✅ implemented, not yet on hardware

Branch: `feature/startup-sequence` (off `dev`, after `feature/positional-display`
merged). Full design: `docs/contracts/startup-sequence.md`. Resolves the open
fork in `docs/insights.md` §5 (does a boot animation break the clock
illusion?) — decided **yes, bounded and one-time**.

Three open questions from the design doc confirmed before coding:
1. No config toggle for now (V1/WiFi-era feature; add one when V2 actually
   needs it)
2. Hanabi burst flashes all LEDs together, not radiating from
   `ANCHOR_INDEX` — contract-agnostic, since no `CONTRACT` is "current" yet
   at boot
3. Failure state is a genuine dead end — persistent red breathe, no
   auto-retry, needs a physical reset

Built:

- [x] `run_startup_sequence()` — the boot ceremony entry point, called once
      at the top of `main()`, before the main loop. Not a `DisplayContract`
      (no `LeaveSignal` exists yet at boot) — standalone procedural code
- [x] `connect_wifi()` restructured: was a blocking `sleep(1)` poll loop
      with zero LED output; now polls on a `FRAME_MS` cadence, drawing one
      loading-circle frame per iteration (`_draw_startup_circle`) — same
      ~20s connect budget, now animated throughout. This was the real
      engineering risk the design doc flagged; the animation math itself
      was nothing new
- [x] **Revised the "crossfade into the live contract" handoff mid-build:**
      the original plan blended the burst's fade-out directly into
      `ACTIVE_CONTRACT`'s render — but that's exactly the brightness/colour
      blend pattern that caused CHASE's dithering flicker on
      `feature/positional-display`. Re-introducing it here, right after
      fixing it there, would be a regression. Burst now decays to black on
      its own; the main loop's first real frame follows immediately after,
      no explicit crossfade logic
- [x] `_play_startup_burst()` — success burst, all LEDs together, ANIMATED
      render path (genuinely changing every frame, so dithering is
      appropriate — unlike an idle/settled pixel)
- [x] `_run_startup_failure_forever()` — persistent red breathe, own
      `ERROR_BREATHE_PERIOD_MS` (not `BREATHE_PERIOD_MS`), never returns
- [x] `main()`'s `try/except KeyboardInterrupt` widened to wrap
      `run_startup_sequence()` too, so Ctrl+C during REPL testing of the
      boot ceremony (including the failure state) still exits cleanly
- [x] 14 new tests (`tests/test_startup_sequence.py`) — all the pure math
      (circle position, burst rise/decay curve, error breathe) is
      host-tested; the real-time loops (`connect_wifi()`'s poll,
      `_play_startup_burst()`, `_run_startup_failure_forever()`) are not,
      same limitation `render_for_interval`'s frame loop already has. 109
      tests total, all passing
- [ ] **Not yet validated on real hardware** — nothing here has run on the
      actual device yet; `STARTUP_BURST_MS`/`STARTUP_FADE_MS`/
      `STARTUP_SPIN_HZ` are all untested guesses, tune live

### Phase 2 — bidirectional (iteration 1: one train per arm) ✅ implemented

`ANCHOR_INDEX`/`ARM_A_LEN`/`ARM_B_LEN` index math was genuinely config-only
as promised. What wasn't: *which signals feed the two arms* — a real
structural addition, not just numbers. Built:

- [x] `DISPLAY_DIRECTION_B` config (a 2nd `schedule.json` direction key,
      feeding arm B; `None` default = phase 1 unchanged)
- [x] `_ArmState` — crossfade state factored out of `ApproachContract`
      itself; the contract now always holds two (`_arm_a`, `_arm_b`)
- [x] `_advance_arm()` — the crossfade math, now in one place, called once
      per arm by both `render()` (phase 1, unchanged) and the new
      `render_dual(signal_a, signal_b, phase_ms)` (phase 2)
- [x] `_render_dispatch()` in `main.py` — picks `render` vs `render_dual`
      (`signal_b is not None and hasattr(contract, "render_dual")`); every
      other contract and phase-1 configs completely unaffected
- [x] No index-collision handling needed — arm A/B occupy disjoint ranges by
      construction (`_arm_target`); only the anchor can coincide, and it's
      always painted last
- [x] Uneven `NUM_LEDS` (no clean centre): confirmed **not** a code problem —
      `ANCHOR_INDEX`/arm lengths are independent knobs already; recommended
      letting arms differ by 1 LED rather than building a wide-anchor mode
- [x] 9 new tests (`tests/test_approach_dual.py`) — both arms land correctly,
      independent crossfade timing (one arm's transition doesn't perturb the
      other's), only-primary-per-arm scope, anchor priority/no-collision,
      dispatch logic. 88 tests total, all passing
- [x] **Validated on real hardware** — bidirectional confirmed working
- [x] Iteration 2: N trains per arm — see below

### CHASE transition — replaced the brightness-blend crossfade ✅ implemented

Real-hardware bring-up on bidirectional found the transition's low point
"withering" — the same low-brightness dithering flicker the marker ticks and
`EchoContract`'s secondary layer had already hit, now on a genuinely
*animated* pixel (so it couldn't be fixed by rendering it STATIC — that
would freeze the fade, not smooth it). Discussed four+ alternative
transition paradigms that avoid dipping into low brightness at all (colour
change, hard-cut overlap, "bounce" overshoot, chase/sweep) and built
**chase**: a moving highlight sweeps LED-by-LED from the old position to the
new one, always at full brightness — never a dim intermediate value, so
dithering is never *needed* during a transition, not just tuned to be less
visible.

- [x] `_ArmState` reworked: `active_index`/`active_color`/`fading_index`/
      `fading_color` → `index`/`color`/`sweep_from`
- [x] `_advance_arm()` rewritten: one-LED hops (the common case) are a single
      sharp switch at the transition's midpoint; multi-LED hops sweep
      through every intermediate LED, each getting an equal time-slice —
      reuses the sequential-sweep idea `led_test.py`'s bring-up `chase()`
      already proved on this hardware. Appearing-from-nothing/vanishing-to-
      nothing snap instead of sweeping (no second endpoint to animate
      toward)
- [x] `LINE_FADE_FLOOR` config **removed entirely** — dead knob once no
      pixel is ever dim during a transition
- [x] `gamma()`/`lerp_color()` no longer used by `ApproachContract` at all
      (still used elsewhere — `BreathingContract` etc. — untouched)
- [x] Tests rewritten for the new behaviour (sharp midpoint switch,
      multi-LED sweep sequencing, snap-on-appear/vanish, and a direct
      invariant test: every rendered pixel is always exactly full brightness
      or the marker baseline, never anything in between). 90 tests total,
      all passing
- [ ] Live on-hardware tuning of `TRANSITION_MS` for the chase feel (bounce/
      overlap variants explicitly not built this pass — chase alone, per the
      2026-07-23 discussion)

### N trains per arm (iteration 2) ✅ implemented

Reused `N_TRAINS` (the same knob `sandtimer`/`breathing*` already use) rather
than a new dedicated knob — each arm now holds a LIST of `N_TRAINS`
`_TrainState`s (renamed from `_ArmState`, one instance per train slot rather
than per arm) instead of one, so every simultaneous marker gets its own
independent CHASE transition. Default `1` keeps every prior behaviour
byte-identical.

- [x] `_TrainState` (renamed `_ArmState`) + `_advance_train` (renamed
      `_advance_arm`, unchanged logic, now operates on one slot rather than
      implicitly "the" arm)
- [x] New `_advance_arm(frame, slots, signal, arm_len, direction,
      base_color, phase_ms)` maps `signal.ttls[:N_TRAINS]` onto slots
      soonest-first and advances/paints each
- [x] Secondary trains differentiate by **hue** (`_layer_hue_shift`,
      `SECONDARY_HUE_SHIFT_DEG` — same knob/formula `EchoContract` already
      uses), never brightness — dimming a slot would silently undo the whole
      point of the CHASE transition (every train always full brightness).
      Direct continuation of the `docs/insights.md` §6 lesson
- [x] Index collisions between slots resolve like `_paint_layers` already
      does: slots painted in reverse order, slot 0 (primary) painted last,
      wins any overlap
- [x] Composes with bidirectional unchanged — both arms independently get
      their own `N_TRAINS` slots
- [x] Documented as an accepted simplification: no cross-tick train
      identity (Stage 1 is ephemeral by design) — "slot 0" means "whichever
      train is currently closest," so a rank shift when the primary departs
      can look like slot 0 jumping to the former slot 1's position. Revisit
      only if it reads as jarring on real hardware
- [x] 5 new tests (single-direction: multiple simultaneous markers, primary
      unshifted/secondaries hue-shifted at full brightness, collision
      tie-break, independent per-slot chase state) + 1 dual-arm test. 95
      tests total, all passing
- [ ] **Not yet validated on real hardware** — host tests only so far

### Wake/sleep interaction layer (IMU tap gestures) — superseded, see below

⚠ **Superseded by the "Gesture envelope" section immediately below.** Kept
here as history, not deleted — the state-machine/safety-gate patterns
(`WAKE_INTERACTION_ENABLED`-style opt-in gating, cooperative-loop
concurrency) carried forward correctly into the new design; what changed
is the *gesture vocabulary* itself, after real hardware showed the
multi-gesture plan below was more than this sensor could reliably support.

Branch: `feature/wake-interaction-layer` (not pushed, per instruction).
Full design: `docs/contracts/wake-interaction.md`. Not the simple "tap
extends the timer" idea first floated — that turned out to be too simple on
reflection (a tap while awake needs to do something *else*, and extending
needs its own gesture plus a confirmation cue, or a missed extend is
indistinguishable from a registered one).

- **Sensor picked:** AE-LSM6DSV16X (Akizuki g130950) — the breakout board,
  not the bare LGA14L chip (g130032, same sensor, not hand-solderable).
  I2C on D4/SDA (GPIO6) + D5/SCL (GPIO7), same bus already earmarked for a
  future DS3231 RTC. Only GND is shared with the LED strip's wiring —
  bundled into one solder joint, no contention with SDA/SCL/3V3
- **Two states:** AWAKE (countdown running, contract renders normally) and
  ASLEEP (all LEDs off). Boot always enters AWAKE — placing the jar on a Qi
  pad *is* an intentional wake trigger, same logic as a deliberate tap
- **State-dependent gestures:** ASLEEP + any tap → wake (replays
  `_play_startup_burst()` as-is). AWAKE + single tap → `_run_secondary_action()`
  (default: `_cycle_brightness()` through `BRIGHTNESS_PRESETS`). AWAKE +
  double tap → extend the countdown + a confirmation overlay
- **Real, named cost:** distinguishing single vs. double tap needs a
  `DOUBLE_TAP_WINDOW_MS` disambiguation window, so a single tap can't fire
  until that window elapses — trades away the ~50ms "instant" feel a
  bare single-gesture design would have had, in exchange for two gestures
  on one sensor
- **Concurrency:** confirmed no RTOS/threading needed — implemented as
  `_run_interactive_loop()`, a cooperative super-loop (one `FRAME_MS` tick,
  several elapsed-time-gated tasks). XIAO ESP32-C3 is single-core anyway, so
  an RTOS would only be time-slicing one core, same real-world result
- **Safety gate added during implementation, not in the original design:**
  `WAKE_INTERACTION_ENABLED` (default `False`). With `_imu_tap_detected()`
  still stubbed (always `False` — no IMU wired), enabling this
  unconditionally would leave the display permanently ASLEEP after
  `WAKE_MINUTES` with no way to wake it again — a real regression for
  `config_friend1.py` and any other IMU-less deployment. `main()` now
  branches: `False` runs `_run_classic_loop()` (the *original* loop, moved
  but byte-for-byte unchanged); `True` runs the new
  `_run_interactive_loop()`. Every existing deployment is unaffected by
  default
- [x] `_TapClassifier`, `_WakeState`, `_StatusMessage`, `_classify_wake_response`,
      `_all_signals_hidden`, `_cycle_brightness`/`_run_secondary_action` — all
      pure, all host-tested (27 tests, `tests/test_wake_interaction.py`)
- [x] **Deviation from the original doc:** the extend confirmation was
      specified as an ANIMATED `pulse()`/`breathe()`; implemented instead as
      the same non-blocking `_StatusMessage` overlay the two new status
      messages use (one shared mechanism, and a blocking animated pulse
      would stall tap classification for its duration)
- [ ] **Not yet on real hardware** — no IMU physically wired;
      `TAP_THRESHOLD`/`DOUBLE_TAP_WINDOW_MS` are untested guesses pending a
      real sensor
- [ ] **Not pushed to `dev`/`main`** — kept local per instruction

### Gesture envelope (IMU tap gestures, v2) ✅ implemented, extensively real-hardware validated, not yet pushed

Branch: `feature/gesture-envelope` (not pushed). Full design + the complete
real-hardware iteration log: `docs/contracts/gesture-envelope.md` (§11
specifically covers everything below in full detail — this is the
proportionate summary). Field-note synthesis: `docs/insights.md` §8-9.

**The sensor is now really wired**, not the stub the section above
describes — AE-LSM6DSV16X on the Pico 2W (`pinouts/pico2w.md`, now
✅ Verified, combined IMU+LED wiring documented with an explicit
3.3V/5V power-rail safety note). A purpose-built sandbox toolchain
(`micropython/vibration_sandbox.py`, `imu_test.py`, `handling_test.py`,
`orientation_test.py`, plus host-side `scripts/analyze_taps.py` /
`prepare_tap_dataset.py` / `train_tap_classifier.py`) ran across many
sessions and two bottles to empirically determine what this hardware could
actually support, rather than assuming the original design's harder
gestures (position disambiguation, flick-vs-handling) would just work.
They didn't hold up reliably at scale; tap-vs-noise did (95-98%+,
98.4% for tap-vs-all-pooled-handling-noise). **Scope pivot:** rather than
force the fuller multi-gesture vocabulary, built a minimal "light
switch"-reliable contract instead — tap wakes, tap cycles, timeout
sleeps, no fourth gesture.

- [x] **`classify_valid_input`** — energy-threshold tap-vs-noise
      recognizer, pure, host-tested, 98.4% lab accuracy
- [x] **`_TapCycleState`** — two-phase ACK/CONFIRM state machine
      (ASLEEP→WAKING→SETTLING→AWAKE; tap=WAKE when asleep, tap=CYCLE when
      awake, timeout back to ASLEEP), pure, host-tested
- [x] **`micropython/gesture_sandbox.py`** — new sandbox, `import main`s
      the real recognizer/state-machine (never re-derives it) but tunes
      the trigger/capture timing independently (240Hz/4ms vs. `main.py`'s
      debug loop's 16ms, a real cause of missed taps found on hardware)
- [x] **Real-hardware validation, terminal-only first:** 10/10 consecutive
      real taps correctly resolved; the one live miss matched the
      already-known 3/180 failure-mode rate, not a new problem; `SETTLING`
      correctly filters taps landing right after `WAKE`
- [x] **LED jolt UX, then wired to a real tap** — ACK (instant, live
      during the ~1.2s capture window itself, before the recognizer has a
      verdict) → CONFIRM (WAKE gets a fuller rise/decay jolt; CYCLE gets a
      simpler flash+cut). Five real-hardware iteration rounds refined this
      from a first pass to something confirmed working well in-bottle:
      the "continental shelf" (ACK settles to a dim held brightness
      instead of black, so ACK and CONFIRM read as one gesture instead of
      two disconnected blips with a stall between them); tap-strength
      scaling (`dev` at trigger time — the only signal available before
      `energy` is known — drives both the ACK peak and the shelf level,
      "hardware-defined software"); a real saturation bug (an
      over-widened brightness ceiling clamped every hard tap to
      identical pure white, silently losing differentiation — found, fixed,
      and **hardened with regression tests**, `tests/test_gesture_sandbox.py`);
      a real rendering bug (`gamma()` crushing the ACK's low-range descent
      to near-black before the shelf's linearly-rendered brightness took
      over — "dive underground to 0, then back up to a plateau"); and
      non-interactive I2C error resilience (a jostled breadboard
      connection — same finding `vibration_sandbox.py` made first — no
      longer crashes the whole script; a sustained failure escalates to a
      persistent-breathe LED cue, matching `led-status-messages.md`'s own
      "errors are persistent and unambiguous" principle rather than a
      brief flash that would work against it)
- [x] 185 tests passing (`tests/test_gesture_envelope.py`,
      `tests/test_gesture_sandbox.py`)
- [ ] **Not yet on the target hardware** — everything above is Pico 2W +
      AE-WS2812B-STICK8 (8 LEDs, bare strip). The actual target is the
      XIAO ESP32-C3 + full LED tape, inside the real frosted bottle —
      genuinely different diffusion/contrast characteristics already
      proven to matter (the bare-strip-tuned brightness range needed
      widening again once first tested in-bottle). This is the explicit
      next step before merge
- [ ] **Not wired into `main.py`'s real production loop** — the jolt only
      exists in `gesture_sandbox.py`'s sandbox integration so far;
      `_run_gesture_debug_loop` (the terminal-only §4-10 exerciser) and
      the real main loop are both untouched by this work
- [ ] **`grab_and_tap` stays parked** — inconsistent across sessions,
      root cause unconfirmed, not built on (`docs/insights.md` §9)
- [ ] **Station-cycling display logic** — CYCLE needs a "current station
      index" concept that doesn't exist anywhere in `main.py` yet; a real,
      separate piece of scope, not resolved by any of the above
- [ ] **Not pushed to `dev`/`main`**

### LED status messages (errors + acknowledgments) ✅ implemented, local only

Full design: `docs/contracts/led-status-messages.md`. Spun out of the
wake-interaction doc's quiet-hours question, which turned out to need a
proper shared vocabulary rather than a yes/no — formalizes the existing
boot-ceremony/connect-failure pattern and extends it to three new cases:

- **Quiet-hours tap acknowledgment** — a tap during quiet hours never fully
  wakes the display (quiet hours always wins on whether it lights up), but
  isn't ignored either: one purple LED at `STATUS_LED_INDEX` (a new,
  deliberately contract-agnostic "middle-ish" position — `NUM_LEDS // 2`,
  NOT `ApproachContract`'s `ANCHOR_INDEX`, so this vocabulary works under any
  `CONTRACT`) for a few seconds, then dark again
- **Wake-to-no-data acknowledgment** — if a wake ceremony resolves and every
  active direction is genuinely `HIDDEN` (no catchable trains), a tap
  shouldn't feel like it did nothing — same `STATUS_LED_INDEX` mechanism, a
  different colour. Confirmed to repeat every time, not just once
- **Schedule-load failure** — confirmed in scope: a missing/corrupt
  `schedule.json` used to crash with a console print and zero LED
  indication; `load_schedule()` now also catches malformed JSON
  (`ValueError`, a pre-existing gap — only `OSError`/missing-file was
  handled before), and `main()` routes either failure into
  `_run_startup_failure_forever(SCHEDULE_ERROR_COLOR)` — the same
  persistent-breathe mechanism WiFi failure already used, now generalized
  to take a colour. Confirmed: error on failure, no indicator needed on
  success
- Stated as an explicit design rule, not just for this doc: never blend
  between states (STATIC or the established ANIMATED path only) — the third
  time this session a low-brightness blend has caused a real bug, worth
  promoting to a standing rule rather than re-deriving per-feature
- [x] Colours shipped as proposed, confirmed to iterate on real glass rather
      than in the abstract
- [ ] **Not yet on real hardware**; **not pushed to `dev`/`main`**

### Deferred to later sessions

- [ ] Line-color palette / metro-line static color scheme
- [ ] NFC / any provisioning mechanism (see Open decisions — under
      reconsideration, not blocking this build)
- [ ] Embedded Swift / Matter rewrite — separate track, own timeline, doesn't
      block any of the above

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
| XIAO board upgrade: C3 → S3 or C6 | ⏳ **leaning S3, being sourced** (2026-08-18) | Driven by the SRAM finding (`docs/insights.md` §11): the C3 can't fit `esp_wifi` alongside an app this size. **All XIAO boards share the 21 × 17.5mm form factor**, so this is a drop-in physically — same footprint, same bottle fit, resolder the module only. What changes is `config.py`, since GPIO numbering differs per variant (C3's D0 = GPIO2; others differ) — exactly what `pinouts/` tracks. **S3 preferred over C6**: its PSRAM lets MicroPython put the GC heap there, *structurally* removing the competition for internal SRAM rather than merely having more of it. C6's 512KB would likely suffice but keeps one shared pool. ⚠ Coupled to the DS3231 decision — see the BOM note in `docs/hardware.md` § DS3231. |
| DS3231 RTC | ⏳ candidate evaluated, not bought (2026-08-18) | Adafruit #3013 confirmed electrically compatible: 2.3–5.5V (no level shifter), I²C 0x68 so no conflict with the IMU's 0x6A/0x6B, 23 × 17.6 × 7.2mm. Needs a CR1220 (not included). **#5188 (STEMMA QT) worth the premium** — daisy-chains off the IMU's existing Qwiic socket, avoiding the one-GND-pad splice. Full evaluation: `docs/hardware.md` § DS3231. Removes the reason to run WiFi, which partially offsets the board-upgrade cost above. |
| ESP32-C3 WiFi memory headroom | ⏳ **worked around, not solved** (2026-08-17) | `esp_wifi_init()` needs ~40KB, ~26KB of it from one capability-constrained SRAM region that has **32 bytes of spare margin at a bare boot** — measured, see `docs/insights.md` §11. Compiling a 115KB `main.py` on-device grows MicroPython's GC heap into that region and triggers `OSError: Wifi Out of Memory`. **Worked around** by bringing WiFi up before `load_schedule()`, which reclaims ~5.5KB — enough today, but a 5KB fix against a 32-byte margin is one feature away from breaking again. **Real fix** is to stop compiling on-device: `.mpy` via `mpy-cross` (no firmware build) or freezing into firmware (bigger win, needs a custom build). Deliberately deferred to keep `feature/gesture-envelope` focused. Note V2's no-WiFi/DS3231 plan retires this entirely, and gesture work already runs WiFi-free via `GESTURE_DEBUG_ENABLED`. |
| Bottle vs. "glass stone on a stand" (eki-ishi) | 🔲 open, new (2026-08-16) | A form-factor proposal (`docs/glass-stone-concept.md`): a solid clear glass pebble on a crafted stand instead of electronics in a bottle neck. The argument is that ~every hard constraint in this project traces to an 18–19mm bore, and a stand retires four stalled threads at once (JJY time sync, onboard NFC *reader*, phone-free provisioning, and the whole battery/Qi power thread). Real cost: `ApproachContract` and arc-of-light don't survive — a new display contract is genuine unstarted scope, and the gesture jolt's tap-strength→brightness scaling would need to move to a different channel (duration/pulse/hue). Blocked on finding a candidate stand before anything else can be evaluated. **Explicitly parallel** to the bottle work per `docs/roadmap.md` § Form-Factor Philosophy — does not pause v1.1 or the v1.4 gift build. |
| Cork vs screw cap | 🔲 open | Cork aesthetic; screw cap practical for access during dev |
| LED direction / HAL abstraction | 🔲 open | Logical arc origin + reverse; full `led_drivers/` HAL deferred to ring arrival (`docs/insights.md` §4) |
| Multi-train modality | 🔲 open | Spare LEDs show 2nd-closest train; data already in `LeaveSignal.ttls` |
| Qi WCR viability | ✅ confirmed (2026-07-13) | Bare unbranded receiver, no FOD rejection on Belkin pad, works through glass, drives 120 LEDs. See `docs/hardware.md` bring-up log |
| WCR power at full brightness | ✅ characterized (2026-07-13) | `BRIGHTNESS=1.0` full-white froze the Qi path (rail collapse) and tripped MacBook USB overcurrent. `0.15` is the stable ceiling on both — already visually "full" for the 120-LED tape. Real ceiling is ≈0.15 or lower; see `docs/hardware.md` |
| LED tape mid-cut connector handling | 🔲 deferred | Until a soldering iron is in hand; factory pigtail + jumper-pin-in-innie trick is sufficient for bring-up (`docs/hardware.md`) |
| NFC provisioning approach | ⏸ still on hold — **candidate unblock identified 2026-08-16, not yet verified** | **New:** `docs/nfc-provisioning.md` §8 proposes skipping the phone entirely — a USB NFC reader/writer on the Mac + a `nfcpy` script writes NTAG213 (Type-2) stickers directly, which would clear every wall below at once. Deliberately **not** marked resolved: nothing is bought, written, or tested, and the path carries its own unverified toolchain assumption (dongle + `nfcpy` on this specific Mac — ACR122U in particular has known macOS PC/SC driver friction). §8.3 records the one-command falsification to run before trusting it. Flipping this row to ✅ requires that test passing, not the proposal existing. **Original blockage below.** The custom-iOS-app plan hit two stacked toolchain walls: the dev Mac (2019 Intel MacBook Air) is structurally capped below the macOS/Xcode version needed for iOS-26 builds, and iOS NFC reading needs the paid $99/yr Apple Developer Program regardless. Reconsidering the whole provisioning *mechanism*, not just working around the walls — candidates include ESP32 SoftAP + browser form (no app, cross-platform) and passive NTAG213 (Type-2, not Type-5 — iOS Shortcuts *does* work on Type-2) station cards, closer to the original concept. Longer-term direction leans toward an Embedded Swift/Matter rewrite (own track, own timeline — see below), which would remove the custom-app requirement entirely: settings live in Matter attributes edited from the Home app, no Xcode/App Store gate. Not blocking the v1.4 gift build. |
| iOS NFC app: separate repo? | ⏸ moot while approach is on hold | Was leaning yes if the custom-app plan resumes. `docs/nfc-provisioning.md` §7 |
| Tag payload: NDEF vs private format | ⏸ moot while approach is on hold | Was leaning private (length+CRC+JSON). `docs/nfc-provisioning.md` §4, §7 |
| V2 rewrite target: Rust/Embassy vs. Embedded Swift/Matter | 🔲 open, new (2026-07-23) | Two independent V2 candidates now on the table, arrived at from different directions. Embedded Swift/Matter would also solve provisioning (Home app UI, no custom app, no entitlement gate) but the toolchain is experimental (not source-stable, real setup friction reported) and means re-deriving the whole display pipeline (contracts, gamma/dither, config) from scratch. Not deciding yet — V1.4/V1.5 firmware work doesn't depend on this. |
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
