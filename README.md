# eki-bin 駅瓶

> An ambient train-departure display. A frosted glass jar on a shelf that glows
> an arc of light telling you how long until the next train. No phone, no screen
> to unlock — glanceable like a clock.

**eki-bin** (駅瓶, "station jar") — 瓶 *bin* = jar/bottle, a play on eki-ben
(駅弁, the station bento). The jar is the whole idea: information present in the
environment, not pushed at you.

See [docs/concept.md](docs/concept.md) for the full design rationale.

---

## Status

**V1 (MicroPython on Raspberry Pi Pico 2W) — firmware feature-complete; in-jar tuning.**

- Connects to WiFi, syncs time via NTP; reads a generated schedule; detects
  weekday/weekend and picks the right timetable
- Drives the 8-LED stick through a two-stage display pipeline
  `time → LeaveSignal → DisplayContract → LEDs`
  ([docs/contracts/display-contract.md](docs/contracts/display-contract.md))
- Seven display contracts (`sandtimer`, `color`, `breathing` + exponent/inverse,
  `echo`, `approach`), colour schemes, an animation/smoothing stack (perceptual
  **gamma** + temporal **dithering** + seamless clock), night quiet-hours — all
  driven by `config.py` knobs, no firmware edits to tune
- Host **test suite** (`make test`) guards the logic; runs before every upload

See [docs/reflections/v1-reflections.md](docs/reflections/v1-reflections.md) for a brief update on how the project is going so far.

**In progress (`feature/gesture-envelope` branch, not yet merged):** IMU
(LSM6DSV16X) tap-gesture recognition + a two-phase ACK/CONFIRM LED jolt —
tap wakes the display, tap cycles it, timeout sleeps it. Extensively
validated on real hardware (Pico 2W + LED stick); XIAO + full LED tape +
the actual bottle is the next validation step before merge. See
[docs/contracts/gesture-envelope.md](docs/contracts/gesture-envelope.md).

**Next:** v1.1 — move everything inside the bottle, Qi-powered (see
[docs/roadmap.md](docs/roadmap.md)). **V2** rewrites the firmware in Rust (Embassy)
with a DS3231 RTC and NFC station cards. Running log: [dev-status.md](dev-status.md).

---

## Repo layout

```
eki-bin/
├── README.md                     ← you are here
├── CLAUDE.md                     ← guidance for Claude Code (Rust teaching directive)
├── dev-status.md                 ← running log: done / next / open decisions
├── Makefile                      ← setup, flash, schedule, led-test, imu-test, upload
├── requirements.txt              ← host Python tools (mpremote, pyyaml)
│
├── docs/
│   ├── concept.md                ← design rationale (the "why")
│   ├── hardware.md               ← parts in hand, voltage compatibility
│   ├── roadmap.md                ← v1.1/v1.2 hardware plan, form-factor threads
│   ├── insights.md               ← field notes, why-decisions, parked ideas
│   ├── rust-migration.md         ← V1 → V2 (MicroPython → Embassy) map
│   └── contracts/
│       ├── schedule-json.md      ← schema for the generated schedule
│       ├── config.md             ← schema for config.py fields
│       ├── display-contract.md   ← LED pipeline: LeaveSignal → contracts
│       ├── approach-contract.md  ← positional/approach display paradigm
│       ├── startup-sequence.md   ← boot ceremony LED sequence
│       ├── gesture-envelope.md   ← IMU tap-gesture recognition + ACK/CONFIRM jolt
│       ├── wake-interaction.md   ← original IMU design (partially superseded above)
│       └── led-status-messages.md ← LED error/acknowledgment vocabulary
│
├── pinouts/                       ← per-board pin assignments (source of truth)
│   ├── pico2w.md                  ← ✅ verified — V1 wiring + IMU (gesture branch)
│   └── xiao_esp32c3.md            ← ✅ verified — v1.2 checkpoint passed; IMU not yet wired here
│
├── schedules/
│   ├── mystation.example.yaml    ← committed sample (copy → mystation.yaml)
│   ├── mystation.yaml            ← gitignored; your real timetable
│   └── mystation.json            ← generated; gitignored
│
├── scripts/
│   ├── convert_schedule.py       ← YAML → minutes-since-midnight arrays
│   ├── select_port.sh            ← USB device picker for `make screen`
│   ├── analyze_taps.py           ← gesture capture → tap/position feature analysis
│   ├── prepare_tap_dataset.py    ← gesture capture → engineered-feature CSV
│   ├── train_tap_classifier.py   ← hardcoded-threshold vs. classifier comparisons
│   └── clear_vibes.sh            ← clean up on-device gesture capture files
│
├── tests/                        ← host-side logic tests (`make test`)
│   ├── conftest.py               ← device-module fakes + config loader
│   └── test_*.py                 ← stage1, render, primitives, gesture envelope, config…
│
├── micropython/                  ← V1 firmware
│   ├── main.py                   ← main loop
│   ├── led_test.py               ← hardware bring-up for the WS2812B stick
│   ├── led_sandbox.py            ← colour/animation A-B comparisons + gesture-jolt prototyping
│   ├── gesture_sandbox.py        ← live gesture recognizer + LED jolt sandbox (real IMU + LEDs)
│   ├── imu_test.py               ← IMU bring-up: I2C scan, register confirm, accel stream
│   ├── vibration_sandbox.py      ← position × gesture batch data collection
│   ├── handling_test.py          ← false-positive-risk data collection (pickup, carry, bump…)
│   ├── orientation_test.py       ← live gravity-vector / orientation monitor
│   ├── config.example.py         ← committed template
│   └── config.py                 ← gitignored; real WiFi creds (see Secrets)
│
└── firmware/                     ← gitignored; local .uf2 files only
```

---

## Quick start

```bash
make setup              # create .venv, install mpremote + pyyaml
make flash-micropython  # flash MicroPython .uf2 via picotool (hold BOOTSEL)

cp schedules/mystation.example.yaml schedules/mystation.yaml   # edit your times
make schedule           # YAML → schedules/mystation.json

cp micropython/config.example.py micropython/config.py         # fill in WiFi creds
make test               # host-side logic tests (also runs automatically on upload)
make upload             # push main.py + config.py + schedule.json to the Pico
make screen             # open the REPL to watch it run
```

### Hardware wiring

Wire the **AE-WS2812B-STICK8** to the Pico (full pin details, including
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

## Secrets

The only secret in V1 is the WiFi credential pair in `config.py`, which is
**gitignored** and never committed:

```bash
cp micropython/config.example.py micropython/config.py   # then fill in SSID/pass
```

`config.py` already lives on the Pico, so you can also just edit it on-board via
Thonny. The Pico has no secure enclave — for a single-user local device,
gitignored-plaintext is an accepted tradeoff. (A vault-based flow was considered
and tabled; revisit if this ever gets shared or goes into CI.)

Schema: [docs/contracts/config.md](docs/contracts/config.md).
