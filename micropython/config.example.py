# micropython/config.example.py
# Committed template — copy to config.py and fill in real values.
# config.py is gitignored and never committed. You can also edit config.py
# directly on the board via Thonny (it already lives on the Pico).
#
# Only WIFI_SSID / WIFI_PASS are required. Every other field below is OPTIONAL:
# main.py reads it with a built-in default, so you can delete any line you don't
# want to change (and older config.py files keep working unchanged).
# See docs/contracts/config.md for full field documentation.

# ── WiFi (V1 only — removed in V2 when DS3231 replaces NTP) ──────

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
#                          ARM_B_LEN > 0 in config.py's approach-contract block.
WALK_TO_STATION_MINS = 2.5  # room→platform; trains you can't catch are hidden

# ── Display: hardware ─────────────────────────────────────────────
# Board-specific — see pinouts/<board>.md for the physical wiring these refer to.
LED_PIN = 6  # GP pin driving the WS2812B data line
NUM_LEDS = 8  # AE-WS2812B-STICK8 = 8; the V1.5 ring will be 12
ARC_ORIGIN = "far"  # which end the arc grows from: "near" = DIN end (index 0),
#                      "far" = the other end. Flip if the strip mounts upside-down.
HEARTBEAT_PIN = "LED"  # status LED. "LED" is a Pico-2W-only alias — on boards
#                        with no such alias (e.g. XIAO ESP32-C3) set a GPIO
#                        number, or bare None (NOT the string "none"!) to
#                        disable the heartbeat entirely. A quoted "none" is a
#                        truthy string that main.py will try to use as a real
#                        pin name and fail — tests/test_real_config.py catches
#                        this before `make upload`, but save yourself the trip.

# ── Display: look & feel ──────────────────────────────────────────
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
# LINE_FADE_FLOOR = 0.3    # dim end of the train's OWN crossfade — independent
#                            of MARKER_BRIGHTNESS (see approach-contract.md)
# MARKER_BRIGHTNESS = 0.15  # LINEAR mult of BRIGHTNESS (no gamma, no dither —
#                            avoids low-brightness flicker) for the idle
#                            "tick" LEDs — 0 = fully off. NOT read by the
#                            train's crossfade.
# MARKER_COLOR = (80, 80, 80)     # idle tick-LED colour, NOT a dimmed LINE_COLOR
# TRANSITION_MS = 4000     # crossfade duration between position updates, ms

# ── Quiet hours (strip dark; wraps past midnight) ─────────────────
QUIET_START_HOUR = 24
QUIET_END_HOUR = 5
