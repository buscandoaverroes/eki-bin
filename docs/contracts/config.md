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
| `DISPLAY_DIRECTION` | str | no | `"b"` | Which schedule direction key the LED ring follows (one ring, no magnetometer in V1) |
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
| `N_TRAINS` | int | no | `1` | How many upcoming departures to render as nested arcs (`1` = original single-arc behaviour). `sandtimer`/`breathing*` only — `color` ignores it, no arc geometry to layer onto |
| `BACKGROUND_BRIGHTNESS` | float | no | `0.35` | Relative brightness of the 2nd train's band (0..1); the 3rd gets this squared, etc. — geometric falloff, one knob regardless of `N_TRAINS`. Used by `sandtimer`/`breathing*`; `echo` ignores it (see below) |
| `SECONDARY_HUE_SHIFT_DEG` | int | no | `20` | **`echo` only.** Hue rotation (degrees) per train index beyond the primary — differentiates by colour instead of brightness |
| `SECONDARY_BREATHE_PERIOD_MS` | int | no | `3000` | **`echo` only.** Breath cycle length for trains beyond the primary |
| `SECONDARY_BREATHE_FLOOR` | float | no | `0.7` | **`echo` only.** Deliberately high — a subtle differentiation pulse, not `BreathingContract`'s dramatic urgency breath. Separate knob so tuning one doesn't fight the other |
| `ANCHOR_INDEX` | int | no | `0` | **`approach` only.** LED index of the station/anchor position. See `docs/contracts/approach-contract.md` |
| `ARM_A_LEN` | int | no | `NUM_LEDS - 1` | **`approach` only.** LEDs available outward from the anchor, direction A |
| `ARM_B_LEN` | int | no | `0` | **`approach` only.** LEDs available outward from the anchor, direction B (`0` = single-direction phase 1 layout) |
| `ANCHOR_COLOR` | tuple | no | `(255, 200, 120)` | **`approach` only.** Always-on anchor colour — distinct from `LINE_COLOR` and `FLOOR_COLOR` |
| `ANCHOR_BRIGHTNESS` | float | no | `1.6` | **`approach` only.** Anchor brightness relative to a normal "full" position (`1.0`); `>1.0` makes it genuinely brighter, not just differently coloured. Rendered via the STATIC path (linear, no gamma) |
| `POSITION_MINUTES_PER_LED` | int | no | `1` | **`approach` only.** Minutes-to-leave each LED of offset from the anchor represents |
| `LINE_COLOR` | tuple | no | `(34, 139, 34)` (forest green) | **`approach` only.** Fixed train colour — deliberately *not* urgency-banded, since position already encodes urgency continuously in this paradigm |
| `MARKER_SATURATION` | float | no | `1.0` | **`approach` only.** `1.0` = unchanged; lower = a genuinely muted/desaturated `LINE_COLOR` (via `desaturate()`), not just a dimmer one — see `docs/contracts/approach-contract.md` |
| `FLOOR_BRIGHTNESS` | float | no | `0.15` | **`approach` only.** LINEAR multiplier of `BRIGHTNESS` for idle (non-anchor, non-train) LEDs — rendered STATIC (no gamma, no dither; see `docs/contracts/approach-contract.md` § Floor), so pick a value that clears ~1 output code per `FLOOR_COLOR` channel or it truncates invisibly to black. `0` = fully off. Deliberately **not** read by the marker's crossfade — see `MARKER_BRIGHTNESS`/`MARKER_FADE_FLOOR` |
| `FLOOR_COLOR` | tuple | no | `(80, 80, 80)` | **`approach` only.** Idle-LED colour — deliberately *not* a dimmed `LINE_COLOR`, so an empty slot can't read as "a very distant train" |
| `MARKER_BRIGHTNESS` | float | no | `1.0` | **`approach` only.** Settled marker's own mult (STATIC path, linear) — independent of `FLOOR_BRIGHTNESS`; tuning the idle floor no longer drags the marker's brightness along with it |
| `MARKER_FADE_FLOOR` | float | no | `0.3` | **`approach` only.** Dim end of the marker's own crossfade envelope (ANIMATED path) — independent of `FLOOR_BRIGHTNESS`, which governs only genuinely idle LEDs |
| `TRANSITION_MS` | int | no | `4000` | **`approach` only.** Crossfade duration between position updates, ms; `0` = instant jump |
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
