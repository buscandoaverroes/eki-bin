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
| What's done / next / open decisions | `dev-status.md` |
| Hardware roadmap: v1.1 parts, form-factor threads, NFC/power research | `docs/roadmap.md` |
| Form-factor proposal: "glass stone on a stand" (eki-ishi) — **a proposal, not a decision; nothing scheduled.** The JJY time-signal and surface-as-input research memos hang off it | `docs/glass-stone-concept.md` |
| Guiding design principles (some stubs) | `docs/design-principles.md` |
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
| V1 → V2 Rust/Embassy migration map | `docs/rust-migration.md` |
| V1 firmware | `micropython/main.py`, `micropython/led_test.py` |
| Quick colour/animation A-B comparisons + gesture-jolt shape prototyping on real hardware | `micropython/led_sandbox.py` |
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

V1 firmware is **feature-complete**: the full `time → LeaveSignal →
DisplayContract → LEDs` pipeline (six contracts including `approach`, gamma +
temporal dithering, seamless clock, config-driven throughout), guarded by a
host test suite. The **v1.2 board-portability checkpoint passed**: the XIAO
ESP32-C3 runs the identical firmware via a `config.py` swap only — proof the
board abstraction (`LED_PIN`, `HEARTBEAT_PIN`) holds up on real hardware.

**Merged to `dev`:** the gesture envelope (IMU tap recognition + two-phase
ACK/CONFIRM LED jolt) and its integration into `main.py`'s real loop — a
tap now wakes the display and cycles which **line** is shown. Multi-line
schedules (`lines[]`, optional, backward-compatible) and per-line colour
rendering shipped with it. Full state: `docs/contracts/gesture-envelope.md`
§11; provisioning a unit end-to-end: `docs/provisioning-runbook.md`.

**The production unit runs.** XIAO RP2350 (no radio) + DS3231 + IMU +
21-LED strip: correct time from the RTC, surviving a power cycle, tap-to-cycle
working, rendering `ApproachContract`. Wiring is **self-contained** in
`pinouts/v1.6-rp2350-production-unit.md` — that file is authoritative for this
build; the `v1.4-*` system files are the record of earlier ones.

**Merged since:** DS3231 integration (`TIME_SOURCE = "ds3231"`), the **V1.6
single-target split** (`main.py` 3,127 → ~620 lines across eleven modules; the
radio-less board carries no radio code — `docs/v1.6-refactor.md`), provisioning
docs, and the colour measurements below.

**Colour is measured, not guessed** (`docs/insights.md` §12):

- **Low-PWM floor is 3** on the bench strip. Below it WS2812B channels stop
  matching and equal values give an *unpredictable* hue. `MARKER_BRIGHTNESS`
  default is now `0.25` (= raw 3); the old `0.15` produced raw 1, which is
  exactly why ticks read red and why `= 0` had been set to hide them.
- **The glass sets the line count.** Amber glass is a blue-cut filter, so it
  collapses the hue wheel onto the red-green axis: thick opaque brown supports
  **2-3** hues, mid brown 4-5, clear brown 5+. **Brightness does not help** —
  scaling preserves channel ratios and cannot restore one the glass removes.
- A **neutral marker is impossible in brown glass at any value.** In there the
  criterion is "does the tick recede behind the train", answered by brightness
  and position, not hue.

**Two bench tools, and they need different rigs:** `make low-pwm-test` (strip
property — run it **out** of the bottle) and `make hue-test` (glass property —
run it **in**, and try several vessels).

**Open:** the vessel decision — thick brown is the best-looking and the most
limiting. `docs/roadmap.md` v1.1 (Qi + soldering) is the next hardware step.
When touching board-specific pins, update `pinouts/<board>.md` alongside
`config.py`. `make test` runs lint + 309 host tests before every `make upload`;
keep it green. `make doctor` before trusting a board — and **a XIAO RP2350
needs firmware newer than 2026-04-06**, or its filesystem is sized past the
physical flash (`docs/insights.md` §13).

---

## Key locked decisions

- **MicroPython V1 → Rust (Embassy) V2** — V1 validates the logic; the Rust
  rewrite is the learning goal (see Teaching directive + `docs/rust-migration.md`).
- **No WiFi in V2 normal operation** — DS3231 RTC, deterministic local schedules,
  orientation selects mode, Qi charging.

Full rationale and V2 hardware: `docs/concept.md`. Open hardware/format questions
and the MCU decision: `dev-status.md`.
