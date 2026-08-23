# Provisioning runbook — bare board to running unit

_One-glance checklist for building a unit from scratch. **Deliberately terse**
— every step links to the detail rather than repeating it. First walked
end-to-end 2026-08-16 on the v1.4+IMU dev unit
(`pinouts/v1.4-imu-dev-unit.md`)._

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

## 3. Config

- [ ] `cp micropython/config.example.py micropython/config.py`, fill in WiFi.
- [ ] Set the **board-specific** values: `LED_PIN`, `NUM_LEDS`,
      `HEARTBEAT_PIN` (`None` on XIAO), `IMU_SDA_PIN` / `IMU_SCL_PIN`.
- [ ] `make schedule` if `schedules/<station>.json` doesn't exist yet.

> `make upload` **fails fast** with a clear message if `config.py` is missing.
> That's the guard working, not a bug. Field reference: `docs/contracts/config.md`.

## 4. Upload

```bash
make upload              # runs make test first, then copies main/config/schedule
```

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

## 6. Run the real loop

Set both gates **off** in `config.py`, then **run it from flash**:

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

## 7. Gesture testing — separate, not in the main loop yet

⚠ **Tapping the real main loop does nothing today.** The gesture-envelope work
(`classify_valid_input`, `_TapCycleState`, the ACK/CONFIRM jolt) is validated
but lives in `micropython/gesture_sandbox.py`, not in `main()`. See
`docs/contracts/gesture-envelope.md` §11's "not yet done."

```bash
make run-file FILE=micropython/gesture_sandbox.py    # real taps → real LED jolt
```

`main.py`'s two IMU-related config gates and what they actually do:

| Gate | Runs | Reality |
|---|---|---|
| `GESTURE_DEBUG_ENABLED=True` | `_run_gesture_debug_loop()` | Terminal-only multi-gesture exerciser. Bypasses WiFi/schedule/boot entirely. **No LED output.** |
| `WAKE_INTERACTION_ENABLED=True` | `_run_interactive_loop()` | ⚠ **Don't** — its `_imu_tap_detected()` is still a stub returning `False`, so the display sleeps after `WAKE_MINUTES` and can never wake. |
| both `False` | `_run_classic_loop()` | The real display loop. What you want for §6. |

---

## Quick reference

| Task | Command |
|---|---|
| Host tests only | `make test` |
| Push firmware | `make upload` |
| Run live, don't persist | `make run` |
| Run any one script | `make run-file FILE=<path>` |
| Make a script auto-run on boot | `make upload-file FILE=<path>` |
| REPL | `make screen` (Ctrl+] to exit) |
| Clean capture files off device | `make clear-vibes` |
