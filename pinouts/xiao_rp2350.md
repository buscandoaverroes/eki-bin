# Seeed XIAO RP2350

**Status: ⬜ Proposed** — cross-referenced against Seeed's own docs
([OSHW-XIAO-Series/XIAO-RP2350.md](https://github.com/Seeed-Studio/OSHW-XIAO-Series/blob/main/document/SeeedStudio_XIAO_RP2350/XIAO-RP2350.md)),
not yet confirmed against a physical board. Flip to ✅ once a bring-up
script actually talks to something over these pins.

Parts context: `docs/roadmap.md`. **Same RP2350 silicon as the Pico 2W**
(`pinouts/pico2w.md`) — different board, no WiFi, XIAO form factor. Not to
be confused with the XIAO ESP32-C3 (`pinouts/xiao_esp32c3.md`), which
shares the same 21×17.5mm footprint and, by coincidence below, some of the
same GPIO numbers — but is different silicon with different I²C rules.

---

## Physical pinout (per Seeed's official docs, not yet bench-verified)

```
                 ┌─────────────┐
                 │   USB-C     │
                 └──┬───────┬──┘
  ► D0/A0  ──────────┤       ├────────── 5V
     D1/A1 ──────────┤       ├────────── GND
     D2/A2 ──────────┤ RP2350├────────── 3V3
     D3    ──────────┤       ├────────── D10 / GPIO3 (MOSI)
     D4/SDA──────────┤       ├────────── D9  / GPIO4 (MISO)
     D5/SCL──────────┤       ├────────── D8  / GPIO2 (SCK)
     D6/TX ──────────┤       ├────────── D7  / GPIO1 (RX)
                      └───────┘
```

`►` = candidate LED data pin (D0), matching this project's convention on
every other board (Pico 2W GP6, XIAO C3 D0/GPIO2) of using the first
left-side pin. Not yet wired or confirmed.

| Pin label | GPIO |
|---|---|
| D0 | 26 |
| D1 | 27 |
| D2 | 28 |
| D3 | 5 |
| D4 (SDA) | 6 |
| D5 (SCL) | 7 |
| D6 (TX) | 0 |
| D7 (RX) | 1 |
| D8 (SCK) | 2 |
| D9 (MISO) | 4 |
| D10 (MOSI) | 3 |

## ⚠ D4/D5 are GPIO6/GPIO7 — same numbers as the XIAO C3, different bus

**Coincidence, not portability.** The XIAO ESP32-C3's I²C pins for this
project are also GPIO6/GPIO7 (`pinouts/xiao_esp32c3.md`), so
`IMU_SDA_PIN`/`IMU_SCL_PIN` values carry over unchanged between the two
boards. **`IMU_I2C_ID` does not.**

On the ESP32-C3, I²C is mapped to any GPIO pair in software — `I2C_ID = 0`
works regardless of which pins are chosen, which is why this project's
config never had to think about it. **On RP2350, the I²C peripheral
instance is fixed in silicon per pin, not selectable**: I²C0 lives on
GP0/1, GP4/5, GP8/9, GP12/13, GP16/17, GP20/21; I²C1 on GP2/3, GP6/7,
GP10/11, GP14/15, GP18/19. `GP6`/`GP7` is **I²C1**.

So a config ported from the XIAO C3 by copying `IMU_SDA_PIN`/`IMU_SCL_PIN`
alone would silently construct `I2C(0, ...)` against pins that are
actually on bus 1 — the exact "empty scan, spend an hour before finding
the pin mismatch" failure mode from `docs/insights.md`, just relocated
from the pin numbers to the bus number. **Confirm on this board:
`IMU_I2C_ID = 1`.**

The Pico 2W follows the same fixed-per-pin rule, which is *why* GP0/GP1
was chosen there in the first place (`pinouts/pico2w.md`) — it's I²C0 on
that board too, just by chip design rather than by choice.

## BOOTSEL

1. Press and hold the BOOT button
2. Connect USB
3. Release BOOT once connected

Same mass-storage `.uf2` flashing flow as the Pico 2W
(`make flash-micropython`'s picotool path) — RP2350 boards share a
bootloader protocol, unlike the ESP32-C3's serial one
(`make flash-esp32-c3`). Worth confirming which `make` target this board
actually needs once flashing is attempted; not yet tested.

---

## Open, before flipping this to ✅

- [ ] Confirm the pinout against the physical board (silkscreen or
      continuity check), not just the vendor doc
- [ ] Confirm `IMU_I2C_ID = 1` actually finds the IMU at `0x6A`/`0x6B`
- [ ] Confirm which flash target applies (`flash-micropython` vs. a new one)
- [ ] Onboard-LED / `HEARTBEAT_PIN` alias, if one exists on this board
      (XIAO C3 has none; unconfirmed here)
