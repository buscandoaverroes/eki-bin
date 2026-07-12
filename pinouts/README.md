# pinouts/

One file per board: physical pin diagram, GPIO-vs-position mapping, and exactly
what's wired to what **in this project**. This is the single source of truth for
"which pin goes where" — `docs/hardware.md` covers parts/components/voltage
compatibility, not pin assignments; this directory owns those.

Why this exists: the project now spans more than one board (Pico 2W, XIAO
ESP32-C3, eventually others). Pin facts that live only in `config.py` defaults
or scattered comments drift silently the moment a second board shows up —
this directory is where they're supposed to live instead.

## Files

| File | Board | Status |
|---|---|---|
| [pico2w.md](pico2w.md) | Raspberry Pi Pico 2W | ✅ Verified — wired and running (V1) |
| [xiao_esp32c3.md](xiao_esp32c3.md) | Seeed XIAO ESP32-C3 | ✅ Verified — wired and running (v1.2 checkpoint passed 2026-07-05) |

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

Copy the shape of an existing file: parts-in-hand context (or link to
`docs/hardware.md`), an ASCII physical-pin diagram, a wiring table for this
project's connections (with GPIO numbers), and a "reserved for later" table if
relevant. Add a row to the table above.
