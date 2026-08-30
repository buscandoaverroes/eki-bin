# Hardware Memo — eki-bin
_Parts and electrical notes. For pin assignments (what connects to what, per
board), see `pinouts/`._

> **How to read this file.** The table below is **the current build** — what
> to buy and wire if you are making a unit today. Everything after it is the
> **record**: bring-up logs, evaluations, dead ends and open threads, roughly
> in the order they happened. The spiral is deliberate; the answer is at the
> top so you do not have to walk it.

---

## THE CURRENT BUILD (2026-08-25)

| | choice | status |
|---|---|---|
| **MCU** | Seeed XIAO RP2350 | ✅ decided — no radio, which is the point |
| **Firmware** | MicroPython **newer than 2026-04-06** | ⚠ **hard requirement.** Earlier builds size the filesystem larger than the flash and corrupt it — `insights.md` §13. `make doctor` fails such a board. |
| **Clock** | DS3231 (Adafruit #3013) + CR1220 | ✅ in hand, verified, survives power cycle. Drift measured **−0.61 ppm**, within the ±2 ppm spec |
| **IMU** | LSM6DSV16X | ✅ in hand, taps working on hardware |
| **Display** | WS2812B — 8-LED stick (bench), 21-LED strip (jar) | ✅ working. `MARKER_BRIGHTNESS ≥ 0.25`; below that channel matching collapses and neutral reads red (§12) |
| **Power** | Qi / battery / wired | 🔲 **OPEN — the live decision.** See § Battery build below |
| **Vessel** | thick vs mid vs clear brown | 🔲 **OPEN.** Thick is the most beautiful and caps colour at 2–3 lines (§12). This is a product decision, not a detail |
| **I²C** | shared bus, `IMU_I2C_ID = 1`, SDA GP6 / SCL GP7 | ✅ DS3231 `0x68` + IMU `0x6b`, no conflict |

**Two open decisions interact**, which is why neither has been forced: Qi
needs a flat bottom (roughly one bottle in five qualifies), so the power
choice silently constrains the vessel choice — and the vessel now carries a
design consequence (how many lines the palette supports) rather than being
cosmetic.

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

## Bring-up log — 21-LED gift-jar strip, brightness (2026-07-23)

New XIAO ESP32-C3 + WS2812B tape cut to **21 LEDs** for the friend gift build
(v1.4, `ApproachContract` — see `dev-status.md` § V1.4). `make led-test`
confirmed all 21 light on `DATA_PIN=2`. `led_test.py`'s `BRIGHTNESS` is a flat
linear scale with no gamma correction, so these readings are directly
comparable to what `main.py`'s global `BRIGHTNESS` produces at `mult=1.0`:

- **`0.15`–`0.2`** reads as a good "full/max" level — bright enough to read
  clearly, not blinding. Matches the existing `0.15` Qi-safe ceiling from the
  120-LED bring-up above, though this is a much shorter strip so the ceiling
  here is a visual/comfort call, not a power one.
- **`0.005`** is the sweet spot for an idle/"floor" level — `0.01` already
  read as almost too bright. An order of magnitude below the "full" reading.

**Translating to `ApproachContract`'s two-tier brightness:** `FLOOR_BRIGHTNESS`
is a *multiplier* run through `gamma()` (`BRIGHTNESS × FLOOR_BRIGHTNESS^GAMMA`),
not a directly-comparable absolute level like `led_test.py`'s flat scale.
Solving for the bench-preferred `≈0.005` absolute floor at `BRIGHTNESS=0.15`,
default `GAMMA=2.2`: `FLOOR_BRIGHTNESS ≈ 0.21` — the contract's built-in
default of `0.05` is roughly 10× dimmer than this and was not the right
starting point. `config_friend1.py` uses the corrected `0.21` starting value;
still expect live retuning once mounted in the actual jar (diffusion changes
perception).

**LED orientation (2026-07-23 follow-up):** originally planned downward-facing
(max refraction off the counter/base — see `dev-status.md` § V1.4). Tested
both ways in the actual **brown glass bottle**; **face-up reads better** —
the opposite of the original plan. Noted here since it's a plan reversal, not
just a confirmation.

**Brown bottle colour filtering (2026-07-23):** the bottle glass itself
noticeably shifts perceived colour — confirmed in the actual jar, not just on
open bench:

| Rendered colour | Reads as, through the brown glass |
|---|---|
| White (`ANCHOR_COLOR`) | Soft orange-white |
| Forest green (`LINE_COLOR`) | Yellow-green |
| Dim neutral gray (`FLOOR_COLOR`) | Yellow |

⚠ **That last row was mis-attributed — corrected 2026-08-18.** The glass is
not why a dim neutral reads yellow. At `BRIGHTNESS 0.15 × MARKER_BRIGHTNESS
0.15`, `MARKER_COLOR (80,80,80)` renders as **`(1,1,1)`** — one PWM step of
255 per channel — and at that level WS2812B channel matching collapses
outright: the R/G/B dies have different efficiencies near minimum drive, so
equal values stop meaning neutral and skew warm. Reproduced with `DITHER =
False` and on a strip `led-test` proved uniform, so it is neither dithering
nor a dead pixel. **General rule: below roughly 4-5/255 per channel, hue is
not controllable on this hardware.** See `docs/insights.md` §12.

Read as a pleasant effect, not a defect — "that's actually not bad." Two
follow-on findings from the same session:

- **The added darkness from the brown glass means brightness can go up.**
  A clear/bench readout of "too bright" doesn't hold once diffused through
  brown glass — `BRIGHTNESS` moved from the bench-tuned `0.15` up toward
  `0.5`, `ANCHOR_BRIGHTNESS` from `1.6` toward `2.0`, in the actual jar. All
  bench brightness numbers above are a clear-air starting point, not the
  in-jar final values — confirms diffusion/perception in the real jar is the
  final tuning authority, same lesson `docs/insights.md` §3/§5 already drew
  from the V1 jar-diffusion assessment.
- **Parked idea:** 2–3 "bin filter" colour presets that pre-shift the
  rendered RGB to compensate for (or lean into) this bottle's amber cast —
  not built, just noted as worth a future look if colour fidelity through
  glass becomes a priority again (e.g. for a different, less-tinted bottle).

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

---

## DS3231 RTC — in hand, on the breadboard (evaluated 2026-08-18, bought + wired 2026-08-20)

Bring-up: `micropython/rtc_test.py` (`make rtc-test`). Pinout:
`pinouts/pico2w.md` § DS3231. Evaluation below (part choice, voltage,
battery) stands as written — nothing in it changed by actually buying the
part; only its status did.

**Candidate:** Adafruit **DS3231 Precision RTC Breakout**, product
[#3013](https://www.adafruit.com/product/3013). Specs below verified
against Adafruit's own product page and pinout guide, not assumed.

| Property | Value | Verdict for this build |
|---|---|---|
| Supply / logic | **2.3–5.5V**, "no regulator or level shifter for 3.3V or 5V logic" | ✅ drives straight off the XIAO's 3V3, same rail as the IMU |
| Interface | I²C | ✅ shares SDA/SCL with the IMU |
| I²C address | **0x68** (fixed in the DS3231 silicon) | ✅ **no conflict** — the LSM6DSV16X sits at 0x6A/0x6B |
| Onboard pull-ups | 10K on both SCL and SDA | ⚠ see note below |
| Size | **23 × 17.6 × 7.2 mm** | ✅ comparable to the IMU breakout (24.5 × 17 mm) — if that fits an enclosure, this should too. Height (7.2mm, coin cell included) is the new dimension to check |
| Backup cell | CR1220, **not included** | ⚠ order separately — it's the entire point (survives power loss, unlike the ESP32's internal RTC) |
| STEMMA QT / Qwiic | **No** on #3013 | see below |

**⚠ Two sets of pull-ups on one bus.** The IMU breakout brings its own,
and these are 10K — in parallel that's ~5K, which is comfortably inside
I²C spec at 400kHz (roughly 1K–10K is the usable band), so this is a note
rather than a problem. It would only matter if a third pulled-up device
joined the same bus.

### Chain topology (what actually matters) vs. connector choice

**Take #3013 for this build.** An earlier version of this note recommended
#5188 (the STEMMA QT variant) — that was optimizing for the wrong
constraint, corrected here:

- **The benefit is the TOPOLOGY, not the connector.** What avoids a 3-way
  GND splice is routing `RTC → IMU → XIAO` instead of wiring RTC and IMU
  each back to the board. **Soldered wire achieves that identically to a
  QT cable.** #3013 gets the same win.
- QT's real advantage is *solderless, reversible* assembly — and this
  build solders everything, because header pins don't fit through the
  bottle. That's a benefit there's no way to spend.
- **Soldered is arguably safer here.** JST SH is a friction fit, and this
  device's input method is *being tapped*. Intermittent `OSError EIO` from
  a jostled connection has already cost real debugging time
  (`docs/insights.md` §10). A plug-in connector inside an object designed
  to be knocked invites that failure mode permanently; a solder joint
  can't unseat.

So: **#3013 + CR1220, no QT cables.** The QT route below stays documented
for a future solderless/breadboard rig, where it's genuinely the nicer
option.

#### Wiring it (either connector choice)

I²C is a **bus**: every device sits in *parallel* on the same SDA/SCL,
distinguished purely by address (RTC 0x68, IMU 0x6A/0x6B). "Daisy-chaining"
is not electrically a chain — Qwiic/STEMMA QT boards simply carry **two
sockets wired straight through to each other**, so a cable in from upstream
and another out to the next device taps the same bus. Nothing active, no
hub. Qwiic (SparkFun) and STEMMA QT (Adafruit) are the same 4-pin JST SH
1.0mm connector (GND/3.3V/SDA/SCL) and interoperate; the AE-LSM6DSV16X's
socket is compatible.

```
XIAO ──(A)── IMU ──(B)── DS3231
        ↑         ↑
        └─────────┴── soldered wire (#3013) or QT cable (#5188)
```

| Link | Soldered build (**#3013 — recommended**) | Solderless (#5188 + QT) |
|---|---|---|
| **A** XIAO → IMU | 4 wires to the IMU's through-holes: `3V3→VCC`, `GND→GND`, `D4→SDA`, `D5→SCL` | QT plug one end, bare wire the other (cut a QT-to-QT cable, or reuse the Qwiic lead Akizuki ships with the IMU) |
| **B** IMU → RTC | 4 wires, hole to hole: `SDA↔SDA`, `SCL↔SCL`, `VCC↔VCC`, `GND↔GND` | QT-to-QT cable, plug in |

Either way the XIAO only ever sees **four** I²C wires — the IMU is the
junction. That's the whole point.

**Order (soldered):** 1× DS3231 #3013, 1× CR1220. No cables needed.
**Order (solderless):** 1× #5188, 2× QT-to-QT cable (cut one for Link A),
1× CR1220.

⚠ **Buy 50–100mm, not 300mm.** Switch Science's own listing warns the
300mm cable is marginal above 400kHz — and `main.py` runs the bus at
exactly `freq=400000`. Two of them is 600mm of bus capacitance on a build
that has *already* produced intermittent `OSError EIO` (see
`docs/insights.md` §10). Inside a bottle, 50–100mm is ample.

**What the chain buys, stated accurately:** it takes GND from a **3-way
splice down to 2-way** (LED strip + chain, instead of strip + IMU + RTC)
and cuts the I²C run from eight wires to four. It does **not** eliminate
the splice — the LED strip still needs its own GND straight to the pad
(see § Build technique). Keep I²C on thin wire (0.3sq / ~28AWG is right
for signalling and the RTC's trickle draw) and leave the strip its own
thicker 5V/GND run — the mixed-gauge rule in § Build technique.

**Search terms (JP):** `Qwiic ケーブル` / `STEMMA QT ケーブル` /
`JST SH 1.0mm 4ピン ケーブル` / `Qwiic 変換ケーブル` /
`DS3231 モジュール` / `リアルタイムクロック モジュール`.
Shops: スイッチサイエンス (best for Adafruit/SparkFun stock), 秋月電子通商,
千石電商, マルツ. ⚠ Seeed's own **Grove** (`グローブ`) connector is 2.0mm
pitch and **does not mate with Qwiic** — search `Grove - Qwiic 変換` if you
ever need to bridge the two.

**Pull-ups compound down a chain:** each QT board brings its own. Two 10K
sets → 5K, three → 3.3K, four → 2.5K. Fine at two or three, over-driven by
four or five; many boards have a solder jumper to cut theirs.

### Bring-up log — DS3231 (2026-08-22)

Confirmed working on the Pico 2W breadboard via `make rtc-test`. Three
findings, all from deliberately breaking things:

**1. A sagging VIN makes the chip silently invisible, and the battery
hides it.** Initial symptom was a completely empty I²C scan on pins
`imu_test.py` had *just* proven good. Cause: the DS3231 switches to VBAT
when V<sub>CC</sub> drops below the power-fail threshold (~2.575V), and
**its I²C interface is disabled on battery power**. So a
high-resistance VIN connection yields a chip that is alive, keeping
perfect time, and totally absent from the bus. Pulling the CR1220 made it
appear instantly — which also means: *if removing the battery makes the
device appear, VIN is sagging below ~2.6V*, a real connection fault
dropping most of a volt, not a slightly-loose clip.

**2. Contact quality is directly observable.** Pressing the unsoldered
board firmly onto header pins gave clean reads; releasing halfway
produced `EIO` within two samples. I²C either transacts or it doesn't —
**any** failure rate here means marginal contact, never a flaky chip.

**3. Without a battery, power loss resets the clock to `2000-01-01`** —
observed directly when the connection dropped mid-run. That's the
factory epoch, and it's exactly the failure the CR1220 exists to prevent.
A useful sanity anchor: a DS3231 reading the year 2000 has lost power
with no working backup.

**Battery backup: ✅ confirmed.** The board was disconnected, physically
moved, and reconnected ~5 minutes later with the cell installed; the
oscillator-stop flag was still **clear** on return, proving the
oscillator never stopped. Note the OSF is the *only* thing that proved
this — the time readback in that same run had been overwritten by the
sync step, so it showed a time that had just been written rather than one
that had survived. `rtc_test.py` now warns when it is about to overwrite
a chip whose OSF is already clear.

**Confirmed on a second board (2026-08-22).** Repeated on the XIAO RP2350
with the **IMU on the same bus**: a scan lists `0x68` and `0x6B` together,
neither loading the other, and the battery-backup test passed there too
(OSF clear across a disconnect, counted time matching wall clock). So the
shared-I²C plan `pinouts/pico2w.md` reserved GP0/GP1 for years ago holds
in practice, on the board intended for production.

⚠ That board needs **`I2C_ID = 1`**, not 0 — its labeled D4/D5 are
GP6/GP7, which sit on I²C1. Cost a full session before `make i2c-scan`
existed to derive it automatically.

**Production implication:** none of the above is a concern once soldered.
The chip prefers V<sub>CC</sub> whenever it is healthy, so with a solid
3.3V feed the battery stays dormant and I²C is always live. The battery
only takes over when main power is genuinely gone — at which point
nothing is reading the bus anyway.

### CR1220 — the backup cell (not included)

`CR1220` is an **IEC designation, not a brand or a regional name**, and it
encodes the dimensions: **12mm diameter × 2.0mm height**, 3V lithium. The
same code is used in Japan — no translation needed when ordering.

⚠ **Neighbouring sizes fit the holder badly or not at all**, and the naming
makes them easy to confuse:

| Code | Size | Note |
|---|---|---|
| **CR1220** | 12 × 2.0mm | ✅ what this board takes |
| CR1225 | 12 × 2.5mm | Same diameter, 0.5mm taller — may not seat |
| CR2032 | 20 × 3.2mm | The ubiquitous one. **Will not fit** — nearly twice the diameter |

**Sourcing in Japan is easy** — Panasonic, Maxell and Sony all make them
domestically. Home centres, Don Quijote, and electronics shops
(秋月電子通商, 千石電商) all carry them; 100-yen shops sometimes do.
Search terms: `CR1220 リチウム電池`, `コイン電池 CR1220`, or
`ボタン電池 CR1220` — both コイン電池 and ボタン電池 are used for this class.

**Expected life:** the DS3231 draws roughly 0.84µA on battery while
timekeeping, against a CR1220's ~35-40mAh. That's several years of pure
arithmetic; self-discharge, not the load, becomes the limit. Call it 3-5
years, i.e. replace it when the jar starts showing the wrong time, not on
a schedule.

**BOM note that cuts in the DS3231's favour:** the SRAM pressure driving
the XIAO-C3 → S3/C6 upgrade (`docs/insights.md` §11) exists *because of
WiFi*. Adding a DS3231 removes the reason to run WiFi at all, so the
extra cost of the roomier board is **partially offset by no longer
needing it** — the two decisions are coupled, not independent line items.
Weigh them together.

## IMU — LSM6DSV16X (wake/sleep interaction layer)

**Purpose:** tap-gesture detection — see `docs/contracts/gesture-envelope.md`
(the current design; supersedes `wake-interaction.md`'s original
multi-gesture plan). **In hand as of 2026-08-03**, and as of 2026-08-16
**wired and extensively validated on the Pico 2W** — real recognizer, real
LED response, not the `_imu_tap_detected()` stub `wake-interaction.md`
describes. Wiring: `pinouts/pico2w.md` (including combined IMU+LED wiring
and its 3.3V/5V power-rail warning). Bring-up: `micropython/imu_test.py`.
Not yet wired on the XIAO — that's the pending next step.

**Part:** ST **LSM6DSV16X** — 6-axis (3-axis accelerometer + 3-axis
gyroscope, no magnetometer). Bought as Akizuki's **AE-LSM6DSV16X** breakout
board (g130950), *not* the bare LGA14L chip (g130032, same silicon,
3×2.5mm, not hand-solderable — see `docs/contracts/wake-interaction.md`'s
"IMU brainstorm" origin for that comparison). Breakout is 24.5×17mm,
through-hole headers + a Qwiic-compliant connector; arrived with both a
Qwiic-style clip/jumper cable **and** loose header pins to solder if
preferred. I²C, SPI, and MIPI I3C capable — this project uses I²C only,
same bus already earmarked for a future DS3231 RTC and shared (so far) with
nothing else currently wired.

Notable but **deliberately unused so far**: the chip has an onboard Machine
Learning Core / Finite State Machine that can do gesture/tap recognition
*inside the sensor itself*, independent of the host MCU. `wake-interaction.md`
explicitly chose plain polled reads + software threshold logic over this for
the first pass — simpler, and this project isn't chasing deep-sleep battery
life where the MLC/FSM's power savings would actually matter. Worth
revisiting if either of those change.

**Reference links:**
- Board (Akizuki): <https://akizukidenshi.com/catalog/g/g130950/>
- Bare chip, for comparison (not what was bought): <https://akizukidenshi.com/catalog/g/g130032/>
- ST product page: <https://www.st.com/en/mems-and-sensors/lsm6dsv16x.html>
- ST's own register-level driver source (used to verify every hex value
  below — not guessed): <https://github.com/STMicroelectronics/lsm6dsv16x-pid/blob/master/lsm6dsv16x_reg.h>

**Register facts** (verified against the driver source above, not the
Akizuki product page — it doesn't state these):
- WHO_AM_I register `0x0F`, expected value `0x70`
- 7-bit I²C address is **`0x6A`** (SA0/SDO strapped low) or **`0x6B`**
  (strapped high) — the breakout brings SA0 out as a solder pad, and
  Akizuki's page doesn't say which way it defaults, so `imu_test.py` scans
  the bus rather than assuming one
- `CTRL1` register `0x10`: lower 4 bits select the accelerometer's output
  data rate, bits 4–6 select operating mode. `0x05` = 60Hz in
  high-performance mode (`ODR_OFF`/`0x00` = powered down)
- Accelerometer output: 6 consecutive bytes from `0x28` (`OUTX_L_A`), X/Y/Z
  low+high pairs, little-endian, two's-complement
- Sensitivity at the power-on-default ±2g full scale: 0.061 mg/LSB
  (standard across the whole ST LSM6DS family) — `imu_test.py` uses this for
  an approximate mg readout; it never explicitly sets `FS_XL`

**MicroPython driver status:** none off-the-shelf, same situation the ST25DV
was in. `micropython/imu_test.py` is the bring-up smoke test — scans the
bus, confirms `WHO_AM_I`, enables the accelerometer, and streams X/Y/Z so
you can watch numbers move when you tap or tilt the board. Deliberately
does **not** attempt tap classification itself — that's `main.py`'s job
(`classify_valid_input` / `extract_gesture_features`, real and host-tested
as of 2026-08-16); this script's only job is proving the chip talks.

**Wiring (I²C):** ✅ **done on the Pico 2W** — `GP0`/`GP1` (I²C0), per
`pinouts/pico2w.md`. (That table previously named the reserved sensor
"MPU-6050", an older placeholder from early V2 planning; corrected to
LSM6DSV16X.) ⬜ **Not yet on the XIAO** — planned for `D4`/`D5`
(`GPIO6`/`GPIO7`, same pins already used for the ST25DV above) for the real
gift-jar integration. The smoke test itself is board-agnostic except for two
pin constants at the top of the file — same "SET PER BOARD" pattern
`led_test.py` already uses.

---

## Build technique — wiring the XIAO permanently (2026-08-16)

Notes from planning the permanent XIAO + IMU + LED build. **Technique, not
pin facts** — the pin assignments themselves live in `pinouts/`.

**The one-GND-pad problem.** The XIAO ESP32-C3 breaks out exactly one GND
pad, but the permanent build needs *two* grounds on it (LED strip and IMU;
see `pinouts/pico2w.md`'s combined-wiring section for why GND is the one
rail that's shared and the power rails are not). Two separate joints on one
small pad tends to lift the pad or leave a cold joint when the second is
made.

**Do a twisted splice instead:** strip both ground wires, twist them
together into a single lead, solder the twist so it behaves as one
conductor, heat-shrink it, then make **one** joint from that lead to the
pad. One clean joint on the fragile pad instead of two competing ones.

**Wire gauge — Japanese "sq" notation.** Japanese suppliers size wire in
**sq** = mm² of conductor cross-section, not AWG:

| Japanese | ≈ AWG | Use here |
|---|---|---|
| 0.3sq | ≈ AWG22 | Signal lines (LED DIN, I²C SDA/SCL) — flexible enough not to strain a pad |
| **0.5sq** | ≈ **AWG20** | VCC/GND for a ~20-LED strip. Fine for the current, but **stiff** — a stiff signal wire levers against its solder joint every time the assembly moves |

**Mix gauges deliberately**: thicker for power, thinner for signal. Using
0.5sq for everything is a common instinct and it makes the signal joints
fragile. **Silicone-insulated** stranded wire is worth the small premium
here — it stays flexible, tolerates soldering-iron contact far better than
PVC, and this build has wires that must flex as the assembly goes into an
enclosure.

---

## Battery build: gating the LED rail (2026-08-25)

_Follows from `docs/roadmap.md` § Battery power and `scripts/power_budget.py`.
The whole battery question turns on cutting power to the strip when idle._

### What a load switch is, and why high-side

A load switch is a transistor in the power line, opened and closed by a GPIO
— a relay with no moving parts. The strip's VDD stops being "always 5 V" and
becomes "5 V when the firmware says so".

```
   HIGH-SIDE (correct here)          LOW-SIDE (wrong here)

   +5V ──[P-MOSFET]── strip VDD      +5V ─────────── strip VDD
              │                                          │
            gate ← GPIO                strip GND ──[N-MOSFET]── GND
                                                     │
   strip GND ──────── GND                          gate ← GPIO
```

**Low-side is the easy circuit and the wrong one.** Switch the ground and the
strip's GND floats up; the MCU's data pin is then *above* the strip's local
ground, so current flows in through the WS2812B's input protection diodes.
The strip stays partly powered through its own data line, which is exactly
the leak being eliminated. Switch the **positive** rail instead.

### ⚠ The firmware half nobody mentions

**Gating VDD is not enough. The data pin must also stop driving high.** With
the rail off but DIN held at 3.3 V, current flows through the input ESD diode
into the strip's supply and partially powers it — the same parasitic path, by
another route. Before opening the switch, set `LED_PIN` to input (or drive it
low). This is a firmware change, not a wiring one, and skipping it silently
undoes the hardware.

### Parts to buy — Japanese search terms

Shops: **秋月電子通商** (Akizuki), **千石電商** (Sengoku), **マルツ**,
**スイッチサイエンス**.

| Need | Search for | Notes |
|---|---|---|
| Load-switch IC | 「ロードスイッチ」 / **TCK107AF** (Akizuki [116072](https://akizukidenshi.com/catalog/g/g116072/)) | ⚠ **SOT23-5 — and Akizuki stocks no SOT23 breakout.** See below. |
| Discrete high-side switch *(recommended: all through-hole)* | see circuit below | 2N7000 + a P-channel MOSFET + 3 passives. Breadboardable, no SMD |
| AA holder ×3 | 「電池ボックス 単3 3本」 | AA = **単3形**, AAA = **単4形** |
| AAA holder ×4 | 「電池ボックス 単4 4本」 | |
| Rechargeables | 「ニッケル水素電池」 / eneloop | Flat discharge curve suits a fixed threshold better than alkaline's slope |
| Boost converter *(only for 2-cell)* | 「昇圧DCDCコンバータ」 | Avoidable — 3× or 4× cells clear the WS2812B's 3.5 V minimum without one |

#### The TCK107AF is the right chip in the wrong package

Toshiba TCK107AF, Akizuki's best-selling load switch, is genuinely well
suited: 1.1–5.5 V, 1 A, **110 nA quiescent**, positive logic (a 3.3 V GPIO
drives it directly), **slew-rate control** and **auto-discharge**. Those last
two matter more than they look — slew control ramps the turn-on instead of
stepping it, which is exactly the inrush that browned this board out twice;
auto-discharge actively drains the output so strip capacitance cannot keep it
half-alive.

One catch: **SOT23-5**, and a search of Akizuki's 変換基板 range turns up only
SOP8 / SOP16 / SSOP / TSSOP / MSOP boards — nothing at 0.95 mm, 5–6 pins. So
either hand-solder fine wire to the part (0.95 mm pitch is coarse as SMD goes,
and quite doable with flux and 30 AWG), or take the discrete route below.

Note also its **1 A ceiling**: fine at working brightness (~190 mA), but 21
LEDs at full white is ~1.26 A. That is already a fault condition, but it is
where this part would object to it.

#### All-through-hole alternative — nothing smaller than TO-92

```
       +5V ─────────┬───────────────┐
                    │               │
                   R1 100k        source
                    │          ┌── gate      P-channel MOSFET
        C1 100n ────┤          │      │
                    │          │    drain ───► strip VDD
                  drain ───────┘
              Q1  2N7000        (C1 across gate-source = soft start)
                  source
                    │
                   GND
                    ▲
        GPIO ──R2── gate           R2 = 1k
              1k
```

- **GPIO HIGH** → Q1 conducts → P-gate pulled to GND → Vgs ≈ −5 V → **strip on**
- **GPIO LOW** → Q1 off → R1 pulls P-gate to +5 V → Vgs = 0 → **strip off**

`R1` is what makes the P-MOSFET *fully* off, which a 3.3 V GPIO cannot do on
its own — that is the level-shifting problem in one resistor. `C1` with `R1`
gives roughly a 10 ms turn-on ramp: a poor-man's slew control, and worth
having given the inrush history.

Ask for 「Pチャネル パワーMOSFET」 in TO-220 and 「2N7000」 in TO-92. At ~200 mA
even a mediocre Rds(on) of 0.2 Ω costs 40 mV, so the part choice is
uncritical — buildability matters more than specs here.

### Does this design need WS2812B at all?

Worth asking, because **the ~0.8 mA-per-pixel idle draw is the price of
per-pixel addressability** — an IC inside every LED, powered whenever the rail
is. Three ways out, and they are not equivalent:

| option | position | colour | idle | verdict |
|---|---|---|---|---|
| **WS2812B + load switch** | full | full | ~0 gated | the current plan; the gate is mandatory |
| **Driver IC + passive LEDs** (IS31FL3731, TLC59711, MAX7219) | full | full w/ RGB parts | **µA in shutdown** | technically the best fit for battery. One driver instead of 21 ICs; costs a matrix to wire. |
| **Discrete filament LEDs** | **coarse only** | usually none | ~0 when off | beautiful, but see below |

**Filament LEDs are not a drop-in.** A filament is one light — not
addressable, and typically fixed warm white. Adopting them deletes *both*
signalling channels this design uses: **position means urgency, colour means
line identity** (`docs/contracts/approach-contract.md`). That is not an LED
swap, it is a different product.

There is a real version of the idea though: **several filaments as coarse
position** — say 5, arranged vertically, each on its own PWM channel. You
lose fine position and colour, and gain the Edison-glow aesthetic plus
near-zero idle. Whether that is a downgrade depends on a decision not yet
made: `insights.md` §12 found the most beautiful vessel (thick opaque brown)
caps colour at 2-3 lines anyway. **If colour is already nearly spent as a
channel, trading it for diffusion quality is a much smaller loss than it
sounds.**

The driver-IC route is the one to reach for if the goal is purely battery
life without giving anything up.

### Filament array — the idea worth taking seriously

**⚠ Step zero: measure the forward voltage.** A bare filament with two leads
and no markings is one of three incompatible families, and you cannot tell by
looking:

| family | Vf | note |
|---|---|---|
| hobby / low-voltage | ~3 V | coin cell or 2×AA; what this design needs |
| mid | ~12 V | workable with a small boost |
| **Edison-bulb standard** | **60–100 V** | many dies in series, mains-derived. Needs a boost converter — inefficient on batteries, probably disqualifying |

A ~10 cm filament is long, which *usually* means more dies in series and
higher voltage — but some long ones use parallel strings at 3 V.

Test cheaply, and **always current-limit — never put an LED straight across a
voltage source**:

1. **9 V battery + 1 kΩ in series.** Glows → Vf < 9 V, so it is a low-voltage
   type and the battery plan survives.
2. Nothing at 9 V → high-voltage family.
3. Bench supply with a current limit, ramped from 0, if available.

This one measurement decides whether filaments and batteries can coexist, so
do it before designing anything around them.

#### Circuit — five channels, low-side

Low-side switching is fine here, unlike the WS2812B: there is no shared data
line whose ground reference could float.

```
   V+ ─┬───────┬───────┬───────┬───────┐
       R1      R2      R3      R4      R5     ← current limit, per filament
       │       │       │       │       │
      ▓F1     ▓F2     ▓F3     ▓F4     ▓F5
       │       │       │       │       │
       ├─┐     ├─┐     ├─┐     ├─┐     ├─┐
        Q1      Q2      Q3      Q4      Q5    ← N-MOSFET, 2N7000 / AO3400
       │       │       │       │       │
      GND     GND     GND     GND     GND
       ▲       ▲       ▲       ▲       ▲
     GPIO    GPIO    GPIO    GPIO    GPIO     ← PWM
```

Physically, mapped onto `docs/contracts/approach-contract.md`:

```
      ╭─────────────╮
      │    ▓ F5     │   30+ min away
      │    ▓ F4     │   ~20 min
      │    ▓ F3     │   ~10 min
      │    ▓ F2     │   ~5 min
      │    ▓ F1     │   ANCHOR — leave now
      ╰─────────────╯
```

#### Why "you lose fine position" is weaker than it sounds

With PWM on every channel you can **cross-fade between adjacent filaments** —
a train at 7 minutes lights F2 at 60% and F3 at 40%. Because filaments
diffuse broadly and their glows overlap, that reads as a **continuous**
position rather than five steps. It is the trick a VU meter uses, and the
diffusion that makes the object beautiful is precisely what makes the blend
work.

So five physical filaments plausibly give twenty-plus *perceived* positions.
The channel actually spent is **colour** — and §12 found the most beautiful
vessel takes most of that anyway. **If colour is already nearly exhausted,
trading it for diffusion quality is a far cheaper trade than it appears.**

Untested. The cheapest falsification is two filaments and a PWM sweep: does a
cross-fade read as motion, or as two lamps taking turns?
