# Development

_How the work gets done: setup, the everyday loop, every `make` target, and
the git flow. Building a bottle from parts is a different job, covered by
the [provisioning runbook](provisioning-runbook.md)._

> **⚠ Not yet reproducible from a clean checkout.** These commands are the
> ones in daily use on one Mac and one bottle (bottle-01), and they've grown
> piece by piece since V1. Making v1.7 build cleanly from scratch, on another
> machine and another board, is planned, not done. Treat this as a map of
> the tools, not a guaranteed recipe.

## Setup

```bash
make setup     # .venv with pinned tools (mpremote, esptool, PyYAML, pytest, ruff),
               # and the pre-push leak check (core.hooksPath = .githooks)
```

Then the two files that are yours and never committed:

```bash
cp micropython/config.example.py micropython/config.py   # pins, TIME_SOURCE, tuning
cp schedules/mystation.example.yaml schedules/mystation.yaml
make schedule                                             # YAML → schedules/*.json
```

What every setting does: [`docs/contracts/config.md`](contracts/config.md).
The schedule format: [`docs/contracts/schedule-json.md`](contracts/schedule-json.md).
Why both are gitignored: [`docs/security.md`](security.md).

## The everyday loop

| | |
|---|---|
| `make test` | lint (`ruff`) + 600+ host tests. Runs before every upload |
| `make dev` | run the firmware straight from the Mac: `mpremote mount` serves `micropython/` to the board, so nothing is written to its flash. Edit, Ctrl-C, re-run |
| `make upload` | tests, then the firmware, `config.py` and the schedule onto the board, each file verified by hash. `main.py` goes last |
| `make screen` · `make repl` | watch it run · a REPL on the board |
| `make doctor` | is this board healthy enough to trust? Probes flash, filesystem and the serial link with throwaway data |

## Every target

**A new board**

| | |
|---|---|
| `make flash-micropython BOARD=…` | flash MicroPython (`pico2w`, `esp32c3`, `xiao-rp2350`; asks if omitted) |
| `make i2c-scan` | find I²C devices without being told which pins |
| `make led-test` · `make imu-test` · `make rtc-test` | bring-up for the strip, the motion sensor, the clock |
| `make rtc-seed` | **writes** the DS3231 (the only target that does) |
| `make set-time` | set the board's own RTC, for `TIME_SOURCE = "rtc"` |
| `make onboard-led-test` | which onboard LEDs software can actually turn off |

**The light, on real glass**

| | |
|---|---|
| `make low-pwm-test` | the strip's low-PWM floor (run **out** of the bottle) |
| `make hue-test` | how many line colours the glass separates (run **in** it) |
| `make motion-sandbox` · `make crawl-sandbox` · `make tilt-sandbox` | the motion words, how a train moves, tilt as input |

**Input: recording and simulation**

| | |
|---|---|
| `make interaction-log UNIT=…` | the real firmware, streaming its decisions to the Mac, with one-key labels |
| `make imu-record UNIT=…` | the raw sensor at 240 Hz, no firmware. `PROTOCOL=tap-vs-grab` cues each trial |
| `make replay` | the real tap/tilt firmware code over recordings, at any loop rate |
| `make sim` · `make sim-live` | detect → arbiter → classify as swappable blocks, on recordings or live |
| `make imu-bench` | where the stream's missing samples go |

Recordings go to `data/` and are curated in `data/imu-sessions.json`. Both
are gitignored. Method: [`docs/imu-interaction-plan.md`](imu-interaction-plan.md).

**The clock**

| | |
|---|---|
| `make rtc-drift UNIT=…` | the DS3231's drift against NTP, per unit. The theory: [`docs/rtc-drift-theory.md`](rtc-drift-theory.md) |

**One-offs**

| | |
|---|---|
| `make run` · `make run-file FILE=…` | run `main.py`, or any script, once without flashing |
| `make upload-file FILE=…` | install any script as `main.py`, for USB-less tests |
| `make clear-vibes` | delete old capture files left on the board |
| `make example-schedule` | regenerate the committed, **synthetic** example timetable |

## Git flow

- **Branches:** `feature/<name>` → a PR into `dev` (`make pr`) → `dev` into
  `main` at each release, tagged (`v1.7`). Release notes live in
  [`docs/releases/`](releases/).
- **Publishing is checked:** `make leakcheck` scans the outgoing diff and
  commit messages for credentials and personal details. It also runs on
  every `git push` (the pre-push hook) and inside `make pr`.
- **AI-assisted:** the code is developed with Claude Code.
  [`CLAUDE.md`](../CLAUDE.md) is its brief, including the house rules:
  Claude commits on feature branches; the owner pushes and merges.

## Repo layout

```
eki-bin/
├── micropython/   firmware: main.py and its modules, plus bench sandboxes and bring-up scripts
├── scripts/       host tools: upload, schedules, recording, replay, the simulator
├── tests/         host-side tests (`make test`)
├── docs/          rationale, contracts (the interfaces), plans, field notes, releases
├── pinouts/       per-board wiring, the source of truth for what connects where
├── schedules/     the example timetable (real ones are gitignored)
└── dev-status.md  what's true now, what's next, open decisions
```
