# Provisioning runbook — bare board to running unit

_One-glance checklist for building a unit from scratch. **Deliberately terse**
— every step links to the detail rather than repeating it. First walked
end-to-end 2026-08-16 on the v1.4+IMU dev unit
(`pinouts/v1.4-imu-dev-unit.md`); revised 2026-08-24 for the V1.6 module
split and the XIAO RP2350 flash-size defect._

---

## 0. Before you start

| Need | Where |
|---|---|
| Board pinout for your board | `pinouts/<board>.md` |
| Assembly wiring for your build | `pinouts/v1.x-<build>.md` |
| Parts, voltages, solder technique | `docs/hardware.md` |

---

## 1. Solder / wire

- [ ] **Check the rails before powering anything.** Shared GND; separate
      positives. **IMU = 3V3, LED = 5V** — the LSM6DSV16X is not 5V-tolerant.
- [ ] XIAO has **one GND pad** → twisted splice, one joint. Not two joints on
      one pad. (`docs/hardware.md` § Build technique)
- [ ] Mixed wire gauge: thicker for power, thinner for signal. Silicone
      insulation.

## 2. Flash MicroPython

```bash
make flash-micropython                      # interactive board picker
make flash-micropython BOARD=pico2w         # or name it directly
make flash-micropython BOARD=esp32c3
make flash-micropython BOARD=xiao-rp2350
```

> **XIAO RP2350 BOOTSEL:** hold **B**, tap **R**, release **B** — the cable
> stays connected. On a board with no reset button: hold BOOT while plugging
> in.

Add `WIPE=1` to erase the filesystem too. **A plain reflash does not touch
it** — firmware and filesystem live in separate flash regions — so a board
that is unreachable because its filesystem is damaged will survive any
number of reflashes unchanged (`docs/insights.md` §13).

Multiple builds in `firmware/`? The **newest** wins (MicroPython filenames
embed `YYYYMMDD`). Pin one explicitly with `FIRMWARE=<path>`.

### ⚠ XIAO RP2350: the firmware VERSION is a correctness requirement

Builds up to **v1.28.0** create a filesystem **larger than the flash that
exists** — 3072 KB on a 2 MB part. The board header declared
`PICO_FLASH_SIZE_BYTES` as 4 MB against a 2 MB chip
([pico-sdk#2834](https://github.com/raspberrypi/pico-sdk/issues/2834)),
propagating into MicroPython
([#18839](https://github.com/micropython/micropython/issues/18839)). It
corrupts littlefs, and the corruption is silent — a file can verify at the
right size and still read back as the filesystem's own superblock.

Fixed in pico-sdk 2.3.0 plus a follow-up trimming the partition to 1408k.
**Use a build newer than 2026-04-06.** Step 2b proves it.

## 2b. Prove the board before trusting it — MANDATORY

```bash
make doctor
```

Checks reachability, filesystem, heap, and write/read integrity at 4/24/40 KB
— separately for a **local** write (device writes its own file) and a
**transfer** (host sends one), so a flash fault is distinguishable from a
transport one. It **fails outright** if the filesystem exceeds the physical
flash.

- [ ] XIAO RP2350 reports **~1408 KB**, not 3072 KB.
- [ ] All six write tests intact.


## 3. Config

- [ ] `cp micropython/config.example.py micropython/config.py`, fill in WiFi.
- [ ] Set the **board-specific** values: `LED_PIN`, `NUM_LEDS`,
      `HEARTBEAT_PIN` (`None` on XIAO), **`IMU_I2C_ID`**, `IMU_SDA_PIN` /
      `IMU_SCL_PIN`. The table at the top of `config.example.py` has all of
      them per board.
- [ ] **`IMU_I2C_ID` is per-board and is NOT always 0.** On RP2040/RP2350
      each I²C peripheral is hard-wired to a fixed pin table, so the XIAO
      RP2350's labelled D4/D5 (GP6/GP7) are on I²C**1**. A wrong ID is
      rejected at *construction* with a bare `ValueError: bad SCL pin`,
      before any bus activity — so no rewiring can fix it. Four separate
      sessions lost to this one.
- [ ] **`LED_PIN` wrong is a POWER fault, not a display bug.** An
      unaddressed WS2812B strip holds whatever state it powered up in —
      possibly full white, ≈480 mA for 8 LEDs — and `BRIGHTNESS` cannot
      help, because it is a property of data you are not sending. Check it
      against `pinouts/<board>.md` *before* connecting a strip
      (`docs/insights.md` §13).
- [ ] **`TIME_SOURCE`**: `"ds3231"` for a unit with the RTC (the only source
      that survives a power cycle), `"rtc"` for a WiFi-free unit without one
      (needs `make set-time`, lost on every power cycle), `"wifi"` otherwise.
      A radio-less board must never be left on `"wifi"`.
- [ ] `make schedule` if `schedules/<station>.json` doesn't exist yet.

> `make upload` **fails fast** with a clear message if `config.py` is missing.
> That's the guard working, not a bug. Field reference: `docs/contracts/config.md`.

## 4. Upload

```bash
make upload              # lint + tests, then config, schedule and 11 modules
make upload WIFI=1       # also send net.py — WiFi units only
```

Every file is **content-hashed** on the device and compared to the host, not
just size-checked: a same-length corruption passes a size check and then
fails to compile, which reads as a bug in your own source. Files already
matching are skipped, so a re-run resumes rather than rewriting everything —
**if it fails partway, just run it again.**

`main.py` goes **last**, because it auto-runs and would otherwise compete
with `mpremote` for the serial link.

## 4b. Iterating? Don't upload at all

```bash
make dev                 # or: make dev STATION=<name>
```

`mpremote mount` serves `micropython/` as the device filesystem, so the
firmware runs from your working copy with **zero flash writes**. Edit,
Ctrl-C, re-run. The unit cannot run standalone this way, and startup is slow
(every import crosses the serial link and is compiled on-device), so use
`make upload` for a real unit — but for tuning colours, gestures or
thresholds this is the right loop.

> ⚠ **Seeding a clock copies your Mac's error into the unit.** The chain is
> `host clock → mpremote rtc --set → board RTC → rtc_test.py SYNC → DS3231`,
> and nothing in it checks the host against real time. A Mac measured at
> **+4.14 s off true time** on 2026-08-24 produced a DS3231 sitting ~2 s
> behind — a permanent floor no amount of RTC precision recovers.
>
> Harmless for a minute-granularity display, but check before seeding a unit
> you care about:
> ```bash
> make rtc-drift        # first line reports the host's offset from NTP
> ```
> If it is seconds rather than milliseconds, fix the Mac's time sync first
> (System Settings → General → Date & Time → Set automatically).

## 5. Bring-up tests — hardware only, no app logic

```bash
make led-test            # all LEDs cycle + chase
make i2c-scan            # ← START HERE for anything on I2C
make imu-test            # IMU: scan → WHO_AM_I → live accel stream
make rtc-test            # DS3231: scan → time read/write → battery-backup proof
```

> **`make i2c-scan` first.** It needs no per-board constants at all — it
> enumerates the chip's legal pin/ID combinations, reports which devices
> answered, and prints the exact `I2C_ID` / `SDA_PIN` / `SCL_PIN` values to
> paste. It exists because pin/ID mismatches cost three separate bring-up
> sessions on this project. `imu-test`/`rtc-test` then verify a chip actually
> *works*, which a scanner can't.

> ⚠ **Bring-up scripts are NOT config-driven** — each has its own per-board
> constants, edited by hand, by design. Every one now **echoes its pins on the
> first line**; if that line doesn't match your board, that's the bug. This is
> the single most repeated stumble in this project's history (`led_test.py`'s
> `DATA_PIN` at the v1.2 checkpoint, `imu_test.py`'s `SDA_PIN`/`SCL_PIN` at the
> v1.4+IMU build) — an empty I2C scan almost always means stale pins, not bad
> solder.

Expected `imu-test` output: scan shows `0x6a` or `0x6b`, `WHO_AM_I = 0x70`,
one axis near ±1000mg (gravity) at rest.

## 5b. Seed the DS3231 — the one step with an order that matters

A factory-fresh chip reports **OSF set** and reads `2000-01-01`. That is
expected the first time. It is *not* expected after a power-cycle test — that
means the CR1220 is not doing its job.

**Do this in order. Step 0 is not optional if you care about the unit.**

```bash
# 0. Is the HOST clock actually right? It gets copied straight into the chip.
make rtc-drift          # first line reports the host's NTP offset
```

Seconds rather than milliseconds → fix the Mac first (System Settings →
General → Date & Time → Set automatically). That error becomes **permanent**
in the unit; nothing downstream can recover it.

```bash
# 1. Host clock → the board's own volatile RTC
make set-time
```

```
# 2. Enable the copy, ONCE:
#    micropython/rtc_test.py →  SYNC_DS3231_FROM_BOARD_RTC = True
```

```bash
# 3. Board RTC → DS3231, and clears OSF
make rtc-test
```

```
# 4. ⚠ SET IT BACK:  SYNC_DS3231_FROM_BOARD_RTC = False
#    Leaving it True overwrites the chip's kept time on every later run —
#    destroying exactly the thing the DS3231 exists to provide. The script
#    guards against syncing from an implausible year, but do not lean on it.
```

```bash
# 5. Physically unplug. Wait. Plug back in. (NOT Ctrl-D — a soft reset does
#    not drop power and proves nothing.)
make rtc-test           # OSF clear + correct time = battery works
```

```bash
# 6. Re-seeding destroyed any drift baseline, so start a new epoch:
make rtc-drift ARGS="--mark-seed"
make rtc-drift          # lays down the first sample of the new epoch
```

> **Why step 5 is the real test.** OSF staying clear across a *physical*
> power cut is the chip's own claim that its oscillator never stopped — much
> stronger than reading back a plausible-looking time, which a chip that lost
> power at 3am and was re-powered would also do.

## 6. Run the real loop

Run it from flash (`make dev` in §4b is the no-write alternative):

```bash
make upload              # puts main.py on the device
make screen              # then press Ctrl+D to soft-reset — main.py auto-runs
```

> ⚠ **Don't use `make run` for `main.py` on the ESP32-C3.** `mpremote run`
> ships the whole source over stdin, so the device holds ~115KB of text in RAM
> *and* compiles it there — then `esp_wifi` has no heap left for its buffers
> and you get `OSError: Wifi Out of Memory` (observed for real once `main.py`
> passed ~2300 lines; it worked at the v1.2 checkpoint when the file was about
> half this size). Booting from flash avoids that peak entirely. `make run`
> is still fine for small scripts and on the roomier Pico 2W.

For standalone (auto-runs on power-up, e.g. on a Qi pad): `make upload`, then
power-cycle — same path, no laptop.

- [ ] Boot ceremony plays (loading circle → burst).
- [ ] Console prints station, contract, and per-tick departures.
- [ ] LEDs render the arc.

> **Looks dead at night?** Quiet hours (`QUIET_START_HOUR` /
> `QUIET_END_HOUR`) blanks the strip by design and is indistinguishable from a
> fault. Set `24` / `0` to disable while testing. The loop prints
> `(quiet hours — display off)` to disambiguate.

## 7. Gestures — shipped and in the main loop

Set **`GESTURE_ENABLED = True`** in `config.py`. A tap then wakes the display
and a further tap cycles which line is shown
(`docs/contracts/gesture-envelope.md` §11).

**The boot banner tells you which way it went.** Off:

```
Gestures: OFF — set GESTURE_ENABLED = True in config.py to enable taps
```

On, once the schedule loads:

```
Lines: <line>, <line>, …  (tap to cycle)
```

⚠ **`GESTURE_ENABLED` is COMMENTED OUT in `config.example.py`** (the file's
convention: commented lines show defaults). A `config.py` freshly copied
from it therefore has gestures **off**, and a wired IMU is simply never
read — indistinguishable from a broken one. That cost three rounds of
hardware debugging; `imu-test` passed cleanly throughout. Check the banner
before suspecting wiring.

Note `make screen` attaches to a loop already running, so it shows
mid-loop output, not the banner. Press **Ctrl-D** to soft-reset and watch
from the top.

| Gate | Runs | What it is |
|---|---|---|
| `GESTURE_DEBUG_ENABLED=True` | `_run_gesture_debug_loop()` | Terminal-only gesture exerciser. Bypasses time source, schedule and boot ceremony. **No LED output.** A bring-up tool, not a display mode. |
| `GESTURE_ENABLED=True` | `_run_interactive_loop()` | The real loop **with** taps. Prints the `Lines: … (tap to cycle)` banner. |
| both `False` | `_run_classic_loop()` | The real display loop, no IMU. What §6 describes. |

> `WAKE_INTERACTION_ENABLED` still works as an alias so older `config.py`
> files keep running, but prefer `GESTURE_ENABLED`. (Its historical warning —
> that the tap detector was a stub returning `False` — no longer applies; that
> stub was replaced by the shipped recognizer.)

Iterate on jolt shape and thresholds without the full loop:

```bash
make run-file FILE=micropython/gesture_sandbox.py    # real taps → real LED jolt
```

---

## Quick reference

| Task | Command |
|---|---|
| **Is this board healthy?** | `make doctor` |
| Host tests + lint | `make test` |
| **Iterate with no flash writes** | `make dev` |
| Push firmware | `make upload` |
| Recover an unreachable board | `make flash-micropython BOARD=<b> WIPE=1` |
| Measure DS3231 drift | `make rtc-drift` |
| Run live, don't persist | `make run` |
| Run any one script | `make run-file FILE=<path>` |
| Make a script auto-run on boot | `make upload-file FILE=<path>` |
| REPL | `make screen` (Ctrl+] to exit) |
| Clean capture files off device | `make clear-vibes` |
