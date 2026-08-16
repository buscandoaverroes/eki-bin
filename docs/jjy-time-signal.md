# JJY time-signal reception — requirements + sourcing memo

_Opened 2026-08-16. **Research memo, nothing bought or built.** Sourcing a
hobbyist-grade module proved harder than expected in a first search, so this
doc exists to capture what we actually need and what to evaluate against —
the candidate table (§5) is deliberately empty, to be filled in as parts
surface._

**Depends on:** `docs/glass-stone-concept.md`. A JJY receiver is only
interesting because a stand has room for one — the ferrite antenna never had a
chance of fitting a bottle neck.

---

## 1. Why we want this

The jar's timekeeping story currently has exactly one recurring phone
dependency left. From `docs/concept.md`:

> **Time correction (if ever needed):** Tap phone to jar via NFC — phone writes
> current Unix timestamp, jar adjusts RTC. Expected frequency: once a year at most.

A DS3231 drifts <1 min/year, so once a year is genuinely rare — but it is
still a phone, an app, and a provisioning ritual that has to keep working for
the life of the object. And "once a year at most" is doing quiet work in that
sentence: it assumes the RTC is *already correct*, which means it still has to
be set correctly at least once, by something.

JJY makes time **passive and self-correcting**: the device listens to a
national time broadcast and sets itself, forever, with no input from anyone.
This is not a new idea competing with a locked decision — it is the *cleanest
possible* expression of two principles this project already holds:

- `docs/concept.md` § Key Hardware Decisions: **"No WiFi in normal operation."**
- `docs/concept.md` § Design Principles #6: **"Digitize only on provision."**
  JJY removes time from the provisioning surface entirely. (Note this is
  `concept.md`'s numbering — `design-principles.md` has its own separate list
  where #6 is the two-stage pipeline.)

Every consumer 電波時計 (radio-controlled clock) in Japan already does exactly
this, so the ambient-object precedent is total: a wall clock that silently
knows the right time is the most ordinary object imaginable, which is precisely
the register eki-bin aims for.

---

## 2. What JJY actually is

A longwave time-signal broadcast operated by **NICT** (National Institute of
Information and Communications Technology), transmitted from two sites:

| Frequency | Transmitter | Region served |
|---|---|---|
| **40 kHz** | Ōtakadoya-yama (Fukushima) | Eastern / northern Japan |
| **60 kHz** | Hagane-yama (Kyushu, Fukuoka/Saga border) | Western / southern Japan |

Most of Honshu can receive at least one; many commercial clocks support both
and pick whichever is stronger. **Which frequency to target is a
location-dependent decision** — confirm against the deployment location before
buying a single-frequency module.

**Signal format:** amplitude-modulated carrier, **1 bit per second, 60-second
frame**. Bits are encoded by pulse width (how long the carrier is attenuated
at the start of each second). The frame carries minute, hour, day-of-year,
year, and day-of-week, plus parity and marker bits.

**Consequences that matter for firmware design:**
- **A full minute is the absolute minimum to read the time.** In practice
  you want two consecutive agreeing frames before trusting a value.
- Real-world acquisition can take **several minutes**, and can fail entirely
  in a bad location or at a bad time of day (reception is typically better at
  night — longwave propagation changes after dark).
- Therefore JJY is a **corrector, not a clock.** The architecture stays
  "DS3231 RTC is the timebase; JJY disciplines it when a read succeeds." The
  RTC is not optional — it is what makes acquisition failure a non-event.
  This is the same design every commercial radio clock uses.

---

## 3. What we need from a module

We want a **receiver module**, not a bare IC and not a complete clock. The
module's job is: demodulate the AM carrier and present a clean digital pulse
train (the 1-bit-per-second waveform) on a single output pin. **The MCU decodes
the time code in firmware** — this is a modest amount of code, well within
scope, and there are many published reference implementations of JJY decoding.

Evaluation checklist:

| Requirement | Why | Notes |
|---|---|---|
| **Ferrite bar antenna included** | The antenna is the hard part; a module without one is not a solution | Typically 30–40mm. Physically the biggest single component — drives the stand's internal volume budget |
| **3.3V operation** | Matches XIAO/Pico logic; avoids a level shifter | Some modules are 1.5–5V tolerant; confirm |
| **Digital demodulated output** | We want a pulse train on a GPIO, not raw RF | Often labelled TCO / OUT / DATA. Some are open-drain → may need a pull-up |
| **40kHz / 60kHz / both** | Location-dependent (§2) | Dual-band is safer if the deployment location is uncertain |
| **Low current draw** | Nice-to-have only — wired USB power now (`glass-stone-concept.md` §2) | Not a selection driver anymore |
| **Enable/power-down pin** | Lets firmware duty-cycle the receiver | Optional. Also useful to *disable* it while the LEDs are switching, see §4 |

---

## 4. Risks to test early, not assume

These are the reasons this is a research memo rather than a plan.

1. **Indoor reception is a genuine, known weak point.** Radio-controlled wall
   clocks sometimes need a window-facing spot to sync. eki-ishi is meant to
   sit on a shelf — possibly an interior one. **Bench-test reception at the
   actual intended location before designing the stand around a module.**
2. **The ferrite antenna is directional.** Orientation relative to the
   transmitter materially affects signal strength, so "hide it wherever it
   fits" is not safe — antenna siting is a mechanical design input, not an
   afterthought.
3. **Self-interference is a real risk and this project is unusually exposed to
   it.** WS2812B strips are driven by a fast switching data signal and draw
   pulsed current; switching regulators (including the USB supply and anything
   in the Qi lineage) radiate broadband noise. A 40/60kHz longwave receiver
   sitting centimetres away inside a small enclosure is close to a worst case.
   Commercial radio clocks handle this by only attempting sync at night when
   the display is quiet. **Mitigation to plan for:** attempt JJY acquisition
   during a quiet window with the LEDs off — which this design already has,
   in the form of quiet hours (`config.py`'s `QUIET_START_HOUR` /
   `QUIET_END_HOUR`) and the display's ASLEEP state
   (`docs/contracts/gesture-envelope.md`). The existing sleep behaviour turns
   out to be exactly the right hook. Worth stating as a design constraint now
   so it isn't discovered late.
4. **Sourcing.** A first search did not turn up an obvious hobbyist module —
   see §5 and §6.
5. **Decode correctness needs its own tests.** Parity bits, the 60-second
   frame, leap-second handling, and the day-of-year → date conversion are all
   pure logic and belong in the host test suite (`tests/`), the same way
   Stage 1 already is. Do not treat this as hardware-only work.

---

## 5. Candidate parts — to fill in

_Deliberately empty. Add rows as parts are found, with a link and the §3
checklist filled in._

| Part / module | Vendor | Freq | Antenna incl. | Voltage | Output | Price | Notes |
|---|---|---|---|---|---|---|---|
| _(none yet)_ | | | | | | | |

---

## 6. Where to look — search terms

Japanese terms will be far more productive than English here; this is
domestic-market hardware.

| Term | Notes |
|---|---|
| **JJY受信モジュール** | The direct term. Try Akizuki Denshi's own site search first |
| **電波時計 受信モジュール** | "Radio clock receiver module" — broader, may surface salvage-grade parts |
| **標準電波 受信** | "Standard radio wave reception" — the formal term NICT uses |
| **MAS6180** | A receiver IC commonly used inside such modules; searching the part number often surfaces breakout boards directly. _Confidence: moderate — verify the part is current before ordering_ |
| "JJY receiver module" | English; works on Amazon.co.jp / AliExpress |
| **Strawberry Linux** | Japanese hobby-electronics vendor that has historically carried a JJY module. _Verify current availability_ |

Also worth checking: Akizuki Denshi, Switch Science, Sengoku Denshi, Marutsu —
the same shops already used throughout `docs/hardware.md`.

### The salvage route — probably the most promising

If a hobbyist module stays hard to find, **buy a cheap 電波時計 (radio-controlled
clock) and harvest its receiver module.** Every one of them contains exactly
the part we want, they are ubiquitous and cheap in Japan (¥1,000–3,000, home
centres and Don Quijote), and the receiver is usually a small discrete
daughterboard with a ferrite bar and a few wires to the main PCB — often with
identifiable VCC/GND/OUT/(EN) pads.

This is the same move `docs/roadmap.md` already documents for the clock
paradigm: salvaging Lavet stepper movements out of ¥100–500 quartz clock
kits rather than sourcing steppers as components. It worked as a strategy
there, it is well-suited to this project's craft/teardown spirit, and it has
a useful side effect — **a working clock is its own reception test.** If the
clock cannot sync where you intend to put the stone, you have answered risk
#1 for ¥1,000 before designing anything.

---

## 7. Fallbacks, in order of preference

If JJY does not work out — either unsourceable or reception fails at the
deployment location — the design does not collapse. In descending order:

1. **DS3231 RTC + rare manual correction.** Exactly the current plan
   (`docs/concept.md`). <1 min/year drift; correction via the NFC book
   (`docs/nfc-provisioning.md`) rather than a phone. This is a perfectly good
   answer, and it is the *status quo* — JJY is an improvement on it, not a
   prerequisite.
2. **Keep WiFi/NTP.** What V1 does today, and it works. Costs the "no WiFi"
   principle and the credentials-entry problem at gift time, which is the
   whole reason for wanting out.
3. **GPS module for time.** Technically excellent time source, but indoor
   reception is *worse* than JJY, not better, and it adds cost and power for
   a positioning capability we don't want. Not recommended.

---

## 8. Open questions

1. Which frequency does the deployment location favour — 40kHz, 60kHz, or is
   dual-band necessary?
2. Does reception work at the actual shelf location? (Cheapest test: a
   ¥1,000 radio clock, §6.)
3. Can a hobbyist module be sourced at all, or is salvage the route?
4. How much does the LED strip interfere in practice, and is a quiet-hours
   sync window sufficient? (§4.3)
5. Where does the antenna physically go in the stand, given it is directional
   and 30–40mm? (Feeds `glass-stone-concept.md` §4's stand selection.)
