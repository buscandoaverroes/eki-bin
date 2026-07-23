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
| Guiding design principles (some stubs) | `docs/design-principles.md` |
| Field notes + why-decisions + parked ideas | `docs/insights.md` |
| Design rationale + full V2 hardware list | `docs/concept.md` |
| Parts in hand, voltage compatibility | `docs/hardware.md` |
| Per-board pin assignments (what connects to what) | `pinouts/` |
| `schedule.json` schema + YAML pipeline | `docs/contracts/schedule-json.md` |
| `config.py` fields + secrets handling | `docs/contracts/config.md` |
| LED display pipeline (LeaveSignal → contracts) | `docs/contracts/display-contract.md` |
| Positional/approach display paradigm (new, in progress) | `docs/contracts/approach-contract.md` |
| Boot/startup LED sequence (design only, not built) | `docs/contracts/startup-sequence.md` |
| V1 → V2 Rust/Embassy migration map | `docs/rust-migration.md` |
| V1 firmware | `micropython/main.py`, `micropython/led_test.py` |
| Quick colour/animation A-B comparisons on real hardware | `micropython/led_sandbox.py` |
| Host test suite (`make test`, runs before `make upload`) | `tests/` |

---

## Current focus

V1 firmware is **feature-complete**: the full `time → LeaveSignal →
DisplayContract → LEDs` pipeline (five contracts, gamma + temporal dithering,
seamless clock, ~19 `config.py` knobs), guarded by a host test suite. Remaining
V1 work is **in-jar tuning via `config.py`**, not features — so prefer config
changes over firmware edits, and keep `make test` green (it runs before
`make upload`). The **v1.2 board-portability checkpoint passed**: the XIAO
ESP32-C3 runs the identical firmware via a `config.py` swap only — proof the
board abstraction (`LED_PIN`, `HEARTBEAT_PIN`) holds up on real hardware.
Current focus: **v1.1** (Qi power-path + soldering into the bottle) — see
`docs/roadmap.md`. When touching board-specific pins, check/update
`pinouts/<board>.md` alongside
`config.py` — don't let pin facts drift out of that directory.
Architecture: `docs/contracts/display-contract.md`; progress + open decisions:
`dev-status.md`.

---

## Key locked decisions

- **MicroPython V1 → Rust (Embassy) V2** — V1 validates the logic; the Rust
  rewrite is the learning goal (see Teaching directive + `docs/rust-migration.md`).
- **No WiFi in V2 normal operation** — DS3231 RTC, deterministic local schedules,
  orientation selects mode, Qi charging.

Full rationale and V2 hardware: `docs/concept.md`. Open hardware/format questions
and the MCU decision: `dev-status.md`.
