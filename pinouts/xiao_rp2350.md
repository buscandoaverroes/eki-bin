# Seeed XIAO RP2350

**Status: ✅ Verified** — bench-confirmed 2026-08-22 on real hardware:
LED strip, LSM6DSV16X IMU, and DS3231 RTC all working, with both I²C
devices sharing one bus. Pin table originally transcribed from
[Seeed's docs](https://github.com/Seeed-Studio/OSHW-XIAO-Series/blob/main/document/SeeedStudio_XIAO_RP2350/XIAO-RP2350.md)
and since exercised in practice.

### Confirmed working values

| Function | Pin | GPIO | Notes |
|---|---|---|---|
| WS2812B data | D7 | **1** | `led_test.py DATA_PIN = 1`; all 8 LEDs cycle |
| I²C SDA | D4 | **6** | shared by IMU + RTC |
| I²C SCL | D5 | **7** | shared by IMU + RTC |
| I²C bus ID | — | **1** | ⚠ **not 0** — see below |

Scan with both devices attached shows `0x68` (DS3231) and `0x6B`
(LSM6DSV16X) together — no address conflict, neither loading the bus.

⚠ **`I2C_ID = 1` is the trap on this board**, and it cost a full
bring-up session. See the section below; `make i2c-scan` now determines
it automatically if you ever need to re-derive it.

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

This board has **two** buttons — **B** (BOOT) and **R** (RESET) — so the
usual unplug dance is unnecessary:

```
   hold B  →  tap R  →  release B          ← no cable handling
```

The cable can stay connected throughout. The older method still works and is
the only option on a board without a reset button:

```
   hold B  →  connect USB  →  release B
```

⚠ Worth knowing before a debugging session: an entire day of BOOTSEL entries
on 2026-08-23/24 used the unplug method because only that one was written
down here. Every power cycle it caused was also a chance for a flash write to
be interrupted — the mechanism behind `docs/insights.md` §13's filesystem
corruptions.

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
- [x] **Onboard-LED alias — confirmed 2026-08-23.** `machine.Pin` accepts
  named board aliases; the full set on this port is:
  `LED`, `NEOPIXEL`, `NEOPIXEL_POWER`, `BAT_ADC`, `BAT_ADC_EN`, `D0`–`D18`.
  Enumerate them any time with:
  `print([n for n in dir(Pin.board) if not n.startswith('_')])`
  - **`LED` is ACTIVE-LOW** — `led.off()` lights it (bright yellow),
    `led.on()` extinguishes it. Verified at the REPL, not assumed.
  - **`NEOPIXEL` — onboard addressable RGB LED. ✅ CONFIRMED WORKING
    2026-08-23** (bright blue at `(0, 0, 40)`). Power-gated by
    `NEOPIXEL_POWER`, which is **active-high** — `.on()` enables it.
    Driven exactly like the external strip:
    ```python
    Pin("NEOPIXEL_POWER", Pin.OUT).on()
    np = NeoPixel(Pin("NEOPIXEL"), 1)
    np[0] = (0, 0, 40); np.write()
    ```
    Significant:
    it's a full-colour status indicator that needs no external strip, which
    is exactly what `docs/contracts/led-status-messages.md` describes and
    has had no hardware to run on. Also relevant to a battery/Qi unit, since
    the power gate means it costs nothing when unused.
  - `BAT_ADC` / `BAT_ADC_EN` suggest onboard battery-voltage sensing —
    unverified, worth a look when the Qi power path is revisited.

## Onboard indicators — THREE of them, only two controllable

Walked through `make onboard-led-test` twice, 2026-09-03. Holding the board
with USB-C at the top:

| # | where | what | software-controllable? |
|---|---|---|---|
| 1 | **left** | user LED, `Pin("LED")`, **ACTIVE-LOW** | ✅ yes |
| 2 | **right** | `NEOPIXEL` (+ `NEOPIXEL_POWER` gate, active-high) | ✅ yes |
| 3 | co-located with #1 | **a very faint RED**, visible only out of the bottle at close range | ❌ **no** |

**#3 is the one that matters for a sealed unit.** It appears roughly **one
minute after power-up**, is unaffected by taps, by `Pin("LED")`, by gating the
NeoPixel, and by anything else firmware has tried. It is the "the LED goes
faint after a few minutes" observation from 2026-08-23 — which was read at the
time as a sagging rail and cost hours of misdiagnosis (`docs/insights.md`
§13). It was never a rail problem; it is simply a third LED.

**Hypothesis: it is the battery-charge indicator, in its no-battery state.**
This board exposes `BAT_ADC` / `BAT_ADC_EN`, so it has charging hardware. A
charger IC with no cell attached typically attempts to charge, times out after
30–60 s, and settles into a fault or standby state — which matches the ~1 min
delay and the complete indifference to firmware exactly. **Not confirmed.**
Cheapest falsification: attach a cell to the battery pads and see whether the
indicator changes behaviour.

**No firmware fix exists either way.** For a unit going into glass the options
are physical, in increasing permanence: opaque tape, a dab of paint, orienting
the board so it faces away from the viewing surface, or desoldering the LED or
its series resistor.

### ⚠ Unresolved: the NeoPixel's RED did not light

In both runs, steps 4–6 drove the NeoPixel red → green → blue. **Green and
blue showed; red showed nothing.** Green and blue working rules out the gate,
the pin and the data path, so this is specific to that channel.

It matters beyond curiosity: `ERROR_COLOR` is red, and
`docs/contracts/led-status-messages.md` earmarks this pixel as the
status channel for a unit with no external strip. **A status indicator that
cannot show the error colour is not a status indicator.**

Worth one targeted re-check before trusting it — at full scale and out of the
bottle, since brown glass passes red well but the faint red of #3 sits right
next to it and could mask a dim result:

```python
from machine import Pin
from neopixel import NeoPixel
Pin("NEOPIXEL_POWER", Pin.OUT).on()
np = NeoPixel(Pin("NEOPIXEL"), 1)
np[0] = (255, 0, 0); np.write()
```

⚠ **The onboard LEDs are NOT a reliable power indicator, despite appearances.**
On 2026-08-23 an apparent "bright red = healthy / faint yellow = sagging rail"
correlation drove a long misdiagnosis. It does not hold: faint yellow was
later observed on a bare, healthy board sitting at the REPL. A GPIO left
high-impedance after reset will glow faintly from leakage, which is the more
likely explanation. **Do not use LED colour as evidence about power** — see
`docs/insights.md` §13 for what that cost.
      (XIAO C3 has none; unconfirmed here)

## shared v1.4 pinout

## Physical pinout (per Seeed's official docs, not yet bench-verified)

```
                 ┌─────────────┐
                 │   USB-C     │
                 └──┬───────┬──┘
  ► D0/A0  ──────────┤       ├────────── 5V [to 8led strip]
     D1/A1 ──────────┤       ├────────── GND [to gnd rail]
     D2/A2 ──────────┤ RP2350├────────── 3V3 [to power rail]
     D3    ──────────┤       ├────────── D10 / GPIO3 
     D4/SDA──────────┤       ├────────── D9  / GPIO4 
     D5/SCL──────────┤       ├────────── D8  / GPIO2 
     D6/TX ──────────┤       ├────────── D7  / GPIO1 
                      └───────┘
```

8led strip

```
[] GND [to gnd rail]
[] DIN [to d7 on xiao]
[] 5Vdc [xiao 5v pin directly]
```


ds3231

```
[] VIN (3v3) [to power rail]
[] GND [to gnd rail]
[] SCL 
[] SDA
```

IMU

```
[] GND [to gnd rail]
[] VIN (3v3) [to power rail]
[] SDA
[] SCL
```


power (3v3) rail

```
[] bridge to 3v3 [to xiao 3v3]
[] to imu
[] to ds3231 
```

gnd rail

```
[] bridge to xiao gnd
[] to imu
[] to ds3231
[] to led strip
```
