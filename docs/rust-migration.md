# V1 → V2: MicroPython → Rust (Embassy)

V1 (MicroPython) exists to validate the logic; V2 rewrites the firmware in Rust
on Embassy as a deliberate learning exercise. This is the running map of how V1
constructs translate. See the teaching directive in `CLAUDE.md` for *how* to
work through it.

## API / construct map

| MicroPython (V1) | Rust/Embassy (V2) |
|---|---|
| `connect_wifi()` | `embassy_net` + CYW43 driver (or removed entirely) |
| `ntptime.settime()` | DS3231 over I2C; `embassy_time` for scheduling |
| `json.load(f)` | `build.rs` reads JSON at compile time → `const` arrays |
| `classify(ttl) -> Urgency` (singletons) | `enum Urgency` + `impl From<f32>` |
| `DisplayContract` (duck-typed strategy) | `trait DisplayContract` + `dyn`/generic dispatch |
| WS2812B via `neopixel` | PIO program driving the strip (RP2350 has PIO) |
| `time.sleep(30)` / `frame_ms` loop | `Timer::after(Duration::from_secs(30)).await` vs a frame loop |
| `network.WLAN` | `cyw43::Control` |
| `Pin("LED")` | `cyw43.set_led(true)` |
| `schedule["weekday"]["a"]` | `const WEEKDAY_A: &[u16] = &[...]` |

## Scaffolding order (tentative)

1. Embassy project: `rust/`, `Cargo.toml`, `.cargo/config.toml`.
2. Blink the onboard LED (hello world).
3. WS2812B output via PIO (port `led_test.py`).
4. Port Stage 1 (pure logic): `Urgency`, `time_to_leave`, `classify`, `LeaveSignal`.
5. Port Stage 2: `DisplayContract` trait + `SandTimer`.
6. Replace WiFi+NTP with DS3231 over I2C.
7. Deep sleep between ticks (static contracts only).
8. Schedule as `const` arrays via `build.rs`.

## Notes

- The Stage 1 / Stage 2 seam (`docs/contracts/display-contract.md`) carries over
  cleanly: Stage 1 is pure data, Stage 2 is a trait. The `frame_ms is None`
  branch becomes the deep-sleep-vs-frame-loop decision — and animated contracts
  remain incompatible with deep sleep.
- MCU decision (RP2350 vs ESP32-C3) is still open — see `dev-status.md`.
