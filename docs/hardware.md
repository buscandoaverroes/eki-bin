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

**Full-brightness stress test (2026-07-13 follow-up).** Ran `BRIGHTNESS = 1.0`,
full-white-ish 120-LED frame, across the three sources:
- **MacBook USB:** ran, but "like looking at the sun," then macOS threw *"USB
  accessory disabled — unplug the accessory using too much power to re-enable
  USB devices."* i.e. it tripped the host port's overcurrent cutoff. USB barely
  coped.
- **Qi (WCR):** insufficient — a few LEDs lit, then froze/stopped (rail collapse
  under the inrush). Confirms the 800 mA ceiling can't source a bright 120-LED
  frame, as the ~4.8 A worst-case math predicted.
- **Takeaway:** `BRIGHTNESS = 0.15` is already visually "full" for this tape
  (initially mistaken for max) and is the safe, stable ceiling on **both** USB
  and Qi. The real question was never "can it do full white" (it can't) but
  **"what's the stable Qi ceiling"** — and it's ≈0.15 or lower. For 120 LEDs,
  even lower is worth trying. A brightness cap that scales down with LED count
  would turn this from a footgun into a guardrail (parked — `docs/insights.md` §4).

> **Milestone:** everything (XIAO + 120-LED tape + Qi receiver) then placed into a
> wide-mouth glass pitcher and run off the pad — the full "MCU + lights inside,
> powered wirelessly through glass, no visible wire" concept, self-contained, for
> the first time. The core v1.1 hardware thesis, proven.

---

## NFC — ST25DV dynamic tag (v1.x "givable" phase)

**Purpose:** provisioning — tap the jar with an iPhone to load a station
schedule, edit settings, and sync time; firmware reads it over I²C. **Update
(2026-07):** the original "iOS Shortcuts, no custom app" plan is **dead** — bench
testing showed iOS's generic NDEF API breaks on this ISO-15693/Type-5 tag. The
plan is now a minimal first-party iOS app on the low-level ISO-15693 API. Full
findings, decision, and the tag data contract: **`docs/nfc-provisioning.md`**.

**Part:** SparkFun Qwiic Dynamic NFC/RFID Tag — **ST25DV** chip. A *dynamic*
dual-interface tag: I²C to the MCU **and** RF to the phone, sharing one EEPROM —
so the phone writes settings over NFC and the firmware reads them over I²C (and
vice-versa). ISO-15693 / **NFC-Forum Type-5**. ⚠ *Not* Type-2 like the NTAG213
station-card idea. This Type-5-ness is exactly what broke the generic-NDEF path
(see `docs/nfc-provisioning.md` §2) — raw ISO-15693 block access works fine, the
high-level NDEF API doesn't.

**Reference links:**
- Board (Switch Science): <https://ssci.to/8881>
- Arduino library — port register-level I²C from this: <https://github.com/sparkfun/SparkFun_ST25DV64KC_Arduino_Library>
- API reference (ESP32-tested): <https://docs.sparkfun.com/SparkFun_ST25DV64KC_Arduino_Library/api_SFE_ST25DV64KC/>
- Hookup guide: <https://learn.sparkfun.com/tutorials/qwiic-dynamic-nfcrfid-tag-hookup-guide>
- Datasheet **DS13519** — covers the whole ST25DV04KC/16KC/64KC family despite the `04KC` filename: <https://cdn.sparkfun.com/assets/f/5/4/e/d/st25dv04kc-2450072.pdf>
- ST "NFC Tap" app (iOS) — for bare-tag bench validation: <https://apps.apple.com/us/app/nfc-tap/id1278913597>

**MicroPython driver status:** none off-the-shelf. Port register-level I²C access
from the SparkFun Arduino library + DS13519. Minimum viable scope: read/write the
*user EEPROM area* over I²C at factory defaults (unprotected, single memory area)
— skip password protection and configurable memory areas for a personal device.
Out of scope this phase: GPO-interrupt instant-apply, ST25DV Fast Transfer Mode
mailbox.

**Wiring (I²C):** the XIAO ESP32-C3 has **no** Qwiic connector, so hand-wire the
Qwiic board's 4 lines (SDA / SCL / 3V3 / GND) to the XIAO — e.g. a Qwiic-to-male
cable into the breadboard. XIAO I²C pins: **D4 = SDA (GPIO6)**, **D5 = SCL
(GPIO7)** — see `pinouts/xiao_esp32c3.md`. (Same bus that will carry a DS3231 RTC
/ sensors in V2.)

**Physical / RF mounting:** put the tag **near the cork/exterior, not behind
anything metal.** A solid conductive lid substantially attenuates the 13.56 MHz
field (eddy currents); glass and cork are both RF-transparent, so a cork-mounted
tag reads fine — another reason cork is the chosen first closure.

> The firmware **settings hot-reload** design and the **iOS app** (the phone-side
> writer) are firmware/UX, not hardware — they live in `docs/nfc-provisioning.md`,
> along with the tag data contract both sides share.
