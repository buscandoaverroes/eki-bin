# eki-bin — CLAUDE.md

**eki-bin** (駅瓶, "station jar"). Ambient train-departure display: a frosted
glass jar that glows an arc of light showing how long until the next train. No
phone, no screen — glanceable like a clock.

This file is intentionally short — orientation and how to behave. Detailed
reference lives in the files mapped below; keep this lean and push specifics there.

---

## Teaching directive

**The owner of this project is using it to improve their Rust proficiency.**

When writing Rust code in this repo, take a teaching role:
- Explain *why* patterns are written the way they are, not just *what* they do.
- Call out Rust-specific concepts when they first appear: ownership, borrowing,
  lifetimes, traits, error handling with `Result`/`Option`, `const` vs `static`, etc.
- Reference the MicroPython V1 equivalent inline where it helps — the owner already
  understands the logic, they're learning to express it in Rust.
- When there are multiple valid Rust approaches, show the idiomatic one and briefly
  note why it's preferred over alternatives.
- Don't simplify to the point of being unidiomatic. Embedded Rust has real patterns
  (typestate, HAL traits, Embassy async) — teach them, don't hide them.
- Sometimes the user will want to take the lead in writing first, with your support for improvements after. Feel free to propose that they take the lead on topics you already discussed, or partially scaffold/stub new code.

---

## Hard Rules

1. **Never read secrets or credentials** — do not `cat`, `view`, or otherwise inspect `config.py` or any file containing real credentials. If you need to understand the shape of a config file, read the `.example` version or ask the user.
2. **Never `git push`** — always stop at commit and prompt the user to push themselves.

---

## Git / Dev-Flow

- Claude may **auto-commit on feature branches** — small, focused commits with clear messages are preferred.
- **Merges require user approval** — propose the merge, explain what it does, wait for confirmation before executing.
- **User always pushes** — never push to remote, even if explicitly asked. Remind the user to push instead.
- Branch naming: `feature/<short-description>`, e.g. `feature/led-strip-v1`, `feature/rust-embassy-blink`.
- On first session: confirm branch name and base branch with user before committing anything.

---

## Where things live

| Looking for… | File |
|---|---|
| Overview, quick start, every `make` target, workflows | `README.md` |
| Building a unit from scratch: solder → flash → upload → bring-up → run | `docs/provisioning-runbook.md` |
| What's true now / next / open decisions (current only) | `dev-status.md` |
| Build-by-build history through V1.6 (frozen 2026-09-29) | `docs/archive/dev-status-history.md` |
| **The plan: making tap + tilt coexist** — record → replay → arbiter → gyro; ML gated. *Draft; iterate before building* | `docs/imu-interaction-plan.md` |
| Hardware roadmap: v1.1 parts, form-factor threads, NFC/power research | `docs/roadmap.md` |
| **Form-factor proposal: the chandelier** — filaments suspended in 3D, the culmination of "the object has no front". *A proposal; nothing scheduled* | `docs/chandelier-concept.md` |
| Form-factor proposal: "glass stone on a stand" (eki-ishi) — **a proposal, not a decision; nothing scheduled.** The JJY time-signal and surface-as-input research memos hang off it | `docs/glass-stone-concept.md` |
| Guiding design principles (some stubs) | `docs/design-principles.md` |
| **Palette checks** — `palette_problems()` / `safe_range()` / boot report; the usable BRIGHTNESS window and what binds each end | `micropython/palette.py` |
| **On-board detection** — ESN vs the MLC, a piezo, and the gyro; why the mic wall is conceptual. *Analysis; nothing built* | `docs/on-board-detection.md` |
| **Palette/brightness config — three proposals** to stop clipping and floor bugs being invisible. *A proposal; nothing built* | `docs/palette-model.md` |
| Field notes + why-decisions + parked ideas | `docs/insights.md` |
| Design rationale + full V2 hardware list | `docs/concept.md` |
| Parts in hand, voltage compatibility | `docs/hardware.md` |
| Per-board pin assignments (what connects to what) | `pinouts/` |
| `schedule.json` schema + YAML pipeline | `docs/contracts/schedule-json.md` |
| `config.py` fields + secrets handling | `docs/contracts/config.md` |
| LED display pipeline (LeaveSignal → contracts) | `docs/contracts/display-contract.md` |
| Positional/approach display paradigm (new, in progress) | `docs/contracts/approach-contract.md` |
| Boot/startup LED sequence (implemented, not yet on hardware) | `docs/contracts/startup-sequence.md` |
| Tap-gesture recognition + ACK/CONFIRM LED jolt + tap-to-cycle-line — **shipped and running on real hardware in the bottle** (XIAO C3 + IMU + 21-LED strip) | `docs/contracts/gesture-envelope.md` |
| IMU tap wake/sleep interaction (original design — partially superseded by `gesture-envelope.md`, still correct for its state-machine/safety-gate patterns) | `docs/contracts/wake-interaction.md` |
| LED status-message vocabulary (errors, acknowledgments — design only) | `docs/contracts/led-status-messages.md` |
| **The light language** — struck-glass metaphor, the five motion words, the ACK-is-the-transition restructure, tilt input (design only, nothing implemented) | `docs/contracts/light-language.md` |
| Shopping memo: strip load switch + battery pack (requirements, Japanese search terms, two traps) | `docs/shopping-battery-power.md` |
| V1 → V2 Rust/Embassy migration map | `docs/rust-migration.md` |
| V1 firmware | `micropython/main.py`, `micropython/led_test.py` |
| Quick colour/animation A-B comparisons + gesture-jolt shape prototyping on real hardware | `micropython/led_sandbox.py` |
| **Crawl sandbox** — how a train moves (6 hop styles) and how the station fades (5). The physics-vs-agency fork the metaphor cannot settle | `micropython/crawl_sandbox.py` (`make crawl-sandbox`) |
| The five motion words on real glass — eased vs linear, all five back to back, `outward` ∝ strike force | `micropython/motion_sandbox.py` (`make motion-sandbox`) |
| **Horizon ceremonies** — goodnight when trains exist but none is in reach, and the morning wake that lets the arc be seen opening | `micropython/horizon.py` |
| **The five motion words, as shipped** — `outward` on wake, `around` on a line change, `shake` for "nothing to change to" | `micropython/motion.py` |
| **Tilt-to-adjust, the shipped controller** — magnitude gate, neutral re-learning, expo curve. One implementation, used by both the firmware and the sandboxes | `micropython/tilt.py` |
| Tilt bench tests: the go-up-first overshoot (**run in the dark**) and `curve_test`'s timed target acquisition | `micropython/tilt_sandbox.py` (`make tilt-sandbox`) |
| Tilt **freeform** — no target, logs every sample to JSONL, asks how it felt. The one that produces usable data | `micropython/tilt_freeform.py` |
| **Wiring the current unit** — self-contained ASCII, config values, traps, bring-up order | `pinouts/v1.6-rp2350-production-unit.md` |
| Low-PWM floor (strip property — test OUT of the bottle) | `micropython/low_pwm_test.py` (`make low-pwm-test`) |
| Hue separation / how many lines a vessel supports (glass property — test IN it) | `micropython/hue_test.py` (`make hue-test`) |
| Which onboard LEDs software can actually turn off | `micropython/onboard_led_test.py` (`make onboard-led-test`) |
| Is this board healthy? flash/filesystem/transport probe | `make doctor` → `scripts/board_check.py` |
| Run firmware from the host, zero flash writes | `make dev` → `scripts/dev.sh` |
| DS3231 drift: the maths, and why offset ≠ drift | `docs/rtc-drift-theory.md` |
| Live gesture recognizer + LED jolt sandbox (real IMU input, real LED output, no full main.py loop) | `micropython/gesture_sandbox.py` |
| IMU bring-up + gesture data-collection tools (see `docs/insights.md` §8 for the field log these produced) | `micropython/imu_test.py`, `vibration_sandbox.py`, `handling_test.py`, `orientation_test.py` |
| Host test suite (`make test`, runs before `make upload`) | `tests/` |

---

## Current focus

**The production unit runs and has been lived with.** XIAO RP2350 (no radio)
+ DS3231 + LSM6DSV16X IMU + 21-LED strip in a brown glass bottle, USB-powered:
correct time across power cycles, tap wakes/cycles **line**, tilt adjusts
brightness, `ApproachContract` with per-line colour, day/night brightness,
goodnight/morning ceremonies, and the motion vocabulary (`docs/contracts/
light-language.md`). Firmware is eleven modules, no radio code. `make test`
runs lint + 418 host tests before every `make upload`; keep it green.
`make doctor` before trusting a board — **a XIAO RP2350 needs firmware newer
than 2026-04-06** (`docs/insights.md` §13). Wiring is self-contained in
`pinouts/v1.6-rp2350-production-unit.md`.

**Colour is measured, not guessed** (`docs/insights.md` §12): low-PWM floor is
3; the glass sets the line count (thick brown = 2–3 hues); a neutral marker is
impossible in brown glass. `make low-pwm-test` runs **out** of the bottle,
`make hue-test` **in** it.

**Three walls from givable** (`dev-status.md`):
1. **Tap + tilt fight each other.** A composition problem, not a
   classification one — including the *approach* to a tilt firing a tap, where
   the disambiguating evidence arrives after the false tap. Plan (draft):
   `docs/imu-interaction-plan.md`. **No ML yet, no new sensor yet** — record
   with the gyro on, build a replay harness, then one arbiter with a look-back
   veto. Ranking of the ML options: `docs/on-board-detection.md`.
2. **A wiring harness** — leaning to a lid-mounted unit assembled outside the
   vessel.
3. **Power** — a battery needs a strip load switch; the chandelier/lamp form
   (USB from the top) would dissolve it.

**The form-factor fork is open and unscheduled:** strip-in-bottle now, but the
intended end state is the **chandelier** (`docs/chandelier-concept.md`), also
open to a bird's-nest tangle. Don't tune per-mount constants as if permanent
— fix the *state machine* (transfers) before *thresholds* (don't; 0%
cross-bottle). NFC / sticker-book input is real but **2–3 versions out** and not
required for first givability. A provisioning manifest (a record per unit) is
needed by the second unit: `docs/gift-registry.md`.

---

## Key locked decisions

- **MicroPython V1 → Rust (Embassy) V2** — V1 validates the logic; the Rust
  rewrite is the learning goal (see Teaching directive + `docs/rust-migration.md`).
- **No WiFi in V2 normal operation** — DS3231 RTC, deterministic local schedules,
  orientation selects mode, Qi charging.

Full rationale and V2 hardware: `docs/concept.md`. Open hardware/format questions
and the MCU decision: `dev-status.md`.
