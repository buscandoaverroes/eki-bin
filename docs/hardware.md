# Hardware Memo — eki-bin V1
_Breadboard phase. Parts and electrical notes — for pin assignments (what
connects to what, per board), see `pinouts/`._

---

## Parts in hand (V1 breadboard)

| Part | Akizuki code | Description | Notes |
|---|---|---|---|
| Raspberry Pi Pico 2W (with headers) | — | RP2350, ARM Secure, WiFi via CYW43 | MCU |
| AE-WS2812B-STICK8 | [114307](https://akizukidenshi.com/catalog/g/g114307/) | WS2812B 8-LED stick, 51×10mm | Primary display LED for V1 |
| OSTW3535C1A × 4 | [113021](https://akizukidenshi.com/catalog/g/g113021/) | SMD serial RGB LED, 3.5×3.5mm | For ring arrangement; see voltage note |
| AE-27mm-TH | [109674](https://akizukidenshi.com/catalog/g/g109674/) | Round double-sided PCB, 27mm dia | Fits Japanese PET bottle cap — perfect for jar |
| Breadboard | — | Standard 830-point | |
| Jumper wires | — | M-M assortment | |
| USB cable (USB-A to micro) | — | For Pico power + programming | |

---

## ⚠ Voltage compatibility notes

**AE-WS2812B-STICK8 (stick):** VCC = 5V; IO signal min = **2.7V**
→ Pico 3.3V GPIO drives DIN directly. No level shifter needed. ✓

**OSTW3535C1A (individual SMD chips):** VCC = 3.5–5.3V; IO signal min = **3.5V**
→ Pico 3.3V GPIO is **below spec** (3.3 < 3.5).
→ In practice WS2812-family chips often tolerate 3.3V; may work on breadboard.
→ For permanent install, add a 74AHCT125 or SN74HCT245 level shifter (3.3V → 5V).
→ Decision: test first, add shifter if signal is unreliable.

---

## Pin assignments

Moved to `pinouts/` — one file per board, kept in sync with the actual wiring
and `config.py` values. See [pinouts/pico2w.md](../pinouts/pico2w.md) (V1,
verified) and [pinouts/xiao_esp32c3.md](../pinouts/xiao_esp32c3.md) (v1.2,
verified).

---

## AE-27mm-TH round PCB — intended use

27mm diameter, 67 through-holes, 2.54mm pitch, double-sided.
Designed to fit inside a Japanese PET bottle cap — which makes it an excellent
platform for mounting LEDs in a circular arrangement inside the jar.

V1.5 plan: solder OSTW3535C1A SMD chips onto round PCB in a ring formation,
connect to Pico via same GP6 data line. Verify 3.3V IO tolerance before committing.

V2 plan: this PCB or similar becomes the permanent LED ring mount inside the jar.

Reserved V2 GPIO assignments (I2C sensors, NFC, e-ink, LDR): see the table in
[pinouts/pico2w.md](../pinouts/pico2w.md).

---

## Bring-up log — Qi power + WS2812B-4020 tape (2026-07-13)

New parts this session:
- **Seeed XIAO ESP32-C3** — the v1.1/v1.2 MCU (USB-C). Pinout: `pinouts/xiao_esp32c3.md`.
- **WS2812B-4020 tape** (Akiba-LED, 120 LED/m, non-waterproof, 8mm, side-fire) —
  candidate replacement for the 8-LED stick.
- **Qi wireless-charging receiver (WCR)** — bare board, unbranded, 5V/1A in →
  5V/800mA out (USB-C). The v1.1 wireless power path.

Two isolated tests, then combined — all passed.

**1. WCR power delivery (no LEDs yet).** Bare receiver on a Belkin Qi pad,
output → XIAO only. Immediate power-on; the pad's "device detected" indicator lit
just like a phone — i.e. **no foreign-object-detection (FOD) rejection** of the
bare board (a real pre-test risk, now retired). Unaffected with a glass kitchen
plate between pad and receiver (simulating the jar wall).

**2. LED tape continuity + firmware** (USB-C direct to MacBook). Uncut tape off
the factory pigtail; `led_test.py` with `NUM_LEDS` 8 → 120. Full 120-LED colour
cycle + chase ran clean on first try. `DATA_PIN = 2` (XIAO D0/GPIO2) correct as
documented — only `NUM_LEDS` changed.
- *Connector finding:* the factory 3-pin input pigtail exposes 5V/GND usefully,
  but the DIN wire's housing has recessed "innie" contacts an alligator clip
  can't grip. **Fix:** press a male Dupont jumper pin into the hole until it
  seats against the internal contact (a graspable "outie"). Avoids the worse
  risk of clip teeth splaying across two adjacent pins — worst case 5V→DIN while
  powered, which the chip's reverse-connection protection does *not* cover (that
  only handles a fully reversed connector).
- **Do not cut the tape** until a soldering iron is in hand — a fresh mid-tape
  cut exposes bare 4×2mm SMD pads (no housing), too small/fragile for repeated
  clip attachment. Keep testing off the factory pigtail (jumper-pin trick for
  DIN) until ready to solder.

**3. Combined: WCR → XIAO → full 120-LED tape.** Same wiring, power swapped from
MacBook USB to the WCR. Full pattern ran clean both on-pad-direct and
through-glass. No visible brightness sag, flicker, or brownout-reset at 120 LEDs
on any of the three sources (MacBook USB, WCR-direct, WCR-through-glass).

**⚠ Not yet stress-tested:** all three ran at `BRIGHTNESS = 0.15`. The 800 mA WCR
ceiling has **not** been tested against a bright/full-white 120-LED frame
(WS2812B-4020 ≈ 40 mA/LED worst case → ~4.8 A theoretical max, far over 800 mA).
Real in-jar brightness needs a higher-`BRIGHTNESS` follow-up before calling the
WCR sufficient — tracked as an open item in `dev-status.md`.

> **Milestone:** everything (XIAO + 120-LED tape + Qi receiver) then placed into a
> wide-mouth glass pitcher and run off the pad — the full "MCU + lights inside,
> powered wirelessly through glass, no visible wire" concept, self-contained, for
> the first time. The core v1.1 hardware thesis, proven.
