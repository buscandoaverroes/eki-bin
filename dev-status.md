# eki-bin — Dev Status
_What is true now, what is next, what is open. Rewritten 2026-09-29; the
build-by-build history through V1.6 is frozen in
`docs/archive/dev-status-history.md`._

---

## Where we are

**The production unit runs and has been lived with.** XIAO RP2350 (no radio)
+ DS3231 + LSM6DSV16X IMU + 21-LED WS2812B strip in a brown glass bottle,
powered over USB. Correct time from the RTC across power cycles; tap wakes and
cycles **line**; tilt adjusts brightness; the display renders
`ApproachContract` with per-line colour; day/night brightness; goodnight and
morning ceremonies for "trains exist but none in reach". Firmware is split
across eleven modules with no radio code. `make test` runs lint + 418 host
tests before every `make upload`. Wiring: `pinouts/v1.6-rp2350-production-unit.md`.

**Recent arc (Aug 22 → Sep 14):** DS3231 bring-up + integration → V1.6
single-target split → colour is measured, not guessed (`insights.md` §12) →
the light language: five motion words, tilt controller, palette checks,
horizon ceremonies, crawl sandbox, `scatter` (`insights.md` §14–§21,
`docs/contracts/light-language.md`).

**The project's centre of gravity has moved** from "does it work" to "is it
givable" and "is this the right costume". Two things follow.

## The walls between here and a givable bottle

| wall | state | doc |
|---|---|---|
| **Interaction: tap and tilt fight** | Each works in isolation; together they are unreliable. Diagnosed as a *composition* problem, not a classification one. **Plan drafted, iterate before building.** | `docs/imu-interaction-plan.md` |
| **Wiring harness** | Mounting the IMU took ~20 min of chopsticks through the mouth. Decision leaning to a **lid-mounted unit** assembled outside the vessel. Needs a conversation before code. | § below |
| **Power** | Battery build needs a strip load switch (4 → 55 days). **May be dissolved rather than solved** if the lamp/chandelier form (USB from the top, always on) is chosen. | `docs/shopping-battery-power.md`, `docs/chandelier-concept.md` |

And one *process* item that is not a wall but bites at the second unit:
**a provisioning manifest** (§ below).

## The form-factor fork (open, and it dissolves two walls)

The LED strip is a good-for-now display, not the destination. The intended
end state is the **chandelier** (`docs/chandelier-concept.md`): filament
LEDs suspended in 3D — or a bird's-nest tangle of them — with everything in a
neck/lid unit and **USB power from the top**. Reframing the object as a
*lamp* (always on, on a cord) rather than a *bottle* (should be wireless and
asleep) retires the battery wall, makes the lid-mounted harness natural, and
lets the MCU run always-on models a battery build could never afford — so the
IMU wall and the power wall trade off against each other.

Nothing here is scheduled. What it changes *now*: **do not tune per-mount
constants for the bottle-base IMU as if permanent** (cross-bottle tap accuracy
is 0%, `insights.md` §8; a lid mount is a different signal). Fix the
*state machine* — which transfers — before the *thresholds* — which do not.
Design language and principles (`light-language.md`, `design-principles.md`)
carry over; hue-dependent parts degrade gracefully by design (`insights.md` §17).

Long-term but explicitly **2–3 versions out, not required for first
givability**: NFC / sticker-book input (`docs/nfc-provisioning.md`).

---

## Next up

**1. The interaction plan** — `docs/imu-interaction-plan.md`. Firmware only, no
new hardware. Instrument and record → replay harness → one arbiter for tap +
tilt with look-back → gyro. ML (MLC / ESN) is gated on the arbiter failing
against recorded data, not scheduled.

**2. Small, independent, cheap**
- Re-test whether the RP2350's third onboard indicator can be turned off in
  software (`insights.md` §13 concluded "no"; new information on 2026-09-14
  suggests otherwise — start from `make onboard-led-test`,
  `pinouts/xiao_rp2350.md`). The current answer is desoldering a part on
  every unit before sealing it in glass.
- Raise `DAY_BRIGHTNESS` on real glass (the day/night profile ships flat).
  Seasonal drift still needs day-of-year, which `local_time()` discards.
- `--unit` flag on `scripts/rtc_drift.py` (see manifest, below).

**3. Hardware track, gated on parts and on the form-factor fork**
- Bottle-mouth measurement (serves the harness *and* the battery holder).
- Strip load switch + battery pack, *if* the bottle stays wireless.
- Forward-voltage measurement for filaments (`hardware.md` § Filament array)
  — the gate on the chandelier.

## Two things that need a conversation before code

### A wiring harness
Fixing the IMU to the base took ~20 minutes, nearly all managing loose wires
through the mouth. The battery build adds a pack, a load switch and a gated
rail through the same opening. The chandelier/lid form fixes it by
construction (assemble outside, lower in) — which is also the roadmap's
"cork-mounted sensor cluster". Constraint shared with the battery holder: the
bottle-mouth measurement. Side effect to plan for: moving the IMU changes the
tap signal; expect to re-collect.

### A provisioning manifest
Multiple DS3231s exist and nothing distinguishes them (no unique-ID register,
no user SRAM). **Concrete hazard:** `data/rtc-drift.jsonl` has `epoch` but no
unit field, so one `make rtc-drift` against the wrong chip silently pollutes
bottle-01's fit. A `--unit` flag closes that hole; the larger answer is a record
per physical unit — see `docs/gift-registry.md` (proposal, not built; forcing
function is the unit-agnostic `data/rtc-drift-summary.json`). It must also
hold `ARC_ORIGIN`, arm A/B orientation, `SHAKE_BOUNDS`, IMU mount location,
`TAP_ENERGY_THRESHOLD` — per-unit facts established by hand, not derivable
from code.

---

## Parked, with a reason

- **On-board ML for gestures** (ESN, MLC decision trees, a piezo disc) —
  `docs/on-board-detection.md`. Ranked *after* the arbiter and the gyro,
  because the failures being hit are composition bugs. The one new argument
  from the form-factor fork: with USB power, always-on inference becomes
  affordable. Still needs recorded data and per-unit calibration first.
- **Clock mode** — verification variant first (blink the digits); the ambient
  "solar dial" waits on the vessel/mount decision.
- **Glass stone on a stand (eki-ishi)** — `docs/glass-stone-concept.md`. A
  parallel form-factor proposal; the chandelier now competes with it for
  "what's the real destination".
- **NFC provisioning** — on hold; candidate path (USB reader + `nfcpy` writing
  NTAG stickers) unverified. A timetable does not fit on an NTAG sticker
  (`nfc-provisioning.md` §8.6a). See above: later versions.
- **Repo hygiene** — branch protection on `main`, a CI workflow running
  `make schedule` then `make test`, pruning ~20 stale local branches.
  Tabled to do comprehensively in one go.
- **V1.5 round PCB ring** — needs a level-shifter test (OSTW3535C1A wants
  ≥3.5 V logic). Superseded in spirit by the chandelier; revive only if a ring
  form is chosen.
- **Rust / Embassy V2** — the learning goal, unstarted. Module boundaries from
  the V1.6 split are the crate boundaries. RP2350 is now the target board
  (it is the production board). Embedded Swift/Matter is the competing
  candidate (solves provisioning via the Home app; experimental toolchain).

---

## Open decisions

| Decision | Status | Notes |
|---|---|---|
| Form factor: strip-in-bottle vs chandelier vs glass stone | 🔲 open — leaning chandelier | See above. Gated on filament forward-voltage measurement and the IMU work |
| Vessel | 🔲 open | Thick brown is best-looking and most limiting (2–3 hues). `insights.md` §12 |
| Tilt: always-on sense vs. a mode entered by a gesture | 🔲 open, in the plan | `docs/imu-interaction-plan.md` §4 |
| Multi-line schedule memory: hold all vs load one | 🔲 deferred | Measured: ~21 KB JSON for 3–4 lines vs 8 KB for one. Fine on RP2350 (492 KB free); revisit if lines grow. Measure with `gc.mem_free()`, don't estimate |
| Cork vs screw cap | 🔲 open | Moot if the unit lives in a lid |
| LED direction / HAL abstraction | 🔲 open | `_physical()` seam exists; full `led_drivers/` deferred until a new display arrives (`insights.md` §4) |
| E-ink / station-card storage | 🔲 open, low | Not on the path to first givability |

**Resolved since the old table** (kept out of the live list): board upgrade
(RP2350 chosen and shipped), DS3231 (integrated), WiFi memory headroom
(retired — the radio is gone), multi-train modality (`N_TRAINS`, shipped),
Qi viability and full-brightness ceiling (`hardware.md`), NFC iOS-app rows
(moot while on hold). History: `docs/archive/dev-status-history.md`.

---

## Known issues / notes

- ⚠ **XIAO RP2350 needs firmware newer than 2026-04-06**, or its filesystem is
  sized past the physical flash and littlefs corrupts silently. `make doctor`
  fails such a board. `insights.md` §13.
- `schedules/*.json` is gitignored and generated; CI would need `make schedule`
  before `make test`.
- WiFi creds / `config.py` are gitignored plaintext. Never read `config.py`.
- **Quiet-hours gotcha:** after `QUIET_START_HOUR` the strip is dark by design
  and looks identical to a bug. To test at night set `QUIET_START_HOUR=24,
  QUIET_END_HOUR=0`.
- **The display cannot say "a train exists, just not near enough"** — *fixed*
  by goodnight/morning ceremonies (`horizon.py`, `insights.md` §17–§18).
- Host tests cover logic, not brightness/diffusion/feel. Those stay a hardware
  judgement call.
- REPL poking via `make screen` lands in a fresh namespace; use `import main`.
