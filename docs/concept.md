# eki-bin — Concept Note
_Living document. Core intent: ambient, natural, non-digital-feeling information display._

> **Name:** eki-bin (駅瓶) — "station jar." 瓶 (*bin*) = jar/bottle; rhymes with
> eki-ben (駅弁, the station bento). The jar is the whole idea.

---

## The Problem
Train departure times are known in advance but hard to access quickly. Phones require too many steps. The gap between "needing to know" and "knowing" causes missed trains.

## The Design Principle
**Information primacy without digital interface.** Like a clock, thermometer, or sundial — the data is simply *present* in the environment. Glanceable, ambient, non-invasive. No screen to unlock, no app to open.

---

## Form Factor
A frosted glass jar or apothecary bottle sitting on a shelf, on a Qi charging pad. Looks like a honey jar or candle. The "reveal" — that it is showing live train data — proves the design point.

---

## Display Strategy (Both)

**LED ring (ambient / distance)**
- WS2812B 12-LED ring inside the jar
- Glowing arc = time until next train. Large arc = comfortable. Small arc = go now.
- Two arcs simultaneously: bright for next train, dim for the one after
- Color: calm blue-green → amber → urgent red as departure approaches
- Brightness auto-dims at night via LDR (light dependent resistor)
- Readable from across the room

**E-ink panel (informational / close)**
- Small e-ink display worn as a "label" on the jar face
- Shows actual departure times: `Next: 14:32 · Then: 14:47`
- Apothecary label aesthetic — looks intentional, not like a gadget
- Zero power cost to maintain; only draws power on update
- Readable when you lean in to confirm

---

## Orientation / Interaction
The jar has **absolute heading awareness** via magnetometer. Rotating the jar on the table changes which mode is active.

- Magnetometer (QMC5883L) sits at the **top of the jar, just inside the cork** — ~30cm from Qi coil to avoid electromagnetic interference
- Qi receiver coil sits at the **base** of the jar interior
- Thin enameled magnet wire runs the length of the jar interior to connect them
- Calibrated once on setup (slow 360° rotation)

**Interaction:** Orient the jar's label toward you → that direction = that mode. No buttons, no gestures, just turning the object. Modes cycle by heading (e.g. four cardinal orientations = four modes).

**IMU (MPU-6050) also present for:**
- Tilt detection (future: flip jar for direction B trains)
- Rotation gesture confirmation animation

---

## Data Architecture
Train schedules are **deterministic** — known in advance, stored locally. No real-time API required.

- Schedule stored as array of minute-of-day values on each NFC station card
- Format: `{ "station": "Shibuya", "direction_a": [427, 435, 443, ...], "direction_b": [429, 437, ...] }`
- Updated by writing a new NFC card (phone app or iOS Shortcut) — a few times a year
- ESP32 reads schedule from card on tap, stores in local flash; calculates "minutes to next departure" from DS3231 RTC time

**Time keeping:** DS3231 dedicated RTC module. Temperature-compensated crystal, drifts <1 minute per year. Set once during initial programming. Coin cell backup maintains time if main battery dies. No WiFi or NTP required.

**Time correction (if ever needed):** Tap phone to jar via NFC — phone writes current Unix timestamp, jar adjusts RTC. Expected frequency: once a year at most.

---

## Input & Configuration — NFC Station Cards

The jar's only "interface" for data input is NFC tap. No app to open, no WiFi credentials, no pairing.

**Station cards** are NTAG213 NFC sticker tags, each carrying one station's full schedule as an NDEF JSON record. Cards live next to the jar — in a small dish, a card holder, or pinned to a noticeboard. Each card is labeled by hand or printed with the station name.

- Tap a card to the jar → schedule loads instantly
- Write new cards with a phone: Android via Web NFC in Chrome (no app); iPhone via iOS Shortcut (one-time setup)
- Tap phone directly to jar for one-off time correction (writes Unix timestamp → jar adjusts RTC)

Turning the jar selects direction. Tapping a card selects station. These are the complete physical inputs.

---

## Power Architecture
- **LiPo battery** (1000–2000mAh) inside jar
- **Qi receiver coil** at jar base, paired with existing Qi charging pad
- **TP4056** charge controller between Qi output and LiPo
- Effectively wall-powered via Qi when jar is on pad; LiPo buffers when picked up
- ESP32 in deep sleep most of the time; wakes every 15–60 seconds to update display
- Average draw ~1.5–2mA in sleep-cycle mode → 40+ days on battery alone if removed from pad

---

## Mode Ideas (Current + Future)
| Orientation | Mode |
|---|---|
| Face forward (default) | Direction A train departures |
| 90° CW | Direction B train departures |
| 180° | (Future) Weather / temperature |
| 90° CCW | (Future) Calendar / next event |

---

## Design Principles
1. **Ambient, not demanding** — information is present, not pushed
2. **Natural materials, hidden technology** — glass, cork, no visible screens or indicators
3. **Analog metaphors** — arc of light = arc of time, orientation = context
4. **Low maintenance** — charge infrequently, update schedule rarely
5. **Extensible** — same object, same interaction language, new data sources
6. **Digitize only on provision** — the device is provisioned digitally (time set, schedule loaded via NFC) then operates entirely in the physical world until intervention is needed again. Daily operation has no digital surface.

---

## Open Questions
- Flexible e-ink sourcing in Japan (would allow label to wrap jar face)
- Whether to use MPU-9250 (combined IMU + magnetometer) vs separate chips
- Cork vs screw-cap jar (cork is more aesthetic; screw cap is more practical for access)
- Best physical form for station card storage next to jar (dish, card holder, etc.)

---

## Key Hardware Decisions (Locked)
- MCU: ESP32-C3 Mini (WiFi dormant; kept as escape hatch only)
- No WiFi in normal operation — replaced entirely by DS3231 + NFC
- DS3231 RTC for timekeeping — set once, <1 min/year drift, coin cell backed
- PN532 NFC module — reads station cards and phone time-sync taps
- NTAG213 NFC sticker tags — one per station, written by phone, tapped to jar
- Qi receiver at base; magnetometer at cork; ~30cm separation
- No solar (marginal indoors; Qi pad is cleaner solution)
- No USB port on jar body (Qi handles charging; no drilling required)
- Gyroscope (MPU-6050 Z-axis) for rotation gesture confirmation
- Magnetometer (QMC5883L) for absolute heading / mode selection
