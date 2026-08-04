# Raspberry Pi Pico 2W

**Status: ✅ Verified** — wired and running as the V1 dev rig.

Parts context: `docs/hardware.md` (voltage compatibility, parts list).

---

## Physical pinout

```
                    USB
              ┌─────────┐
    GP0   1 ──┤         ├── 40  VBUS    ← 5V from USB → LED VCC
    GP1   2 ──┤         ├── 39  VSYS
    GND   3 ──┤         ├── 38  GND     ← LED GND
    GP2   4 ──┤         ├── 37  3V3_EN
    GP3   5 ──┤         ├── 36  3V3(OUT)  future sensors
    GP4   6 ──┤         ├── 35  ADC_VREF
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

`►` = assigned V1 LED data pin

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

**Status: ⬜ Proposed** — in hand, not yet physically wired. First bring-up
target (over the XIAO) since this board's already on the breadboard.
Parts/register reference: `docs/hardware.md`. Smoke test:
`micropython/imu_test.py` (`make imu-test`).

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

## Status heartbeat

`HEARTBEAT_PIN = "LED"` — a Pico-2W-only alias routed through the onboard CYW43
WiFi chip, **not** a plain GPIO. This is the *only* board where the string
`"LED"` works; every other board needs a GPIO number or `None`.

---

## Pins reserved for V2 (not yet wired)

| GPIO | Purpose |
|---|---|
| GP0/1 | I2C0 SDA/SCL → DS3231 RTC, LSM6DSV16X IMU (in hand — see the wiring section above; "MPU-6050" here was an early V2-planning placeholder, corrected once the actual part was picked) |
| GP2/3 | I2C1 SDA/SCL → QMC5883L magnetometer |
| GP4/5 | SPI → PN532 NFC module |
| GP10/11/12/13 | SPI → e-ink display (Waveshare 2.9") |
| GP16 | LDR (ADC via voltage divider) |
| GP6 | WS2812B data (V1 and V2) |

_Pin assignments not final — update when V2 wiring begins._
