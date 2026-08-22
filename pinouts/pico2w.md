# Raspberry Pi Pico 2W

**Status: ✅ Verified** — wired and running as the V1 dev rig.

Parts context: `docs/hardware.md` (voltage compatibility, parts list).

---

## Physical pinout

```
                    USB
              ┌─────────┐
  ◆ GP0   1 ──┤         ├── 40  VBUS    ← 5V from USB → LED VCC
  ◆ GP1   2 ──┤         ├── 39  VSYS
    GND   3 ──┤         ├── 38  GND     ← shared GND rail (LED + IMU)
    GP2   4 ──┤         ├── 37  3V3_EN
    GP3   5 ──┤         ├── 36  3V3(OUT)  ◆ IMU VCC (NOT the LED — 5V
    GP4   6 ──┤         ├── 35  ADC_VREF     would exceed its rating)
    GP5   7 ──┤         ├── 34  GP28
    GND   8 ──┤         ├── 33  GND
  ► GP6   9 ──┤         ├── 32  GP27
    GP7  10 ──┤         ├── 31  GP26
    GP8  11 ──┤         ├── 30  RUN
    GP9  12 ──┤         ├── 29  GP22
    GND  13 ──┤         ├── 28  GND
   GP10  14 ──┤         ├── 27  GP21
   GP11  15 ──┤         ├── 26  GP20
   GP12  16 ──┤         ├── 25  GP19
   GP13  17 ──┤         ├── 24  GP18
    GND  18 ──┤         ├── 23  GND
   GP14  19 ──┤         ├── 22  GP17
   GP15  20 ──┤         ├── 21  GP16
              └─────────┘
```

`►` = assigned V1 LED data pin. `◆` = assigned IMU pins (I2C0 SDA/SCL +
its own 3.3V rail) — both boards now wired simultaneously on this build,
see the combined wiring section below for the power-rail safety note.

---

## Wiring — AE-WS2812B-STICK8

Only 3 connections needed:

| Pico 2W | Physical pin | GPIO (for `config.py`) | → | LED stick pad |
|---|---|---|---|---|
| VBUS | 40 | — | → | VCC (5V) |
| GND | 38 | — | → | GND |
| GP6 | 9 | `6` | → | DIN |

DOUT on the stick is unused (no chaining).

```
Pico 2W                AE-WS2812B-STICK8
─────────                ─────────────────
VBUS (pin 40) ─────────── VCC
GND  (pin 38) ─────────── GND
GP6  (pin  9) ─────────── DIN
                           DOUT (unused)
```

**`config.py` values**: `LED_PIN = 6`

## Wiring — AE-LSM6DSV16X (IMU)

**Status: ✅ Verified** — wired and extensively validated across
`docs/contracts/gesture-envelope.md`'s tap/flick/orientation testing (V1
scope now, not just a future-sensor placeholder — see that doc). Parts/
register reference: `docs/hardware.md`. Smoke test: `micropython/
imu_test.py` (`make imu-test`).

`GP0`/`GP1` is I²C0 on this board — fixed by the RP2350's silicon, not an
arbitrary choice (see the "Pins reserved for V2" table below, which already
had this reserved before the sensor itself was picked).

| Pico 2W | Physical pin | GPIO | → | AE-LSM6DSV16X |
|---|---|---|---|---|
| 3V3(OUT) | 36 | — | → | VCC |
| GND | 38 | — | → | GND |
| GP0 | 1 | `0` | → | SDA (blue) |
| GP1 | 2 | `1` | → | SCL (yellow) |

`imu_test.py`'s constants: `SDA_PIN = 0`, `SCL_PIN = 1`, `I2C_ID = 0`.

## Wiring — DS3231 RTC (Adafruit #3013)

**Status: ✅ Verified** — confirmed 2026-08-22: `make rtc-test` finds the
device at `0x68`, reads and writes time correctly, and battery backup
holds across a physical disconnect (`docs/hardware.md` § Bring-up log —
DS3231).
Part evaluation (voltage, address, size, battery): `docs/hardware.md`
§ DS3231.

Four wires. `GP0`/`GP1` is I²C0 — **the same bus the IMU already uses**,
which is correct and intended: I²C is a bus, and the DS3231's address
(`0x68`) doesn't collide with the LSM6DSV16X's (`0x6A`/`0x6B`). A scan
with both attached should list **both** addresses, which is itself a
useful confirmation that neither is loading the bus.

| Pico 2W | Physical pin | GPIO | → | DS3231 |
|---|---|---|---|---|
| **3V3(OUT)** | **36** | — | → | **VIN** ⚠ see below |
| GND | 38 | — | → | GND |
| GP0 | 1 | `0` | → | SDA |
| GP1 | 2 | `1` | → | SCL |

### ⚠ 3V3 only — NOT 5V, and not for the usual reason

The DS3231 chip itself runs on 2.3–5.5V, so 5V looks harmless. It isn't:
**this breakout's SCL and SDA carry 10K pull-ups tied to VIN.** Power it
from VBUS and those pull-ups hold the I²C lines at 5V — into RP2350 GPIOs
that are **not 5V-tolerant**. That damages the Pico rather than merely
failing to work.

Same rule as the IMU (`pin 36, never pin 40`), but note the reasoning
differs: the LSM6DSV16X is simply not 5V-rated, whereas the DS3231 would
*survive* 5V and take the microcontroller with it.

### Unused pins on the breakout

| Pin | Why it's unused here |
|---|---|
| `SQW` | Square-wave / alarm interrupt output. Not needed to read time. Worth remembering if the display ever wants an interrupt-driven wake instead of polling. |
| `32K` | 32.768kHz reference output — for clocking other hardware. Nothing here needs it. |
| `RST` | Reset / power-fail indicator. Not needed. |

### Battery

**CR1220**, and it is **not included** with the breakout — see
`docs/hardware.md` § DS3231. Without it the RTC loses time on every power
cycle, which is precisely the problem it was bought to solve.

## Wiring — IMU + LED together (combined breadboard build)

Both wired simultaneously on this board for full IMU + LED testing (see
`docs/contracts/gesture-envelope.md` §11's jolt/UX work) — GPIO pins don't
conflict (IMU: GP0/GP1, LED: GP6), so this is just the two sections above
combined onto one breadboard, plus one rule that matters:

| Signal | Pico 2W pin | Shared between the two? |
|---|---|---|
| GND | 38 | ✅ **yes** — normal, both devices need it, common ground rail |
| IMU VCC | 3V3(OUT), pin 36 | ❌ **IMU only** — the LSM6DSV16X isn't 5V-tolerant |
| LED VCC | VBUS, pin 40 (5V) | ❌ **LED only** — needs actual 5V, and would over-volt the IMU |
| IMU SDA/SCL | GP0 / GP1 | — |
| LED DIN | GP6 | — |

**Do not bridge the two power rails** — 3V3(OUT) and VBUS are different
voltages feeding devices with different tolerances. GND is the only rail
meant to be common between them.

## Status heartbeat

`HEARTBEAT_PIN = "LED"` — a Pico-2W-only alias routed through the onboard CYW43
WiFi chip, **not** a plain GPIO. This is the *only* board where the string
`"LED"` works; every other board needs a GPIO number or `None`.

---

## Pins reserved for V2 (not yet wired)

| GPIO | Purpose |
|---|---|
| GP0/1 | I2C0 SDA/SCL → DS3231 RTC (V2), and **already actively wired for the LSM6DSV16X IMU in V1** (see the wiring section above) — not just a V2 reservation anymore |
| GP2/3 | I2C1 SDA/SCL → QMC5883L magnetometer |
| GP4/5 | SPI → PN532 NFC module |
| GP10/11/12/13 | SPI → e-ink display (Waveshare 2.9") |
| GP16 | LDR (ADC via voltage divider) |
| GP6 | WS2812B data (V1 and V2) |

_Pin assignments not final — update when V2 wiring begins._
