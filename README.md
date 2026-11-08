# eki-bin 駅瓶

> An ambient train-departure display. A glass bottle on a shelf whose
> light shows how soon you need to leave for the next trains. No phone, no
> screen to unlock: glanceable like a clock.

**eki-bin** (駅瓶, "station jar"): 瓶 *bin* is jar or bottle, a play on eki-ben
(駅弁, the station bento). It exists because checking a departure board on a
phone is a small act of attention, many times a day, for one fact. The
bottle makes that fact part of the room: information present in the
environment, not pushed at you. The glass does the hiding; the technology is
only acceptable if you can't see it.

<!-- A photo or short GIF of the bottle goes here: docs/media/eki-bin.gif -->

Design rationale: [docs/concept.md](docs/concept.md) · principles:
[docs/design-principles.md](docs/design-principles.md).

---

## Status

**A working prototype, lived with day to day.** One production unit: a XIAO
RP2350 with a DS3231 real-time clock, an LSM6DSV16X IMU and a 21-LED WS2812B
strip inside a thick brown glass bottle, powered over USB. Firmware V1 is
MicroPython, split into small modules; 600+ host tests run before every
upload (`make test`).

- **Works now, on the bottle:** correct time with no network (the RTC keeps
  it across power cycles); each upcoming train shown as a point of light
  closing in on a fixed "station" point, one colour per line; tap to wake
  and to cycle lines; tilt to adjust brightness; day/night brightness;
  goodnight and morning ceremonies.
- **Working in simulation, not yet flashed:** a rebuilt input pipeline that
  stops tap and tilt from fighting each other (below, *Design iterations*).
- **Not started:** V2, a rewrite in Rust (Embassy). On-device ML for gestures
  has been analysed and is deliberately gated: it gets built only if the
  rule-based pipeline fails against recorded data.

Current state in detail: [dev-status.md](dev-status.md).

---

## How it works

Two pipelines meet at the LEDs: one decides what to show, the other decides
what you did.

```
  what to show
  DS3231 RTC ──► timetable ──► LeaveSignal ─────► DisplayContract ──► 21 × WS2812B
  (time, no      (per line)    "how long until    "how that looks"    behind brown
   network)                     you must leave"         ▲             glass
                                                        │
  what you did                                          │
  LSM6DSV16X ──► detect ─────► arbiter ─────► classify ─┘  tap  → next line
  accel + gyro   "did anything "when is it    "what was     tilt → brightness
  240 Hz          happen?"      real?"         it?"
```

- **Display:** the display pipeline is two stages: time becomes an abstract
  signal (`LeaveSignal`), and a swappable `DisplayContract` turns it into
  light. New inputs and new outputs each touch only their own side.
  [docs/contracts/display-contract.md](docs/contracts/display-contract.md)
- **Input:** detect is cheap and always on, and classify judges what an
  impulse was. The arbiter, which holds each tap as a provisional claim
  and commits it only once the bottle is proved still, runs in the
  simulator today and is next to go onto the bottle.
  [docs/imu-interaction-plan.md](docs/imu-interaction-plan.md)

---

## Design iterations

- **Board and time: WiFi → no radio.** V1 ran on a Raspberry Pi Pico 2W,
  syncing time over WiFi/NTP. A portability checkpoint on a XIAO ESP32-C3
  (July 2026) passed, but WiFi needs ~40 KB of SRAM there and ran out of
  memory. V1.6 (August) moved to a XIAO RP2350 with a DS3231 RTC and no
  radio at all: no WiFi credentials, no pairing, nothing to set up in the
  house it's given to. A timetable doesn't need a network.
- **Enclosure: the glass is part of the display.** Clear glass ruined the
  effect; thick translucent glass makes it. The glass also sets the colour
  budget: thick brown supports only 2–3 distinguishable line colours, and
  a neutral marker colour is impossible in it. Measured with bench tests
  (`make hue-test`, `make low-pwm-test`), not chosen on a screen.
- **Motion: curves, not choreography.** Six ways of moving a "train" and
  five station fades were compared on real glass. The smooth ones won every
  time. The ones that looked *alive* read as "something needs your
  attention", the opposite of ambient. That became a design rule (physics
  is indifferent; intent wants something from you).
- **Input: from tuning thresholds to measuring.** Tap recognition shipped
  as a hand-tuned energy rule (98.4% separation from handling), but tap and
  tilt fought: a grab often began as a "tap". Rather than keep tuning, the
  input path was instrumented: raw 240 Hz recordings, a guided recording
  protocol where the script cues each trial (both hands free), and a
  simulator that replays the real firmware code with each block swappable.
  It found that half of natural taps never reached the classifier (the
  trigger measured the *length* of the acceleration vector, and a sideways
  tap barely changes it). A vector trigger plus an arbiter that commits on
  stillness: natural taps detected 15/30 → 28/30, grab trials producing a
  false tap 16/30 → 6/30, and no false taps in 70 minutes of rest
  recordings. One bottle, one table, in simulation; the bottle comes next.
- **Power: USB, honestly.** A battery build needs a load switch for the LED
  strip: left powered, its idle draw empties 3×AA in about 4 days; switched
  off between uses, with shorter wake periods, about 55. A lamp-like form
  powered from above may make the question go away rather than solve it.

## Next

1. **Finish the noise floor** (~3 h of rest recordings, the target is under
   one false tap per hour), then wire the arbiter into the firmware and
   validate it in the bottle.
2. **A wiring harness**, assembled outside the vessel and mounted in the
   lid. It should also cure the IMU's intermittent resets, which the
   recordings point to a loose wire.
3. **V2 in Rust (Embassy)**, with the V1 logic as the specification:
   [docs/rust-migration.md](docs/rust-migration.md).

---

## Repo layout

```
eki-bin/
├── micropython/   firmware: main.py and its modules (signals, contracts, gestures,
│                  arbiter, tilt, motion…), plus bench sandboxes and bring-up scripts
├── scripts/       host tools: upload, schedule conversion, recording, replay, the simulator
├── tests/         host-side tests (`make test`, runs before every upload)
├── docs/          rationale, contracts (the interfaces), plans, field notes
│   └── contracts/ display pipeline, schedule format, config, gestures, light language
├── pinouts/       per-board wiring, the source of truth for what connects where
├── schedules/     timetable template (real timetables are gitignored)
├── dev-status.md  what's true now, what's next, open decisions
└── CLAUDE.md      orientation for Claude Code, including a map of every doc
```

Good places to start reading: [docs/concept.md](docs/concept.md) (why),
[docs/insights.md](docs/insights.md) (field notes and why-decisions),
[docs/imu-interaction-plan.md](docs/imu-interaction-plan.md) (the current
engineering thread), and [docs/reflections/](docs/reflections/).

---

## Quick start

```bash
make setup              # create .venv, install mpremote + pyyaml
make flash-micropython  # flash MicroPython (asks which board; or BOARD=pico2w)

cp schedules/mystation.example.yaml schedules/mystation.yaml   # edit your times
make schedule           # YAML → schedules/mystation.json

cp micropython/config.example.py micropython/config.py         # pins, TIME_SOURCE (WiFi creds only for "wifi")
make test               # host-side logic tests (also runs automatically on upload)
make upload             # push the firmware + config.py + schedule.json to the board
make screen             # open the REPL to watch it run
make imu-record UNIT=bottle-01  # raw sensor stream + intent labels, no firmware (data/imu-*.jsonl)
make imu-record UNIT=bottle-01 PROTOCOL=tap-vs-grab  # guided: the script cues each trial
make sim                # the IMU pipeline with swappable blocks, scored on every usable recording
make sim-live           # the same, live, on the recording being made (second terminal)
make leakcheck          # scan what's about to be published (also runs in `make pr` + the pre-push hook)
make pr                 # push this branch + open its PR against dev (body: .pr-body.md, else the commit list)
```

### Hardware wiring

**The production unit** (XIAO RP2350 + DS3231 + IMU + 21-LED strip) is wired
per [pinouts/v1.6-rp2350-production-unit.md](pinouts/v1.6-rp2350-production-unit.md),
which is self-contained: ASCII diagram, config values, traps, bring-up order.
Building one from scratch: [docs/provisioning-runbook.md](docs/provisioning-runbook.md).

**The original dev board:** wire the **AE-WS2812B-STICK8** to the Pico (full pin details, including
GPIO-for-`config.py` mapping, in [pinouts/pico2w.md](pinouts/pico2w.md);
parts/voltage notes in [docs/hardware.md](docs/hardware.md)):

| Pico 2W | pin | → | LED stick |
|---|---|---|---|
| VBUS | 40 | → | VCC (5V) |
| GND  | 38 | → | GND |
| GP6  |  9 | → | DIN |

No level shifter needed — the stick's signal threshold is 2.7V, below the
Pico's 3.3V GPIO. Bringing up a different board? Check
[pinouts/](pinouts/) for its pin mapping — it's the single source of truth
for what's wired where, kept in sync with `config.py`. Then:

```bash
make led-test           # cycle colours + chase across all 8 LEDs
```

Bringing up the IMU (LSM6DSV16X, for tap-gesture recognition — see
`docs/contracts/gesture-envelope.md`)? Wire SDA/SCL/3V3/GND per
`docs/hardware.md` and `pinouts/<board>.md` (combined IMU+LED wiring, with a
3.3V/5V power-rail safety note, is documented in `pinouts/pico2w.md`), then:

```bash
make imu-test            # scan I2C, confirm the chip, stream accel readings
```

---

## Tuning the display

The entire look is driven from `config.py` — no firmware edits. Copy the
template, then adjust. Full reference: [docs/contracts/config.md](docs/contracts/config.md);
the rendering model: [docs/contracts/display-contract.md](docs/contracts/display-contract.md).

| Knob | What it does |
|---|---|
| `CONTRACT` | Visual strategy: `sandtimer` · `color` · `breathing` (+ `_exponent` / `_inverse`) · `echo` · `approach` |
| `COLOR_SCHEME` | Palette: `default` · `sunset` · `mono` |
| `BRIGHTNESS` | Global ceiling (ambient, not blinding) |
| `WALK_TO_STATION_MINS` | Subtracted from each departure → "time to leave"; uncatchable trains hidden |
| `URGENCY_THRESHOLDS` | Minutes-to-leave band edges (colour changes) |
| `ARC_ORIGIN` | `near` / `far` — flip the arc for an upside-down strip |
| `LED_PIN` · `HEARTBEAT_PIN` | Board-specific — GPIO for the data line / status LED (see [pinouts/](pinouts/)) |
| `GAMMA` · `DITHER` · `FRAME_MS` | Smoothness: perceptual curve · low-end dithering · frame rate |
| `BREATHE_PERIOD_MS` · `BREATHE_FLOOR` | Breath speed and how dim the trough gets |
| `QUIET_START_HOUR` · `QUIET_END_HOUR` | When the strip goes dark (set `24` / `0` to disable) |

> Tip: at night the strip is dark by design (quiet hours) — set
> `QUIET_START_HOUR=24, QUIET_END_HOUR=0` to test any time.

---

## Schedule workflow

`schedules/<station>.yaml` is the human-edited source of truth (times in `HH:MM`,
post-midnight trains use extended hours like `"25:10"`). `make schedule` converts
it to minutes-since-midnight arrays the firmware consumes.

The real schedule reveals where you live, so `schedules/` is gitignored except
the `*.example.yaml` template. Schema: [docs/contracts/schedule-json.md](docs/contracts/schedule-json.md).

---

## Secrets and privacy

The production unit has no secrets: it keeps time with a DS3231 and has no
radio. On the WiFi path (`TIME_SOURCE = "wifi"`, the Pico 2W), the WiFi
credentials live in `config.py`, which is **gitignored** and never committed:

```bash
cp micropython/config.example.py micropython/config.py   # then fill in what your board needs
```

The board has no secure enclave; for a single-user local device,
gitignored plaintext is an accepted tradeoff.

This is a public repo about a private commute, so a real timetable reveals
where someone lives. Real schedules, sensor recordings and `config.py` are
all gitignored, and `make leakcheck` scans what's about to be published
(it also runs in a pre-push hook). Posture and open items:
[docs/security.md](docs/security.md).

Schema: [docs/contracts/config.md](docs/contracts/config.md).
