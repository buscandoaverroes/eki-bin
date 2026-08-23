# pinouts/

Physical pin diagrams, GPIO-vs-position mappings, and exactly what's wired to
what **in this project**. This is the single source of truth for "which pin
goes where" — `docs/hardware.md` covers parts/components/voltage
compatibility, not pin assignments; this directory owns those.

Why this exists: the project now spans more than one board (Pico 2W, XIAO
ESP32-C3, eventually others). Pin facts that live only in `config.py` defaults
or scattered comments drift silently the moment a second board shows up —
this directory is where they're supposed to live instead.

## Two kinds of file

- **Board files** (one per board) — a single board's own pins: physical
  diagram, GPIO numbers, what's broken out where. The board's pinout doesn't
  change across builds, so these are long-lived and board-scoped.
- **System files** (one per meaningfully-distinct build) — how a specific
  build's *parts connect to each other* (MCU → LED strip → power source,
  etc.), on top of whatever the board file already establishes. Add a new
  system file when a build's part set meaningfully changes (different MCU, a
  second LED run, a sensor added) — don't grow one system file to cover every
  build variant, and don't duplicate a board's own pin facts into it (link
  to the board file instead).

## Files

| File | Scope | Status |
|---|---|---|
| [pico2w.md](pico2w.md) | Board — Raspberry Pi Pico 2W | ✅ Verified — wired and running (V1) |
| [xiao_esp32c3.md](xiao_esp32c3.md) | Board — Seeed XIAO ESP32-C3 | ✅ Verified — wired and running (v1.2 checkpoint passed 2026-07-05) |
| [xiao_rp2350.md](xiao_rp2350.md) | Board — Seeed XIAO RP2350 | ✅ Verified — LED + IMU + DS3231 all confirmed 2026-08-22 |
| [v1.4-gift-jar-system.md](v1.4-gift-jar-system.md) | System — XIAO + 21-LED strip + Qi/USB-C power | ⬜ Proposed — one pad position needs a physical confirm |
| [v1.4-imu-dev-unit.md](v1.4-imu-dev-unit.md) | System — the above **+ LSM6DSV16X IMU**; the gesture-envelope dev/validation unit | ✅ Verified — full from-scratch provisioning 2026-08-16 |

## Conventions

- **Status marker** at the top of each file: ✅ Verified (physically wired and
  confirmed working) or ⬜ Proposed (from datasheet/silkscreen research, not yet
  bench-confirmed). Flip to ✅ once you've actually tested it — don't leave a
  proposed pinout looking authoritative.
- **Physical pin** = the numbered/labeled pad on the board silkscreen (what your
  multimeter probe or jumper wire lands on).
- **GPIO number** = what MicroPython's `machine.Pin(n, ...)` actually takes.
  This is the number that goes in `config.py`'s `LED_PIN` / `HEARTBEAT_PIN` — the
  physical position is for your hands, the GPIO number is for the firmware.
- Each file's wiring table should map directly onto real `config.py` values —
  if you change a connection, update both the doc and the config, in the same commit.
- Every open/unverified detail gets flagged explicitly (⚠) rather than asserted
  confidently. A wrong pin assignment costs you a bring-up session; a flagged
  unknown costs you five minutes with a datasheet.

## Adding a new board

Copy the shape of an existing board file: parts-in-hand context (or link to
`docs/hardware.md`), an ASCII physical-pin diagram, a wiring table for this
project's connections (with GPIO numbers), and a "reserved for later" table if
relevant. Add a row to the table above.

## Adding a new system

Copy the shape of [v1.4-gift-jar-system.md](v1.4-gift-jar-system.md): a short
parts list (linking to the relevant board file(s) and `docs/hardware.md`, not
repeating their content), a diagram of how the parts connect to *each other*
(power source → MCU → peripheral, not the MCU's own internal pin layout —
that's the board file's job), and a wiring table. Name it after the build
version it documents (`v1.x-<short-description>.md`), add a row to the table
above, and flag anything not yet physically confirmed the same way board
files do.
