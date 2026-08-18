# Contract: config.py

**File on device:** `config.py`  
**Template:** `micropython/config.example.py`  
**Gitignored:** yes — never commit real credentials  

---

## How fields are read

Only `WIFI_SSID` / `WIFI_PASS` are **required** — `main.py` imports them directly,
so a missing value fails loudly. Everything else is **optional**: `main.py` reads
it with `getattr(config, "NAME", default)`, so

- a `config.py` written before a field existed keeps working (uses the default), and
- you only need to list the fields you actually want to override.

## Fields

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `WIFI_SSID` | str | **yes** (V1) | — | Network name. Removed in V2 (WiFi dormant) |
| `WIFI_PASS` | str | **yes** (V1) | — | Network password. Removed in V2 |
| `UTC_OFFSET_HOURS` | int | no | `9` | JST = UTC+9. Clock display + weekday detection |
| `LOOP_INTERVAL_SECS` | int | no | `30` | How often the loop recomputes + updates |
| `SCHEDULE_FILE` | str | no | `"schedule.json"` | Filename on device filesystem |
| `DISPLAY_DIRECTION` | str | no | `"b"` | Which schedule direction key the LED ring follows (one ring, no magnetometer in V1). Feeds arm A when `DISPLAY_DIRECTION_B` is also set |
| `DISPLAY_DIRECTION_B` | str | no | `None` | **`approach` phase 2 (bidirectional) only.** A second schedule direction key, feeding arm B — one train per arm. `None` = single-direction, phase 1 unchanged. Ignored (not an error) by every other contract |
| `WALK_TO_STATION_MINS` | float | no | `2.5` | Room→platform time; subtracted from each departure. Trains you can't catch are hidden. `[→ NFC]` later from the station card |
| `LED_PIN` | int | no | `6` | GP pin driving the WS2812B data line |
| `NUM_LEDS` | int | no | `8` | LEDs on the strip (stick = 8; V1.5 ring = 12) |
| `ARC_ORIGIN` | str | no | `"near"` | Which end the arc grows from: `"near"` = DIN end (index 0), `"far"` = the other end. Logical, not physical — flip when the strip mounts upside-down. Applied in `_physical()`, the HAL seam |
| `HEARTBEAT_PIN` | str/int/`None` | no | `"LED"` | Status heartbeat LED. `"LED"` is a **Pico 2W–only** alias (routed via the CYW43 WiFi chip). Other boards have no such alias — set a GPIO number (see `pinouts/<board>.md`) or `None` to disable. The console heartbeat (●/○) is unaffected either way |
| `BRIGHTNESS` | float | no | `0.15` | `0.0–1.0` global brightness ceiling |
| `CONTRACT` | str | no | `"sandtimer"` | Active display strategy: `"sandtimer"` \| `"color"` \| `"breathing"` \| `"breathing_exponent"` \| `"breathing_inverse"` \| `"echo"` \| `"approach"` |
| `COLOR_SCHEME` | str | no | `"default"` | Urgency→colour palette: `"default"` \| `"sunset"` \| `"mono"` |
| `MINUTES_PER_LED` | int | no | `1` | Arc geometry: minutes-to-leave each LED represents |
| `URGENCY_THRESHOLDS` | tuple | no | `(2, 5)` | Minutes-to-leave band edges → `LEVEL_1` (`< 2`), `LEVEL_2` (`2–5`), `LEVEL_3` (`≥ 5`) |
| `GAMMA` | float | no | `2.2` | Perceptual brightness curve applied to animation multipliers (`gamma()`). Higher = smoother dim-end fades. `1.0` = linear/off |
| `BREATHE_PERIOD_MS` | int | no | `8000` | Length of one breath cycle, ms (breathing contracts) |
| `BREATHE_FLOOR` | float | no | `0.2` | Dim end of the breath (`0.0–1.0`); raise if `GAMMA` dims the trough too far |
| `DITHER` | bool | no | `True` | Temporal dithering in `_paint` — averages sub-integer brightness across frames to smooth low-end banding. `False` = plain `int()` truncation |
| `FRAME_MS` | int | no | `16` | Animation frame duration, ms — **animated contracts only** (static contracts keep `frame_ms=None` and ignore it). Lower = smoother animation + dither, more CPU |
| `N_TRAINS` | int | no | `1` | How many upcoming departures to render simultaneously (`1` = original single-train behaviour). `sandtimer`/`breathing*`: nested arcs, dimmed via `BACKGROUND_BRIGHTNESS`. `approach`: one marker per arm slot, hue-shifted via `SECONDARY_HUE_SHIFT_DEG` (never dimmed — see `docs/contracts/approach-contract.md` § N trains per arm). `color` ignores it, no arc geometry to layer onto |
| `BACKGROUND_BRIGHTNESS` | float | no | `0.35` | Relative brightness of the 2nd train's band (0..1); the 3rd gets this squared, etc. — geometric falloff, one knob regardless of `N_TRAINS`. Used by `sandtimer`/`breathing*`; `echo` ignores it (see below) |
| `SECONDARY_HUE_SHIFT_DEG` | int | no | `20` | **`echo` and `approach` (with `N_TRAINS>1`).** Hue rotation (degrees) per train index beyond the primary — differentiates by colour instead of brightness |
| `SECONDARY_BREATHE_PERIOD_MS` | int | no | `3000` | **`echo` only.** Breath cycle length for trains beyond the primary |
| `SECONDARY_BREATHE_FLOOR` | float | no | `0.7` | **`echo` only.** Deliberately high — a subtle differentiation pulse, not `BreathingContract`'s dramatic urgency breath. Separate knob so tuning one doesn't fight the other |
| `ANCHOR_INDEX` | int | no | `0` | **`approach` only.** LED index of the station/anchor position. See `docs/contracts/approach-contract.md` |
| `ARM_A_LEN` | int | no | `NUM_LEDS - 1` | **`approach` only.** LEDs available outward from the anchor, direction A |
| `ARM_B_LEN` | int | no | `0` | **`approach` only.** LEDs available outward from the anchor, direction B (`0` = single-direction phase 1 layout) |
| `ANCHOR_COLOR` | tuple | no | `(255, 200, 120)` | **`approach` only.** Always-on anchor ("the 0") colour — distinct from `LINE_COLOR` and `MARKER_COLOR` |
| `ANCHOR_BRIGHTNESS` | float | no | `1.6` | **`approach` only.** Anchor brightness relative to a normal "full" position (`1.0`); `>1.0` makes it genuinely brighter, not just differently coloured. Rendered via the STATIC path (linear, no gamma) |
| `POSITION_MINUTES_PER_LED` | int | no | `1` | **`approach` only.** Minutes-to-leave each LED of offset from the anchor represents |
| `LINE_COLOR` | tuple | no | `(34, 139, 34)` (forest green) | **`approach` only.** Fixed train colour — deliberately *not* urgency-banded, since position already encodes urgency continuously in this paradigm. Where the train currently is renders at `BRIGHTNESS` directly (no separate brightness knob) |
| `LINE_SATURATION` | float | no | `1.0` | **`approach` only.** `1.0` = unchanged; lower = a genuinely muted/desaturated `LINE_COLOR` (via `desaturate()`), not just a dimmer one — see `docs/contracts/approach-contract.md` |
| `MARKER_BRIGHTNESS` | float | no | `0.15` | **`approach` only.** LINEAR multiplier of `BRIGHTNESS` for the idle "tick" LEDs — every position that isn't the anchor or the train right now. Rendered STATIC (no gamma, no dither; see `docs/contracts/approach-contract.md` § Marker ticks), so pick a value that clears ~1 output code per `MARKER_COLOR` channel or it truncates invisibly to black. `0` = fully off. A train is never dimmer than `BRIGHTNESS` itself, so this never applies to it |
| `MARKER_COLOR` | tuple | no | `(80, 80, 80)` | **`approach` only.** Idle tick-LED colour — deliberately *not* a dimmed `LINE_COLOR`, so an empty tick can't read as "a very distant train" |
| `TRANSITION_MS` | int | no | `4000` | **`approach` only.** Chase-transition duration between position updates, ms; `0` = instant single-frame switch |
| `STARTUP_COLOR` | tuple | no | `(255, 255, 255)` | Boot-ceremony loading-circle + success-burst colour. All LEDs together, contract-agnostic — see `docs/contracts/startup-sequence.md` |
| `STARTUP_SPIN_HZ` | float | no | `0.4` | Loading-circle revolutions/sec while connecting (WiFi + NTP) |
| `STARTUP_BURST_MS` | int | no | `800` | Success-burst rise duration, ms |
| `STARTUP_FADE_MS` | int | no | `1500` | Success-burst decay duration, ms — after which the main loop takes over (no crossfade; see the doc's Handoff section) |
| `ERROR_COLOR` | tuple | no | `(255, 0, 0)` | Persistent failure state (WiFi connect fails) — all LEDs, forever, until reset |
| `ERROR_BREATHE_PERIOD_MS` | int | no | `4000` | Failure-state breathe period — deliberately separate from `BREATHE_PERIOD_MS` |
| `WAKE_INTERACTION_ENABLED` | bool | no | `False` | **Safety gate** — see `docs/contracts/wake-interaction.md`. No IMU wired yet; enabling with the sensor still stubbed puts the display permanently ASLEEP after `WAKE_MINUTES` with no way to wake it. Leave `False` until a real sensor read exists |
| `WAKE_MINUTES` | int | no | `30` | Active-display window after any wake/extend trigger |
| `DOUBLE_TAP_WINDOW_MS` | int | no | `400` | Max gap between two taps to count as a double-tap — GUESS, tune against real sensor data |
| `TAP_THRESHOLD` | float | no | `2.0` | Accelerometer magnitude threshold for "a tap happened" — UNTESTED GUESS, not read by the current stub |
| `SECONDARY_ACTION` | str | no | `"brightness_cycle"` | What a single tap while AWAKE does — pluggable, only one action implemented |
| `BRIGHTNESS_PRESETS` | tuple | no | `(0.15, 0.35, 0.6)` | Levels `SECONDARY_ACTION="brightness_cycle"` cycles through |
| `EXTEND_CONFIRM_COLOR` | tuple | no | `STARTUP_COLOR` | Double-tap-while-AWAKE confirmation colour |
| `EXTEND_CONFIRM_MS` | int | no | `600` | Duration of the extend confirmation |
| `IMU_I2C_ID` | int | no | `0` | **Gesture envelope** (`docs/contracts/gesture-envelope.md`). Hardware I2C peripheral index |
| `IMU_SDA_PIN` | int | no | `0` | **Gesture envelope.** Board-specific — see `pinouts/<board>.md` (Pico 2W default shown) |
| `IMU_SCL_PIN` | int | no | `1` | **Gesture envelope.** Board-specific — see `pinouts/<board>.md` |
| `GESTURE_DEBUG_ENABLED` | bool | no | `False` | **Gesture envelope.** Terminal-only validation loop (`_run_gesture_debug_loop`) — prints state transitions instead of rendering LEDs, bypasses WiFi/schedule/boot entirely. Own flag, deliberately separate from `WAKE_INTERACTION_ENABLED` |
| `GESTURE_FLIP_ENABLED` | bool | no | `False` | **Gesture envelope.** Orientation/flip detection — requires wired (USB) power; flipping a Qi-mounted jar breaks inductive coupling |
| `GESTURE_POSITION_ENABLED` | bool | no | `False` | **Gesture envelope.** Shoulder-vs-base tap disaggregation — ~78-81% even on a bottle it's tuned for (`docs/insights.md` §8-9), optional |
| `GESTURE_FLICK_ENABLED` | bool | no | `True` | **Gesture envelope.** Best-validated signal after tap presence — on by default |
| `TAP_TRIGGER_THRESHOLD_MG` | int | no | `50` | **Gesture envelope.** Cheap first-pass gate only — deliberately permissive; the recognizer, not this trigger, does the real tap/flick/noise discrimination |
| `FLICK_MAGNITUDE_THRESHOLD_MG` | int | no | `328` | **Gesture envelope.** Flick vs. soft tap — chianti-bottle value, re-derive per physical unit. Recalibrated against shoulder+base taps (95.2%) after real-hardware testing found the original 140 (calibrated against body taps only) let 79% of ordinary shoulder taps through as false flicks |
| `FLICK_SPACING_STDEV_THRESHOLD_MS` | int | no | `5` | **Gesture envelope.** Flick vs. hard handling — the feature that actually separates them (magnitude alone caps ~80%, `docs/insights.md` §9) |
| `POSITION_THRESHOLD_MG` | int | no | `151` | **Gesture envelope.** Only read if `GESTURE_POSITION_ENABLED` |
| `ORIENTATION_STABLE_MG` | int | no | `700` | **Gesture envelope.** Below this, a reading is "mid-motion," not a resting orientation |
| `ORIENTATION_MAP` | tuple of tuples | no | `(("upright","y",1), ("horizontal","z",-1), ("upside_down","y",-1))` | **Gesture envelope.** `(state name, dominant axis, sign)` — depends entirely on how the IMU is physically mounted on a given bottle, re-derive with `orientation_test.py` per unit |
| `GESTURE_MENU_OPTIONS` | tuple | no | `("Item 1", "Item 2", "Item 3")` | **Gesture envelope.** Placeholder scrollwheel content — the real option list is a product decision, not yet made (`docs/contracts/gesture-envelope.md` §9) |
| `GESTURE_MODE_TIMEOUT_MS` | int | no | `15000` | **Gesture envelope.** Bounded return to ambient — same philosophy as `WAKE_MINUTES` |
| `STATUS_LED_INDEX` | int | no | `NUM_LEDS // 2` | Shared "middle-ish" position for brief acknowledgments — see `docs/contracts/led-status-messages.md`. Deliberately not `ANCHOR_INDEX`, stays contract-agnostic |
| `QUIET_TAP_COLOR` | tuple | no | `(128, 0, 200)` | Acknowledgment colour for a tap during quiet hours (purple) |
| `QUIET_TAP_DURATION_MS` | int | no | `2500` | Duration of the quiet-hours acknowledgment |
| `NO_DATA_COLOR` | tuple | no | `(200, 160, 0)` | Acknowledgment colour for waking up to no catchable trains (gold) |
| `NO_DATA_DURATION_MS` | int | no | `2500` | Duration of the no-data acknowledgment |
| `SCHEDULE_ERROR_COLOR` | tuple | no | `(200, 0, 120)` | Persistent failure colour for a missing/corrupt `schedule.json` — distinct from `ERROR_COLOR` (WiFi/NTP failure) |
| `QUIET_START_HOUR` | int | no | `23` | Hour the strip goes dark |
| `QUIET_END_HOUR` | int | no | `6` | Hour the strip wakes (window may wrap past midnight) |

The display fields (`CONTRACT`, `COLOR_SCHEME`, `MINUTES_PER_LED`,
`URGENCY_THRESHOLDS`, `BRIGHTNESS`, …) drive the rendering pipeline documented in
`docs/contracts/display-contract.md`. The `CONTRACT` and `COLOR_SCHEME` *names*
are resolved against the `CONTRACTS` / `SCHEMES` registries in `main.py` — add an
entry there to expose a new strategy or palette to config.

## V1 vs V2 note

WiFi credentials exist only in V1 (MicroPython + NTP).  
In V2 (Rust + DS3231 RTC), `WIFI_SSID` and `WIFI_PASS` are removed entirely.  
`config.py` is replaced by compile-time constants or a separate NFC-provisioned config.

## Secrets handling (V1)

The WiFi creds are the only secret in V1. `config.py` is **gitignored** and
edited by hand:

```bash
cp micropython/config.example.py micropython/config.py   # then fill in SSID/pass
```

It already lives on the Pico, so you can also edit it on-board via Thonny.

**Threat model:** the Pico 2W has no secure enclave, so `config.py` is plaintext
both on the host and on the device. For a single-user, local device this is an
accepted tradeoff — gitignored is enough to keep creds out of version control. A
vault-based flow (e.g. KeePassXC) was considered and **tabled**; revisit only if
the repo is ever shared or wired into CI. In V2 the creds disappear entirely
(config is provisioned over NFC; no WiFi in normal operation).
