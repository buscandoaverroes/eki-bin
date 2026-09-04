# Shopping memo — strip load switch + battery pack

**One trip. Everything here is for the same goal:** get the unit off the USB
cable, which is what frees the vessel choice and makes a pick-up gesture
possible at all.

Read the arithmetic first if you want the why:
`docs/roadmap.md` § "Battery power — the arithmetic" (modelled in
`scripts/power_budget.py`). The short version:

> A WS2812B draws **0.7–1.0 mA while displaying black** — the driver IC is
> live whenever VDD is. Twenty-one of them is ~17 mA showing nothing.
> Gating VDD is the difference between **4 days and 55 days** on 3× AA.

**Measure the bottle's mouth before you go.** Everything in the pack has to
fit through it, and that single number decides between a moulded holder and
daisy-chained singles.

---

## A. The load switch — the actual point of the trip

Two ways to build it. **Buy the parts for both** — they're cents, and the
discrete version is the guaranteed-in-stock fallback.

### Option 1 (preferred): a load-switch IC

One part plus one capacitor. Also gives **controlled slew rate**, which
matters here for a reason you have already met: 21 WS2812B powering up at
once is an inrush spike, and an unaddressed strip has already browned out a
board on this project (`insights.md` §13).

| Requirement | Value | Why |
|---|---|---|
| Input voltage | **≥ 6 V** | 4× NiMH is 5.6 V fresh |
| Continuous current | **≥ 1.5 A**, 2 A comfortable | 21 × 60 mA all-white worst case = 1.26 A |
| R<sub>DS(on)</sub> | < 100 mΩ | 1.26 A × 100 mΩ = 126 mW, fine; higher starts costing volts |
| Control logic | **3.3 V compatible** | XIAO GPIO |
| Polarity | **active-HIGH enable** | so the strip is OFF at reset and during boot |
| Nice to have | soft-start / slew control | kills the inrush brownout |

Search: `ロードスイッチ` / `ハイサイドスイッチ` / `load switch IC`
Example families to check stock on: **TPS22918**, **TPS27081A**, **AP2281**.
Most are SMD — grab a **SOT-23 変換基板** (SOT-23 breakout board) in the
same trip if you want it on a breadboard.

### Option 2 (fallback): discrete P-MOSFET + small N-MOSFET

Guaranteed available anywhere. Four parts.

```
   BATT+ ─────┬────────────── S
              │            [P-ch MOSFET]
             R1             D ──────────── strip VDD (+ 1000µF to GND)
            100k               
              │            G
              └──────────────┤
                             │
                             D
                       [2N7002 N-ch]
              MCU GPIO ──┤ G
                             S
                             │
              R3 100k ───────┤
                             │
                            GND
```

- GPIO **HIGH** → N-FET on → P-FET gate pulled to GND → V<sub>GS</sub> = −V<sub>BATT</sub> → **strip on**
- GPIO **LOW / Hi-Z** → R3 holds the N-FET off, R1 pulls the P-FET gate to source → V<sub>GS</sub> = 0 → **strip off**

Reset and boot both leave the GPIO undriven, so the strip defaults **off**.
That is the correct failure direction and it also removes the power-on
inrush entirely.

**⚠ The P-FET must be logic-level / low V<sub>GS(th)</sub>.** The rail is only
4.5–5.6 V, so a classic part like an IRF9540 (needs ~10 V of V<sub>GS</sub> to
enhance fully) will run half-on and get hot. This is the one spec not to
compromise on.

| Part | Requirement | Search |
|---|---|---|
| P-ch MOSFET ×2 | V<sub>DS</sub> ≥ −20 V, I<sub>D</sub> ≥ −3 A, **V<sub>GS(th)</sub> ≤ −2.5 V** | `Pチャネル MOSFET ロジックレベル` — e.g. **AO3401**, **IRLML6402**, **2SJ** logic-level series |
| N-ch small-signal ×2 | any, 60 V / 200 mA is plenty | `2N7002` / `小信号 Nチャネル MOSFET` |
| Resistors | 100 kΩ ×4 (R1, R3) | `カーボン抵抗 100kΩ` |

---

## B. Battery pack

**2× AA is out — voltage, not capacity.** WS2812B wants **≥ 3.5 V**. Two
cells is 3.0 V nominal and dead on arrival without a boost converter.

| Pack | Fresh | Nominal | End of useful life | Verdict |
|---|---|---|---|---|
| 3× alkaline | 4.8 V | 4.5 V | sags to ~3.0 V — **below the 3.5 V floor with a third of the capacity left** | works, wastes the tail |
| **4× NiMH (eneloop)** | 5.6 V | 4.8 V | flat until nearly empty | **preferred** — the flat discharge curve suits a fixed-threshold load |

Buy:

| Item | Search | Note |
|---|---|---|
| Battery holder | `単3電池ボックス 4本 リード線付` (4-cell AA box with leads) | also grab `3本` — decide once you have the bottle mouth measured |
| Holder, slim/inline | `単3電池ボックス 1本` ×4 | daisy-chain these if a moulded 4-cell box won't fit through the mouth |
| Cells | `ニッケル水素電池 単3` / `エネループ` | 4 minimum, 8 if you want a swap set |
| Inline switch | `スイッチ付` on the holder, or `トグルスイッチ` | not required — the load switch handles the strip, and the MCU sleeps — but a hard off is nice for storage |

**The DS3231 keeps its own coin cell**, so the clock survives every pack
change. That is what makes a two-month replacement interval tolerable
instead of a re-provisioning event — don't accidentally power the RTC from
the main pack.

---

## C. Small parts to grab while you're there

| Item | Search | Why |
|---|---|---|
| Electrolytic 1000 µF, ≥ 10 V | `電解コンデンサ 1000µF 16V` | standard across the strip's supply; steadies the rail on colour changes |
| Resistors 330 Ω / 470 Ω | `カーボン抵抗 330Ω` | series on the strip's DIN — standard WS2812B practice, protects the first pixel |
| Resistors 10 kΩ | `カーボン抵抗 10kΩ` | general |
| SOT-23 breakout boards | `SOT-23 変換基板` | only if you go the IC route |
| Schottky diode | `ショットキーダイオード 1A` | optional, reverse-polarity protection on the pack |

---

## D. Two traps that will cost you an evening if you miss them

### 1. Gating VDD is not enough — DIN must go low too

If the MCU keeps driving the data line high after VDD is cut, current flows
through the first pixel's input protection diode into the now-floating VDD
rail. The strip **partially powers itself through its own data pin**, LEDs
glow dimly, and the load switch appears to have done nothing.

**Before gating power: write black, then drive DIN low (or set the pin to
input).** This is the same family of trap as `quiet_onboard_leds()` already
handles for the onboard NeoPixel — write black *before* cutting the gate,
because the pixel latches its last value. Same lesson, one layer out.

### 2. 3.3 V data into a 5+ V strip is marginal, and gets worse on NiMH

WS2812B wants V<sub>IH</sub> ≈ 0.7 × VDD. It works today on the USB 5 V rail
with a 3.3 V GPIO (0.7 × 5.0 = 3.5 V — technically already out of spec, and
tolerated). Fresh NiMH at **5.6 V wants 3.9 V** and the margin gets worse,
not better.

If the strip glitches on battery but not on USB, this is why. Fixes, cheapest
first:

- Put a **series Schottky** in the strip's VDD to drop ~0.3 V
- Add a **74AHCT125** level shifter (`74AHCT125` — its 3.3 V input threshold
  with a 5 V supply is exactly this job)
- Run the strip from a regulated 3.3 V (dimmer, but the data line is then
  perfectly matched)

Don't pre-solve it. Note it, and check it first if the strip misbehaves.

---

## Checklist

- [ ] Bottle mouth measured **before leaving**
- [ ] Load switch IC ×2 (+ SOT-23 breakouts) **or** P-FET ×2 + 2N7002 ×2 + 100 kΩ ×4
- [ ] 4× AA holder, and 1× AA holders ×4 as the fits-through-the-mouth fallback
- [ ] NiMH AA ×4 (×8 for a swap set)
- [ ] 1000 µF electrolytic, 330 Ω, 10 kΩ
- [ ] Optional: 74AHCT125, Schottky, inline switch
