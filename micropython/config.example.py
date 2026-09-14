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
#   Value           | Pico 2W | XIAO ESP32-C3 | XIAO RP2350 |
#   ----------------|---------|---------------|-------------|
#   LED_PIN         | 6       | 2             | 1  (= D7)   |
#   HEARTBEAT_PIN   | "LED"   | None          | see below   |
#   IMU_I2C_ID      | 0       | 0             | **1**       |
#   IMU_SDA_PIN     | 0       | 6             | 6  (= D4)   |
#   IMU_SCL_PIN     | 1       | 7             | 7  (= D5)   |
#
# ⚠ IMU_I2C_ID IS A PER-BOARD VALUE — it is not always 0. On RP2040/RP2350
# each I2C peripheral is hard-wired to a fixed pin table in silicon, so the
# XIAO RP2350's labeled D4/D5 (GP6/GP7) are on I2C**1**. An ID that
# disagrees with the pins is rejected AT CONSTRUCTION with a bare
# `ValueError: bad SCL pin` — before any bus activity, so no amount of
# rewiring helps. This has now cost four separate sessions. `make i2c-scan`
# finds the right combination and prints the values to paste.
#
# ⚠ HEARTBEAT_PIN on the XIAO RP2350: the "LED" alias DOES exist, unlike on
# the ESP32-C3 — but it is ACTIVE-LOW, so a heartbeat would run inverted
# (lit when it should be dark). Leave it None until main.py grows a
# polarity flag. The board also has an onboard NEOPIXEL (power-gated via
# NEOPIXEL_POWER) which is the better status indicator anyway —
# pinouts/xiao_rp2350.md.
#
# Physical wiring for each: pinouts/<board>.md — that directory is the
# source of truth for what's connected where; this file just mirrors it.

LED_PIN = 6  # GPIO driving the WS2812B data line.
#              ⚠ GETTING THIS WRONG IS A POWER FAULT, NOT A DISPLAY BUG.
#              An unaddressed WS2812B strip holds whatever state it powered
#              up in — potentially full white, ≈480mA for 8 LEDs — and
#              BRIGHTNESS cannot help, because it's a property of data you
#              aren't sending. On 2026-08-23 a wrong LED_PIN browned the
#              board out, corrupted the filesystem mid-write, and presented
#              as dead hardware for a morning. Check pinouts/<board>.md
#              BEFORE connecting a strip. See docs/insights.md §13.
NUM_LEDS = 8  # AE-WS2812B-STICK8 = 8; gift-jar strip = 21; 4020 tape = 120
HEARTBEAT_PIN = "LED"  # status LED. "LED" is a **Pico-2W-only** alias (routed
#                        through the CYW43 WiFi chip). On ANY other board it
#                        raises `ValueError: invalid pin` — set a GPIO number,
#                        or bare None (NOT the string "none"!) to disable.
#                        A quoted "none" is a truthy string main.py would try
#                        to use as a real pin name; tests/test_real_config.py
#                        catches that one before `make upload`.

# IMU (LSM6DSV16X) — only read if you've actually wired one.
IMU_I2C_ID = 0  # ⚠ PER-BOARD — see the table above. 0 is right for the
#                 Pico 2W and the ESP32-C3 (which maps I2C in software), but
#                 the XIAO RP2350 needs 1. Not a free choice on RP2 chips.
IMU_SDA_PIN = 0
IMU_SCL_PIN = 1

# ══ ② Time source + WiFi ═════════════════════════════════════════════
# TIME_SOURCE = "wifi" (default) connects and NTP-syncs at boot.
#
# ⚠ **On the XIAO ESP32-C3, use "rtc".** esp_wifi needs ~40KB of SRAM and
# ~26KB of that from one capability-constrained region that has only 32
# bytes of spare margin at a bare boot — an app this size does not fit
# alongside it, and you get `OSError: Wifi Out of Memory` or a native
# abort() during association. Fully measured in docs/insights.md §11.
# The Pico 2W has room and is fine on "wifi".
#
# "rtc" skips WiFi/NTP entirely and trusts the board's own clock — set it
# with `make set-time`. It survives a soft reset but NOT a power cycle, so
# re-run after unplugging. This is also where V2 is heading permanently
# (DS3231 RTC, no WiFi in normal operation).
# "ds3231" reads a DS3231 RTC over I2C every tick — the V2 direction, and
# the only source that survives a power cycle. It needs seeding once with
# `make rtc-test` (see that file's WORKFLOW), and it is TERMINAL on failure:
# an unreadable chip, a set oscillator-stop flag, or an implausible date all
# stop the display rather than showing departures from a clock we can't
# vouch for. Wrong times are worse than no times — they make you miss the
# train while believing you won't.
TIME_SOURCE = "wifi"  # "wifi" | "rtc" | "ds3231"

# DS3231 wiring — only read when TIME_SOURCE = "ds3231". Defaults to the
# IMU's bus, because on this project's hardware they ARE the same bus
# (0x68 vs 0x6A/0x6B, no address conflict). Uncomment only to split them.
# RTC_I2C_ID = 1
# RTC_SDA_PIN = 6
# RTC_SCL_PIN = 7

# Only read when TIME_SOURCE = "wifi".
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
#   ⚠ ARC CONTRACTS ONLY — inert under CONTRACT = "approach".
#   The two paradigms use colour for different jobs, and it's worth being
#   explicit about which:
#     · arc contracts (sandtimer/breathing*/echo/color) — colour means
#       URGENCY. A short strip can't express time positionally, so hue has
#       to carry it. This is the 8-LED-stick lineage and still correct there.
#     · approach — colour means LINE IDENTITY (from schedule.json's
#       lines[].color), and URGENCY is carried by POSITION: distance from
#       the anchor already is the time. Using hue for both would make a
#       line's colour non-constant, which breaks the whole point of being
#       identifiable on a random glance (gesture-envelope.md §11).
#   URGENCY_THRESHOLDS is likewise unused for approach RENDERING — it still
#   classifies the LEVEL shown in console output, nothing more.
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
# ⚠ THE FLOOR IS A PRODUCT OF THREE NUMBERS, so a safe MARKER_BRIGHTNESS
#   depends on BRIGHTNESS and stops being safe if you lower it:
#       MARKER_COLOR 80 × BRIGHTNESS × MARKER_BRIGHTNESS = raw value
#   At BRIGHTNESS 0.15, MARKER_BRIGHTNESS 0.15 gives raw 1 — exactly where
#   WS2812B channel matching collapses and "neutral" reads RED. The 0.25
#   default gives raw 3, the measured floor on the AE-WS2812B-STICK8.
#   ⚠ Any "= raw N" note next to MARKER_BRIGHTNESS is only true at the
#   BRIGHTNESS it was written for. At 0.50 the 0.25 default is raw 10; at
#   0.85 it is raw 17. Raising BRIGHTNESS moves markers AWAY from the
#   danger zone — it is the multipliers ABOVE 1.0 that get hurt (see the
#   anchor note below). Confirm per strip with `make low-pwm-test`.
#   docs/insights.md §12, and "How the brightness values compose" in
#   docs/contracts/config.md.
#
#   ⚠ ZERO IS NOT IN THE DANGER ZONE — it is OFF, and it is a legitimate
#   choice, not a workaround. The warning above is about the range
#   0 < x ≲ 0.15, where a channel is lit but too dim to be matched. An
#   unlit LED has no hue to get wrong.
#
#   **In a thick opaque bottle, off is often the right answer** (measured
#   over 24h, insights §18): the ticks diffuse into a yellow haze that
#   adds no information and competes with the two things that carry it,
#   the station and the train. Their job — "how far does the arc reach" —
#   is a question a clear vessel raises and an opaque one answers for you.
# MARKER_BRIGHTNESS = 0.25  # LINEAR mult of BRIGHTNESS (no gamma, no dither —
#                            avoids low-brightness flicker) for the idle
#                            "tick" LEDs. **0 = OFF** — see above.
#                            A train is never dimmer than BRIGHTNESS itself.
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

# ── Tap interaction — docs/contracts/gesture-envelope.md §11 ──────────
# Set GESTURE_ENABLED = True to make the unit respond to taps: tap wakes
# the display, tap again cycles the line, it sleeps after AWAKE_MINUTES.
# Needs a wired IMU. Off by default, which is right for an IMU-less unit —
# the display then behaves as it always has (always awake, no countdown).
#
# ⚠ Historical note: this gate used to be WAKE_INTERACTION_ENABLED, and
# turning it on was actively harmful — it fronted a loop whose tap
# detector was a stub returning False, so the display slept and could
# never wake. That stub is gone. The old name still works for
# compatibility, but prefer GESTURE_ENABLED.
# GESTURE_ENABLED = False
# AWAKE_MINUTES = 15           # how long it stays lit AFTER A TAP — a glance
# BOOT_AWAKE_MINUTES = 15      # how long it stays lit AT BOOT. Defaults to
#                                AWAKE_MINUTES. Different jobs: boot is a
#                                SELF-TEST window (you just plugged it in and
#                                want to see it work; nobody taps a unit they
#                                are still placing), a tap is someone asking
#                                when the next train is.
# ACK_HOLD_MS = 400            # ACK rise+dip before it settles to the shelf
# WAKE_JOLT_MS = 500           # CONFIRM jolt duration on WAKE
# WAKE_SETTLE_MS = 1500        # post-jolt debounce; stops the same physical
#                                contact registering again as a CYCLE
# CYCLE_TRANSITION_MS = 200    # CYCLE's simpler flash

# Tap-strength → brightness. A harder tap reads brighter on both the ACK
# peak and the shelf it settles onto. ⚠ All PER-ENCLOSURE: these were
# retuned three times as testing moved from a bare strip to inside frosted
# glass, which compresses contrast (gesture-envelope.md §11).
# STRENGTH_MAX_DEV_MG = 460    # `dev` of a deliberately hard tap
# ACK_PEAK_FLOOR = 0.35        # lightest-tap ACK peak
# ACK_PEAK_CEIL = 6.0          # hardest-tap ACK peak. ⚠ Bounded by
#                                SATURATION, not taste — once
#                                BRIGHTNESS * mult * channel hits 255,
#                                every harder tap looks identical. 10.0 did
#                                exactly that past ~65% strength.
# SHELF_FLOOR = 0.08           # the "continental shelf" — dim, NOT dark:
# SHELF_CEIL = 0.25            #   dropping to black made ACK and CONFIRM
#                                read as two disconnected blips
# GESTURE_POLL_MS = 4          # ⚠ must stay < FRAME_MS. Recognizer accuracy
#                                was measured at 4ms/240Hz; polling at 16ms
#                                was a documented cause of missed taps.

# ── Superseded: wake-interaction layer — wake-interaction.md ──────────
# Kept for reference. _cycle_brightness/_run_secondary_action still exist
# and are tested, but nothing binds them now that AWAKE+tap means CYCLE.
# WAKE_MINUTES = 30
# DOUBLE_TAP_WINDOW_MS = 400
# TAP_THRESHOLD = 2.0
# SECONDARY_ACTION = "brightness_cycle"
# BRIGHTNESS_PRESETS = (0.15, 0.35, 0.6)
# EXTEND_CONFIRM_COLOR = STARTUP_COLOR
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

# ── Memory instrumentation — docs/insights.md §11 ─────────────────
# Prints a checkpoint table at boot showing what each stage COST, e.g.:
#     after import           free  402112  alloc  118656
#     after time source      free  399984  alloc  120784   (-2128)
#     after schedule load    free  359776  alloc  160992   (-40208)
#     entering loop          free  357440  alloc  163328   (-2336)
# Deltas, not totals — "what did this step cost" is the answerable
# question. On ESP32 it also prints the ESP-IDF heap, which is a SEPARATE
# pool from the GC heap above and the one esp_wifi actually allocates
# from; confusing the two is what made the C3 investigation take days.
# ⚠ Samples after each step, so it shows RESIDENT cost, not transient
# peak — it would show the aftermath of a compile-time spike, not the
# spike. Off by default; costs one boolean test when off.
# MEM_DEBUG_ENABLED = False

# ── Onboard indicators (the MCU's own LEDs, NOT the strip) ────────
# Driven dark at boot by default. A jar with a stray LED glowing inside it
# is not ambient, it's a gadget — and these are invisible on a bench, so
# they're easy to forget until the thing is in glass.
# ONBOARD_LED_MODE = "off"        # "off" | "keep" (keep = for bring-up)
# ⚠ POLARITY IS PER-BOARD. XIAO RP2350's "LED" alias is ACTIVE-LOW —
# driving it HIGH extinguishes it. The Pico 2W's is active-high (and is
# its HEARTBEAT_PIN, so it's skipped there automatically).
# ONBOARD_LED_ACTIVE_LOW = True

# ── Quiet hours (strip dark; wraps past midnight) ─────────────────
# ⚠ A dark strip during quiet hours is INDISTINGUISHABLE from a fault. Set
# 24 / 0 to disable while testing; the loop prints "(quiet hours — display
# off)" so the console can tell you apart from a real problem.
QUIET_START_HOUR = 24
QUIET_END_HOUR = 5

# ── Day/night brightness (a different question from quiet hours) ───
#   quiet hours  → MAY the display light up at all?
#   day/night    → HOW BRIGHT when it does?
#
# Measured, not guessed: 24 h with the v1.6 unit found daylight too dim and
# night fine (insights.md §14) — the exact reverse of the finding ten weeks
# earlier through different glass (§5). One BRIGHTNESS cannot be right at
# both ends of a day, and raising it to fix noon produces glare at night
# that destroys the diffusion the whole look depends on.
#
# Both default to BRIGHTNESS, so leaving this block alone changes NOTHING.
# Raising DAY_BRIGHTNESS is the point. Tune it on the actual glass at the
# actual time of day — ~2x BRIGHTNESS is a starting guess, not a value.
DAY_NIGHT_ENABLED = True
DAY_START_HOUR = 7      # inclusive
DAY_END_HOUR = 17       # exclusive. Equal start/end = always night;
                        #   0/24 = always day.
# DAY_BRIGHTNESS = 0.30
# NIGHT_BRIGHTNESS = 0.15
#
# ── Goodnight, and the morning flower ──────────────────────────────
# For the hours when trains exist but none is near enough to display. A
# lit anchor is a promise — rendering it with nothing on the arms reads as
# a broken jar. insights.md §17.
#
# GOODNIGHT: a tap that resolves to "nothing within reach" gets a slow
# `outward` — energy leaving the station — and then the strip goes dark
# instead of sitting lit. Distinct from the no-data acknowledgment,
# because "come back tomorrow" and "you missed the last train" are
# different facts.
# When AWAKE_MINUTES expires, unwind instead of cutting to black — which
# is indistinguishable from a power loss. ONE wave, not three: you stopped
# looking, which is a smaller fact than the day ending.
SLEEP_UNWIND_ENABLED = True
# SLEEP_UNWIND_MS = 2200
# SLEEP_UNWIND_COLOR = (150, 70, 20)

GOODNIGHT_ENABLED = True
# Three waves, because one is a gesture and three are a ceremony. The
# sequence is a SUNSET — slower, dimmer and cooler each time — and its
# mirror, MORNING_WAVES, is a sunrise. Each entry is (color, ms, peak).
# ⚠ The colour drift is the part an amber vessel will NOT show (§12: it is
# a blue-cut filter), so duration and decay carry the meaning on their own:
# a clear bottle gets a sunset, a brown one gets a fade, and neither
# depends on the other.
# GOODNIGHT_WAVES = (((200, 90, 0), 1400, 1.00),
#                    ((140, 60, 60), 2100, 0.70),
#                    ((40, 40, 150), 3200, 0.45))
#
# MORNING: wake just before the first train crosses into view, so the arc
# is seen opening from its outer edge inward. ⚠ The flower is not an
# animation — it is the ordinary renderer, watched at a moment the display
# is normally asleep for. Costs one extra awake window per day, which is
# not free on a battery build (taps/day is the power budget's largest
# lever).
MORNING_WAKE_ENABLED = True
# MORNING_LEAD_MINUTES = 1         # wake this long before the crossing
# MORNING_WAVES = (((60, 30, 90), 2400, 0.35),     # pre-dawn, barely there
#                  ((220, 110, 10), 1700, 0.70),   # warming
#                  ((255, 200, 0), 1200, 1.00))    # daylight yellow

# ── The light language: motion instead of flashes ──────────────────
# With this on, a tap's CONFIRM stops being a flash and becomes a word:
#   wake from asleep        → `outward` from the anchor, ∝ strike force
#   cycle to another line   → `around`, in the NEW line's colour
#   cycle, but only 1 line  → `shake` — motion that fails to complete
# The ACK stays a flash: it is the tactile "click" of the button and has
# to fire before anything is classified. docs/contracts/light-language.md
MOTION_ENABLED = True
#
# The shake's WIDTH is fixed by the vocabulary and you should not need to
# touch it: ±5 LEDs reads as a short lap of `around` and the two words
# stop being distinguishable; ±3 is a clean head-shake. Its CENTRE is the
# per-unit part — put it at the LABEL EDGE so the "no" bounces against the
# one boundary the vessel has. A bottle with no label needs neither.
# SHAKE_CENTER = 10        # defaults to the middle of the strip
# SHAKE_HALF_WIDTH = 3     # vocabulary constant — measured, not taste
# SHAKE_BOUNDS = (7, 13)   # overrides both, for an asymmetric bounce

# ── Tilt to adjust brightness ──────────────────────────────────────
# Tilt the bottle: the first lean past the deadzone defines the axis AND
# means "up"; leaning back the other way means "down". Return to upright
# and it holds. Set the bottle down and wherever it rests becomes the new
# neutral. No calibration, and it works however the IMU ended up mounted.
#
# ⚠ RAM ONLY. A tilt-set brightness does not survive a power cycle, and
# the day/night profile above reclaims it at the next 07:00/17:00 boundary
# — deliberately, that is the same contract an OS's automatic dark mode
# has: it switches you, you may override, the next switch wins.
#
# Every other TILT_* constant in settings.py is a hardware finding rather
# than a preference (insights.md §15) — read that before changing one.
TILT_ENABLED = True
# TILT_EXPO = 0.6            # 0 = linear, 1 = pure cubic. Fine control near
#                            #   upright, full rate at full tilt.
# TILT_RATE_PER_SEC = 0.20   # brightness units per second at full tilt
# TILT_FIRST_MEANS = "up"    # "down" if go-up-first ever glares in the dark

# Seasonal drift (a window that breathes with the calendar) is NOT here:
# it needs day-of-year, which local_time() currently discards. Separate,
# larger step — insights.md §14.
