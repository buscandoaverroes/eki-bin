# micropython/config.example.py
# Committed template — copy to config.py and fill in real values.
# config.py is gitignored and never committed. You can also edit config.py
# directly on the board via Thonny (it already lives on the device).
#
# Only WIFI_SSID / WIFI_PASS are required. Every other field below is OPTIONAL:
# main.py reads it with a built-in default, so you can delete any line you don't
# want to change (and older config.py files keep working unchanged).
#
# Anything COMMENTED OUT below is showing you its default — uncomment only to
# change it. Anything ACTIVE is either required, or a value worth stating
# explicitly because the right setting depends on your hardware.
#
# See docs/contracts/config.md for full field documentation, and
# docs/provisioning-runbook.md for the build-a-unit-from-scratch checklist.

# ══ ① BOARD-SPECIFIC — set these FIRST ═══════════════════════════════
# These are the values that differ per board, and getting one wrong is the
# single most common bring-up failure in this project's history. Grouped
# here rather than scattered through the file for exactly that reason.
#
#   Value           | Pico 2W | XIAO ESP32-C3 |
#   ----------------|---------|---------------|
#   LED_PIN         | 6       | 2             |
#   HEARTBEAT_PIN   | "LED"   | None          |
#   IMU_SDA_PIN     | 0       | 6             |
#   IMU_SCL_PIN     | 1       | 7             |
#
# Physical wiring for each: pinouts/<board>.md — that directory is the
# source of truth for what's connected where; this file just mirrors it.

LED_PIN = 6  # GPIO driving the WS2812B data line
NUM_LEDS = 8  # AE-WS2812B-STICK8 = 8; gift-jar strip = 21; 4020 tape = 120
HEARTBEAT_PIN = "LED"  # status LED. "LED" is a **Pico-2W-only** alias (routed
#                        through the CYW43 WiFi chip). On ANY other board it
#                        raises `ValueError: invalid pin` — set a GPIO number,
#                        or bare None (NOT the string "none"!) to disable.
#                        A quoted "none" is a truthy string main.py would try
#                        to use as a real pin name; tests/test_real_config.py
#                        catches that one before `make upload`.

# IMU (LSM6DSV16X) — only read if you've actually wired one.
IMU_I2C_ID = 0  # ESP32 maps I2C to any pins in software, so 0 works on both
IMU_SDA_PIN = 0
IMU_SCL_PIN = 1

# ══ ② WiFi — the only genuinely required fields ══════════════════════
# (V1 only — removed in V2 when a DS3231 RTC replaces NTP.)

WIFI_SSID = "your_network_name"
WIFI_PASS = "your_network_password"

# ── Timezone / loop ───────────────────────────────────────────────
UTC_OFFSET_HOURS = 9  # JST = UTC+9
LOOP_INTERVAL_SECS = 30  # seconds between display updates
SCHEDULE_FILE = "schedule.json"  # filename on device filesystem

# ── Which trains ──────────────────────────────────────────────────
DISPLAY_DIRECTION = "b"  # which timetable direction the ring shows
#                          (V1 has no magnetometer; matches a key in schedule.json)
# DISPLAY_DIRECTION_B = "a"  # "approach" contract, phase 2 (bidirectional)
#                          only — a SECOND direction key, feeding arm B.
#                          Unset = single-direction, phase 1. Also needs
#                          ARM_B_LEN > 0 in the approach block below.
WALK_TO_STATION_MINS = 2.5  # room→platform; trains you can't catch are hidden

# ── Display: look & feel ──────────────────────────────────────────
ARC_ORIGIN = "far"  # which end the arc grows from: "near" = DIN end (index 0),
#                     "far" = the other end. Mount-specific, not board-specific
#                     — flip if the strip ends up mounted upside-down.
BRIGHTNESS = 0.15  # 0.0–1.0 global ceiling — ambient, not blinding
CONTRACT = "breathing"  # "sandtimer" | "color" | "breathing"
#                         | "breathing_exponent" | "breathing_inverse" | "echo"
#                         | "approach"
COLOR_SCHEME = "default"  # "default" | "sunset" | "mono"
MINUTES_PER_LED = 1  # arc: minutes-to-leave each LED represents
URGENCY_THRESHOLDS = (2, 5)  # minutes-to-leave band edges → LEVEL_1 / 2 / 3
GAMMA = 2.2  # perceptual brightness curve (higher = smoother dim-end fades)
BREATHE_PERIOD_MS = 8000  # length of one breath, ms (breathing contracts)
BREATHE_FLOOR = 0.2  # dim end of the breath, 0..1 (raise if gamma makes it vanish)
DITHER = True  # temporal dithering — smooths low-end brightness steps (set False to A/B)
FRAME_MS = 16  # frame duration, ms (breathing contracts)
N_TRAINS = 2  # how many upcoming departures to show as nested arcs (1 = just
#               the primary — the original behaviour). sandtimer/breathing only;
#               color ignores this (no arc geometry to layer a 2nd train onto).
BACKGROUND_BRIGHTNESS = 0.35  # 0..1; relative brightness of the 2nd train's
#               band; the 3rd gets this squared, etc. (geometric falloff)
#               Used by sandtimer/breathing. echo ignores this — see below.

# "echo" contract only — differentiates further-out trains by HUE + gentle
# breathing that stays near-full brightness, instead of dimming (dimming alone
# looked bad on real hardware — flicker + visible LED die; see insights.md §6).
SECONDARY_HUE_SHIFT_DEG = 20  # degrees per train index beyond the primary
SECONDARY_BREATHE_PERIOD_MS = 3000  # ms per breath cycle
SECONDARY_BREATHE_FLOOR = 0.7  # high — subtle motion, not a dim/urgent pulse

# "approach" contract only — positional/approach paradigm, see
# docs/contracts/approach-contract.md. A train renders as a single LED that
# moves toward ANCHOR_INDEX as it nears, instead of a growing/shrinking arc.
# ANCHOR_INDEX = 0        # LED index of the station/anchor position
# ARM_A_LEN = 20          # LEDs available outward from the anchor, direction A
# ARM_B_LEN = 0           # direction B; 0 = single-direction (phase 1) layout
# ANCHOR_COLOR = (255, 200, 120)  # always-on anchor ("the 0") colour
# ANCHOR_BRIGHTNESS = 1.6  # >1.0 = brighter than a normal "full" position
# POSITION_MINUTES_PER_LED = 1    # minutes-to-leave per LED of offset
# LINE_COLOR = (34, 139, 34)      # forest green — fixed, not urgency-banded.
#                            Where the train currently is renders at
#                            BRIGHTNESS directly — no separate brightness knob.
# LINE_SATURATION = 1.0    # 1.0=unchanged; lower = a genuinely MUTED
#                            (desaturated) LINE_COLOR, not just a dimmer one
# MARKER_BRIGHTNESS = 0.15  # LINEAR mult of BRIGHTNESS (no gamma, no dither —
#                            avoids low-brightness flicker) for the idle
#                            "tick" LEDs — 0 = fully off. A train is never
#                            dimmer than BRIGHTNESS itself.
# MARKER_COLOR = (80, 80, 80)     # idle tick-LED colour, NOT a dimmed LINE_COLOR
# TRANSITION_MS = 4000     # chase-transition duration, ms; 0 = instant switch.
#                            A moving highlight sweeps LED-by-LED between old
#                            and new positions, always at full brightness —
#                            never a dim intermediate value (avoids low-
#                            brightness dithering flicker on this hardware).
# N trains per arm (iteration 2) reuses N_TRAINS/SECONDARY_HUE_SHIFT_DEG
# above — trains beyond the primary are hue-shifted, never dimmed (same
# reasoning as "echo" above, and everything CHASE already does).

# ── Boot ceremony — see docs/contracts/startup-sequence.md ─────────
# Runs once at power-on, before the main loop; never recurs during normal
# operation. All LEDs together, contract-agnostic (no CONTRACT is "current"
# yet at boot time).
# STARTUP_COLOR = (255, 255, 255)  # loading-circle + success-burst colour
# STARTUP_SPIN_HZ = 0.4     # loading-circle revolutions/sec while connecting
# STARTUP_BURST_MS = 800    # success burst: rise duration, ms
# STARTUP_FADE_MS = 1500    # success burst: decay duration, ms — then the
#                              main loop takes over (no crossfade blend —
#                              would reintroduce the low-brightness dithering
#                              CHASE was built to eliminate, see the doc)

# Terminal failure states — persistent breathe, forever, until reset. Each
# failure CAUSE gets its own colour on purpose so a unit with no laptop
# attached still tells you WHICH thing broke (led-status-messages.md).
# ERROR_COLOR = (255, 0, 0)         # WiFi/NTP connect failure — red
# SCHEDULE_ERROR_COLOR = (200, 0, 120)  # schedule.json missing/corrupt
# CONFIG_ERROR_COLOR = (255, 140, 0)    # a bad config VALUE here — orange.
#                            (e.g. HEARTBEAT_PIN="LED" on a non-Pico board.)
#                            Note LED_PIN/NUM_LEDS can't be covered: they're
#                            consumed at import time to build the strip
#                            itself, so getting those wrong fails before any
#                            LED can light. Those two need a serial console.
# ERROR_BREATHE_PERIOD_MS = 4000    # separate from BREATHE_PERIOD_MS on purpose

# ── Wake/sleep interaction layer — docs/contracts/wake-interaction.md ──
# ⚠ SUPERSEDED by the gesture envelope below, and **leave this False**.
# _imu_tap_detected() is still a stub that always returns False, so enabling
# this puts the display permanently ASLEEP after WAKE_MINUTES with no way to
# wake it — true even now that a real IMU is wired, because this older loop
# doesn't read it. The newer gesture work lives in gesture_sandbox.py and is
# not yet integrated into main()'s real loop.
# WAKE_INTERACTION_ENABLED = False
# WAKE_MINUTES = 30            # active-display window after any wake/extend
# DOUBLE_TAP_WINDOW_MS = 400   # GUESS — tune against the real sensor
# TAP_THRESHOLD = 2.0          # UNTESTED GUESS — not even read by the stub yet
# SECONDARY_ACTION = "brightness_cycle"   # single tap while AWAKE
# BRIGHTNESS_PRESETS = (0.15, 0.35, 0.6)  # SECONDARY_ACTION's levels
# EXTEND_CONFIRM_COLOR = STARTUP_COLOR    # double-tap-while-AWAKE confirmation
# EXTEND_CONFIRM_MS = 600

# ── Gesture envelope — docs/contracts/gesture-envelope.md ──────────────
# ⚠ GESTURE_DEBUG_ENABLED = True makes main() run a TERMINAL-ONLY debug loop
# and return — no WiFi, no schedule, no boot ceremony, NO LED OUTPUT AT ALL.
# It's a bring-up tool, not a display mode. Leave it False (the default) for
# a normal unit; flip it on deliberately when you want the IMU exerciser over
# `make screen`.
#
# Threshold VALUES below are PER-PHYSICAL-UNIT — amplitude features do not
# transfer between bottles (cross-bottle position accuracy measured 0%, worse
# than random; docs/insights.md §9). Re-derive per unit with
# vibration_sandbox.py + scripts/analyze_taps.py rather than copying these.
# GESTURE_DEBUG_ENABLED = False       # terminal-only IMU exerciser, see above
# GESTURE_FLIP_ENABLED = False        # orientation detection; needs wired
#                                       power — incompatible with Qi (flipping
#                                       the jar breaks the charging coupling)
# GESTURE_POSITION_ENABLED = False    # shoulder-vs-base — only ~78-81% even
#                                       tuned, and per-bottle calibrated
# GESTURE_FLICK_ENABLED = False       # best-validated signal after tap presence
# TAP_TRIGGER_THRESHOLD_MG = 50       # cheap gate only — real handling motion
#                                       crosses this too; the recognizer does
#                                       the real discrimination, not this
# TAP_ENERGY_THRESHOLD = 138000       # the v1 tap-vs-noise call (98.4%) — a
#                                       tap reads BELOW this; harder/"rocking"
#                                       contact reads above and is rejected
# FLICK_MAGNITUDE_THRESHOLD_MG = 328  # recalibrated against shoulder+base taps
#                                       (95.2%); the original 140 was derived
#                                       from body taps only and let 79% of real
#                                       shoulder taps through as false flicks
# FLICK_SPACING_STDEV_THRESHOLD_MS = 5  # the feature that actually separates
#                                       flick from hard handling — magnitude
#                                       alone caps ~80% (setdown_firm is as
#                                       hard as a deliberate flick)
# POSITION_THRESHOLD_MG = 151         # only read if GESTURE_POSITION_ENABLED
# ORIENTATION_STABLE_MG = 700
# ORIENTATION_MAP = (("upright", "y", 1), ("horizontal", "z", -1), ("upside_down", "y", -1))
# GESTURE_MENU_OPTIONS = ("Item 1", "Item 2", "Item 3")  # placeholder content
# GESTURE_MODE_TIMEOUT_MS = 15_000

# ── LED status messages — docs/contracts/led-status-messages.md ────────
# Brief acknowledgments (as opposed to the terminal failures above).
# STATUS_LED_INDEX deliberately does NOT reuse ApproachContract's
# ANCHOR_INDEX — this stays contract-agnostic.
# STATUS_LED_INDEX = NUM_LEDS // 2
# QUIET_TAP_COLOR = (128, 0, 200)   # purple — tap during quiet hours
# QUIET_TAP_DURATION_MS = 2500
# NO_DATA_COLOR = (200, 160, 0)     # gold — woke up to nothing catchable
# NO_DATA_DURATION_MS = 2500

# ── Quiet hours (strip dark; wraps past midnight) ─────────────────
# ⚠ A dark strip during quiet hours is INDISTINGUISHABLE from a fault. Set
# 24 / 0 to disable while testing; the loop prints "(quiet hours — display
# off)" so the console can tell you apart from a real problem.
QUIET_START_HOUR = 24
QUIET_END_HOUR = 5
