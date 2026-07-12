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
proposed).

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
