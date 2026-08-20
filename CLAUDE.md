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

**Two active parallel branches (worktrees), both cut from `dev`:**

- **`feature/color-consistency`** — the live problem. Through the brown
  bottle only near-opposite hues are distinguishable, which caps how many
  lines the palette can support (`docs/insights.md` §12). Also owes a real
  fix for marker ticks: they currently render at `(1,1,1)`, where WS2812B
  channel matching collapses and neutral gray reads yellow, and the present
  `MARKER_BRIGHTNESS = 0` is a **workaround that removes the affordance**,
  not a fix. Raising overall brightness in-bottle likely solves both at
  once. Iterate with `micropython/led_sandbox.py` — no WiFi or schedule
  needed. **The MCU is irrelevant here; the strip and the bottle are not.**
- **`feature/ds3231-time`** — bring up the DS3231 RTC on the Pico 2W
  breadboard (I²C 0x68, no conflict with the IMU at 0x6A/0x6B). Evaluation
  and wiring: `docs/hardware.md` § DS3231.

Both converge on the intended production unit: **XIAO RP2350 (no radio) +
DS3231 + IMU + LED strip**, wired or Qi powered. Note `TIME_SOURCE="rtc"`
already exists and is what makes a WiFi-free unit run today.

In parallel, separately: **v1.1** (Qi power-path + soldering into the
bottle) — see `docs/roadmap.md`. When touching board-specific pins,
check/update `pinouts/<board>.md` alongside `config.py` — don't let pin
facts drift out of that directory. `make test` runs before every
`make upload`, keep it green. Architecture: `docs/contracts/
display-contract.md`; progress + open decisions: `dev-status.md`.

---

## Key locked decisions

- **MicroPython V1 → Rust (Embassy) V2** — V1 validates the logic; the Rust
  rewrite is the learning goal (see Teaching directive + `docs/rust-migration.md`).
- **No WiFi in V2 normal operation** — DS3231 RTC, deterministic local schedules,
  orientation selects mode, Qi charging.

Full rationale and V2 hardware: `docs/concept.md`. Open hardware/format questions
and the MCU decision: `dev-status.md`.
