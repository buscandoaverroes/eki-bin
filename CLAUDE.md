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
| Tap-gesture recognition + two-phase ACK/CONFIRM LED jolt UX — implemented, extensively real-hardware validated (Pico 2W + LED stick), XIAO/full-tape/bottle validation still pending | `docs/contracts/gesture-envelope.md` |
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

**Active branch: `feature/gesture-envelope`** (not yet pushed or merged) —
IMU (LSM6DSV16X) tap-gesture recognition + a two-phase ACK/CONFIRM LED jolt,
replacing the earlier wake-interaction design after real-hardware testing
found the original multi-gesture plan unreliable and scoped down to a
minimal, "light switch"-reliable tap-or-noise contract instead. Extensively
validated on real hardware (Pico 2W + AE-WS2812B-STICK8), including five
rounds of live tuning against real taps — but that's still a bare LED strip,
not the target XIAO + full LED tape inside the actual frosted bottle, which
is the next validation step before merge. Full state: `docs/contracts/
gesture-envelope.md` §11; progress log: `dev-status.md`.

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
