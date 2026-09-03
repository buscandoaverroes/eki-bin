# micropython/settings.py — eki-bin
# Every value main.py reads out of config.py, with its default, in one
# place. Extracted verbatim from main.py during the V1.6 split
# (docs/v1.6-refactor.md) — the code below was MOVED, not rewritten.
#
# Everything else imports from here, so this module must depend on nothing
# but `config` itself. Keep it that way: the moment settings.py imports a
# sibling, the extraction order in the runbook stops working.
#
# ⚠ TRANSITIONAL: main.py currently does `from settings import *` so the
# 265 host tests, which reach into `main.X`, keep passing unchanged while
# the rest of the split happens. That re-export is deliberate and temporary
# — see the runbook's "one rule that keeps this safe". Tightening it is the
# LAST step of V1.6, not an improvement to make early.
#
# Note `import *` does not export underscore-prefixed names, so
# _UTC_OFFSET_APPLIED is imported explicitly by main.py.

import config

# ─────────────────────────────────────────────────────────────
# Settings (from config.py)
# ─────────────────────────────────────────────────────────────
# WiFi creds are required only when TIME_SOURCE = "wifi" (the default), so
# they can't be a hard `config.WIFI_SSID` any more — a deliberately
# WiFi-free unit (TIME_SOURCE="rtc", the only way to run on the XIAO
# ESP32-C3; see docs/insights.md §11) has no reason to carry credentials,
# and a bare attribute read would AttributeError at import before main()
# could explain why. Default to None and let connect_wifi() do the
# complaining, where there's an LED path to complain THROUGH.
WIFI_SSID = getattr(config, "WIFI_SSID", None)
WIFI_PASS = getattr(config, "WIFI_PASS", None)

# Everything else is optional with a default. getattr(config, "NAME", default)
# returns the default when the field is absent, so a config.py written before a
# knob existed keeps working — you only add the lines you want to override.
UTC_OFFSET_HOURS = getattr(config, "UTC_OFFSET_HOURS", 9)
LOOP_INTERVAL_SECS = getattr(config, "LOOP_INTERVAL_SECS", 30)
SCHEDULE_FILE = getattr(config, "SCHEDULE_FILE", "schedule.json")

# Which trains
DISPLAY_DIRECTION = getattr(config, "DISPLAY_DIRECTION", "b")
DISPLAY_DIRECTION_B = getattr(config, "DISPLAY_DIRECTION_B", None)  # phase 2 —
#   bidirectional ApproachContract only. Set to a SECOND schedule.json
#   direction key (DISPLAY_DIRECTION feeds arm "a", this feeds arm "b") to show
#   one train per arm. None (default) = single-direction, phase 1 unchanged.
#   Ignored entirely by every other contract (see render_for_interval()).
WALK_TO_STATION_MINS = getattr(config, "WALK_TO_STATION_MINS", 2.5)
# [→ NFC] WALK could later be read from the station card, not config.

# Display — hardware (changes with the physical strip: stick=8, ring=12)
LED_PIN = getattr(config, "LED_PIN", 6)
NUM_LEDS = getattr(config, "NUM_LEDS", 8)
ARC_ORIGIN = getattr(config, "ARC_ORIGIN", "near")  # "near" = DIN end (index 0) is
#   the arc origin; "far" = the other end. Logical, not physical — flip this when
#   the strip ends up mounted upside-down, without touching any rendering code.

# Display — look & feel
BRIGHTNESS = getattr(config, "BRIGHTNESS", 0.15)
CONTRACT_NAME = getattr(config, "CONTRACT", "sandtimer")
COLOR_SCHEME = getattr(config, "COLOR_SCHEME", "default")
MINUTES_PER_LED = getattr(config, "MINUTES_PER_LED", 1)
URGENCY_THRESHOLDS = getattr(config, "URGENCY_THRESHOLDS", (2, 5))
GAMMA = getattr(config, "GAMMA", 2.2)  # perceptual brightness curve (see gamma())
BREATHE_PERIOD_MS = getattr(config, "BREATHE_PERIOD_MS", 8000)  # one breath, ms
BREATHE_FLOOR = getattr(config, "BREATHE_FLOOR", 0.2)  # dim end of the breath (0..1)
DITHER = getattr(config, "DITHER", True)  # temporal dithering for smooth dim fades
FRAME_MS = getattr(config, "FRAME_MS", 16)  # frame duration, ms
N_TRAINS = getattr(config, "N_TRAINS", 1)  # how many upcoming departures to show
#   as nested arcs (1 = just the primary — the original behaviour). >1 shows
#   further-out trains as a dimmer band beyond the primary's arc.
BACKGROUND_BRIGHTNESS = getattr(config, "BACKGROUND_BRIGHTNESS", 0.35)  # 0..1;
#   relative brightness of the 2nd train; the 3rd gets this squared, etc.
#   (geometric falloff — one knob regardless of how many trains you show).
#   Used by SandTimerContract/BreathingContract's uniform per-layer dimming.

# EchoContract only (see docs/insights.md §6 for why brightness-only dimming
# didn't work): trains beyond the primary differentiate by HUE + a brightness
# that stays high the whole time — no low-brightness dip to flicker/lose
# diffusion. Tuned empirically via led_sandbox.py.
SECONDARY_HUE_SHIFT_DEG = getattr(config, "SECONDARY_HUE_SHIFT_DEG", 20)  # per
#   train index beyond the primary (2nd = ×1, 3rd = ×2, ...)
SECONDARY_BREATHE_PERIOD_MS = getattr(config, "SECONDARY_BREATHE_PERIOD_MS", 3000)
SECONDARY_BREATHE_FLOOR = getattr(config, "SECONDARY_BREATHE_FLOOR", 0.7)  # high —
#   this is a subtle differentiation pulse, not the urgency-signalling breath
#   BreathingContract's own BREATHE_FLOOR drives; deliberately separate knobs
#   so tuning one doesn't fight the other.

# ApproachContract only — positional paradigm, see docs/contracts/approach-contract.md.
# ANCHOR_INDEX/ARM_*_LEN are one arm-generic mechanism: phase 1 (this build) sets
# ARM_B_LEN=0 for a single direction; phase 2 (bidirectional) is the same code
# path with different config, not a second contract.
ANCHOR_INDEX = getattr(config, "ANCHOR_INDEX", 0)
ARM_A_LEN = getattr(config, "ARM_A_LEN", NUM_LEDS - 1)
ARM_B_LEN = getattr(config, "ARM_B_LEN", 0)
ANCHOR_COLOR = getattr(config, "ANCHOR_COLOR", (255, 200, 120))  # warm white/amber —
#   distinct from both LINE_COLOR and MARKER_COLOR so the anchor never
#   reads as "a very close train" or "an empty tick".
ANCHOR_BRIGHTNESS = getattr(config, "ANCHOR_BRIGHTNESS", 1.6)  # relative to a normal
#   "full" position (mult=1.0) — >1.0 makes the anchor genuinely brighter than
#   the BRIGHTNESS ceiling everything else tops out at, not just relying on
#   colour alone to read as "the fixed one". Rendered via the STATIC path (see
#   _write_frame), so this scales BRIGHTNESS LINEARLY — no gamma reshaping.
POSITION_MINUTES_PER_LED = getattr(config, "POSITION_MINUTES_PER_LED", 1)
# The train's own colour is fixed, NOT urgency-banded like PALETTE: in this
# paradigm distance-to-anchor already encodes urgency continuously, so colour
# is freed up to mean "this line" instead of re-encoding the same signal a
# second way (same reasoning MARKER_COLOR-not-dimmed already uses below).
LINE_COLOR = getattr(config, "LINE_COLOR", (34, 139, 34))  # forest green
LINE_SATURATION = getattr(config, "LINE_SATURATION", 1.0)  # 1.0=unchanged;
#   lower = a genuinely MUTED (desaturated) LINE_COLOR, not just a dimmer one
#   — see desaturate()'s docstring for why those are different transforms.
#   Applied once at class-definition time (ApproachContract.line_color).
# Where the train currently is renders at BRIGHTNESS directly (mult=1.0,
# STATIC path, always — see the CHASE transition below, which never dims a
# train at all). Two independent brightness surfaces total:
# ANCHOR_BRIGHTNESS (the "0") and MARKER_BRIGHTNESS (the idle ticks, below) —
# BRIGHTNESS itself is the train's, with no separate scalar on top.
# Default RAISED from 0.15 to 0.25 on 2026-08-24. The old value put markers
# at raw 1 per channel — MARKER_COLOR 80 x BRIGHTNESS 0.15 x 0.15 — which is
# exactly where WS2812B channel matching collapses and neutral reads RED.
# Measured floor on this strip is 3; 0.25 lands on it. docs/insights.md §12.
# ⚠ The floor is per-strip, and this is a magic number tied to MARKER_COLOR
# and BRIGHTNESS: change either and markers can silently fall back into the
# collapse zone. A clamp on the final value is the durable fix (§12).
MARKER_BRIGHTNESS = getattr(config, "MARKER_BRIGHTNESS", 0.25)  # LINEAR multiplier
#   of BRIGHTNESS for the idle "tick" LEDs — every position that ISN'T the
#   anchor or the train right now (the gaps on the thermometer). Rendered via
#   the STATIC path (see _write_frame) — direct linear, no gamma. Needs to
#   clear ~1 output code per MARKER_COLOR channel or it truncates invisibly
#   to black. 0 = idle LEDs fully off.
MARKER_COLOR = getattr(config, "MARKER_COLOR", (80, 80, 80))  # dim neutral — NOT a
#   dimmed LINE_COLOR (see docs/contracts/approach-contract.md § Marker ticks)
TRANSITION_MS = getattr(config, "TRANSITION_MS", 4000)  # crossfade duration; 0 = instant

# Boot ceremony — see docs/contracts/startup-sequence.md. Runs once at power-on,
# before the main loop starts; never recurs during normal operation.
STARTUP_COLOR = getattr(config, "STARTUP_COLOR", (255, 255, 255))  # loading-
#   circle + success-burst colour. All LEDs together, contract-agnostic — the
#   startup sequence runs before any CONTRACT is "current".
STARTUP_SPIN_HZ = getattr(config, "STARTUP_SPIN_HZ", 0.4)  # loading-circle
#   revolutions/sec while connecting (WiFi + NTP)
STARTUP_BURST_MS = getattr(config, "STARTUP_BURST_MS", 800)  # success burst:
#   rise duration, ms
STARTUP_FADE_MS = getattr(config, "STARTUP_FADE_MS", 1500)  # success burst:
#   decay duration, ms, after which the main loop takes over
ERROR_COLOR = getattr(config, "ERROR_COLOR", (255, 0, 0))  # persistent
#   failure state — see run_startup_sequence(). All LEDs, forever, until reset.
ERROR_BREATHE_PERIOD_MS = getattr(config, "ERROR_BREATHE_PERIOD_MS", 4000)  #
#   deliberately separate from BREATHE_PERIOD_MS — retuning a contract's
#   breathing feel should never touch the failure state's.

# Tap interaction — docs/contracts/gesture-envelope.md §11. OFF by default:
# the display behaves exactly as before (always "awake", no countdown),
# which is right for any unit with no IMU wired.
#
# **Turning this on is now SAFE and actually does something.** It used to be
# neither: the gate fronted a loop whose tap detector was a stub returning
# False, so enabling it slept the display after the timeout with no way to
# wake it. That stub is gone (see the note above _StatusMessage) and this
# now drives the real recognizer.
#
# Accepts GESTURE_ENABLED (preferred) or the older
# WAKE_INTERACTION_ENABLED, so existing config.py files keep working —
# design principle #9. The old name is kept only for compatibility; it
# describes a design that has been superseded.
WAKE_INTERACTION_ENABLED = getattr(
    config, "GESTURE_ENABLED", getattr(config, "WAKE_INTERACTION_ENABLED", False)
)
WAKE_MINUTES = getattr(config, "WAKE_MINUTES", 30)  # active-display window
#   after any wake/extend trigger
DOUBLE_TAP_WINDOW_MS = getattr(config, "DOUBLE_TAP_WINDOW_MS", 400)  # max gap
#   between two taps to count as a double-tap — GUESS, tune against real
#   sensor data once the IMU is wired
TAP_THRESHOLD = getattr(config, "TAP_THRESHOLD", 2.0)  # accelerometer
#   magnitude delta for "a tap happened" — UNTESTED GUESS, no IMU wired yet;
#   _imu_tap_detected() doesn't even use this yet (still stubbed), kept here
#   so the real implementation has an obvious knob to read
SECONDARY_ACTION = getattr(config, "SECONDARY_ACTION", "brightness_cycle")  #
#   pluggable — what a single tap while AWAKE does (see _run_secondary_action)
BRIGHTNESS_PRESETS = getattr(config, "BRIGHTNESS_PRESETS", (0.15, 0.35, 0.6))
EXTEND_CONFIRM_COLOR = getattr(config, "EXTEND_CONFIRM_COLOR", STARTUP_COLOR)
EXTEND_CONFIRM_MS = getattr(config, "EXTEND_CONFIRM_MS", 600)

# LED status messages — docs/contracts/led-status-messages.md. Shared
# "middle-ish" position for brief single-LED acknowledgments, deliberately
# NOT ApproachContract's ANCHOR_INDEX (which defaults to 0, not the middle,
# under every other CONTRACT) — this vocabulary works the same regardless of
# which CONTRACT is active.
STATUS_LED_INDEX = getattr(config, "STATUS_LED_INDEX", NUM_LEDS // 2)
QUIET_TAP_COLOR = getattr(config, "QUIET_TAP_COLOR", (128, 0, 200))  # purple
QUIET_TAP_DURATION_MS = getattr(config, "QUIET_TAP_DURATION_MS", 2500)
NO_DATA_COLOR = getattr(config, "NO_DATA_COLOR", (200, 160, 0))  # gold/amber
NO_DATA_DURATION_MS = getattr(config, "NO_DATA_DURATION_MS", 2500)
SCHEDULE_ERROR_COLOR = getattr(config, "SCHEDULE_ERROR_COLOR", (200, 0, 120))
#   distinct from ERROR_COLOR (red, WiFi/NTP failure) — a different failure
#   cause should look like a different failure, not the same red for anything
TIME_SOURCE = getattr(config, "TIME_SOURCE", "wifi")
#   "wifi" — connect + NTP at boot (V1 default, needs ~40KB of SRAM for
#            esp_wifi; fine on the Pico 2W, does NOT fit on the XIAO
#            ESP32-C3 alongside an app this size — docs/insights.md §11)
#   "rtc"  — skip WiFi/NTP; trust the board's own RTC, set at provisioning
#            time (`make set-time`). Survives soft reset, not power loss.
#            The direction V2 goes permanently, via a DS3231.

# NTP writes UTC to the RTC; `mpremote rtc --set` writes the HOST'S LOCAL
# time. So UTC_OFFSET_HOURS must only be applied in the "wifi" case —
# adding it to an already-local clock puts the display UTC_OFFSET_HOURS
# ahead, which is exactly what happened on the first real "rtc" boot.
# Derived here rather than making the user also remember to zero
# UTC_OFFSET_HOURS: two knobs that must agree is a footgun, one that
# follows from the other isn't.
_UTC_OFFSET_APPLIED = 0 if TIME_SOURCE in ("rtc", "ds3231") else UTC_OFFSET_HOURS
CONFIG_ERROR_COLOR = getattr(config, "CONFIG_ERROR_COLOR", (255, 140, 0))
#   orange — a BAD CONFIG VALUE (e.g. HEARTBEAT_PIN="LED" on a board with no
#   such alias, which raises ValueError: invalid pin). Previously this class
#   of failure crashed before any LED code ran, so a misconfigured unit on a
#   wall adapter looked identical to a dead one — no serial console, no
#   indication, nothing. That's the worst possible failure mode for a device
#   meant to be handed to someone else. Same persistent-breathe treatment as
#   the other two, its own colour per led-status-messages.md.

# Gesture envelope — docs/contracts/gesture-envelope.md. Evidence-based,
# from real sandbox data (docs/insights.md §8-9), unlike WAKE_INTERACTION's
# TAP_THRESHOLD/DOUBLE_TAP_WINDOW_MS above (both flagged guesses when
# written, no IMU in hand yet). Every GESTURE_*_ENABLED flag is a hardware
# capability, off by default until something concrete backs it up — same
# safety-gate precedent WAKE_INTERACTION_ENABLED already set.
IMU_I2C_ID = getattr(config, "IMU_I2C_ID", 0)
IMU_SDA_PIN = getattr(config, "IMU_SDA_PIN", 0)  # Pico 2W default — see
IMU_SCL_PIN = getattr(config, "IMU_SCL_PIN", 1)  #   pinouts/pico2w.md

# DS3231 RTC. Defaults to the IMU's bus because on this hardware they ARE
# the same physical bus — 0x68 and 0x6A/0x6B, no address conflict
# (docs/hardware.md § DS3231). Overridable for a board that wires them apart.
RTC_I2C_ID = getattr(config, "RTC_I2C_ID", IMU_I2C_ID)
RTC_SDA_PIN = getattr(config, "RTC_SDA_PIN", IMU_SDA_PIN)
RTC_SCL_PIN = getattr(config, "RTC_SCL_PIN", IMU_SCL_PIN)
# Cyan, deliberately far from ERROR_COLOR (red), SCHEDULE_ERROR_COLOR
# (magenta) and CONFIG_ERROR_COLOR (orange) — those three are all one hue
# family, and docs/insights.md §12 found that through brown glass only
# near-opposite hues stay distinguishable. A clock fault must be tellable
# apart from a WiFi fault by someone holding a jar with no laptop.
CLOCK_ERROR_COLOR = getattr(config, "CLOCK_ERROR_COLOR", (0, 160, 200))

if TIME_SOURCE not in ("wifi", "rtc", "ds3231"):
    # Fail loudly at import. A typo previously fell through to the WiFi
    # path, which on a radio-less board is an unrecoverable hang.
    raise ValueError(
        "TIME_SOURCE=%r is not one of 'wifi', 'rtc', 'ds3231'" % (TIME_SOURCE,)
    )

GESTURE_FLIP_ENABLED = getattr(config, "GESTURE_FLIP_ENABLED", False)  #
#   requires wired (USB) power — flipping a Qi-mounted jar breaks inductive
#   coupling, see gesture-envelope.md §5
GESTURE_POSITION_ENABLED = getattr(config, "GESTURE_POSITION_ENABLED", False)  #
#   shoulder-vs-base disaggregation — ~78-81% even on a bottle it's tuned
#   for (insights.md §8-9); off by default, opt-in per physical unit
GESTURE_FLICK_ENABLED = getattr(config, "GESTURE_FLICK_ENABLED", True)  #
#   best-validated signal after tap presence — on by default

# Per-bottle calibrated thresholds — chianti-bottle values derived from the
# sandbox tooling's pooled data (insights.md §8-9), NOT guesses, but also
# NOT universal: amplitude features don't transfer across bottles (§9's
# cross-bottle test: 0% for position). Re-derive per physical unit via
# vibration_sandbox.py + scripts/analyze_taps.py before flashing a
# different bottle.
TAP_TRIGGER_THRESHOLD_MG = getattr(config, "TAP_TRIGGER_THRESHOLD_MG", 50)  #
#   cheap first-pass gate only — deliberately permissive (real handling
#   motion overlaps this range too, see insights.md §9's handling_test.py
#   findings), the real discrimination happens in the recognizer layer
#   below, not at this trigger
FLICK_MAGNITUDE_THRESHOLD_MG = getattr(config, "FLICK_MAGNITUDE_THRESHOLD_MG", 328)  #
#   RECALIBRATED against shoulder+base taps (95.2% separability) — the
#   original 140 was calibrated against BODY taps only (median 50mg), which
#   badly undershoots shoulder's own normal tap force (median 215mg) — real
#   hardware testing found 79% of ordinary shoulder taps already exceeded
#   140mg on their own. See gesture-envelope.md §10.
FLICK_SPACING_STDEV_THRESHOLD_MS = getattr(config, "FLICK_SPACING_STDEV_THRESHOLD_MS", 5)
#   flick vs. hard handling when spacing IS computable — magnitude alone
#   caps ~80% (setdown_firm is just as hard as a deliberate flick); this
#   shape feature helps when available, see insights.md §9. NOT available
#   most of the time in practice (needs >=3 crossings; ~70% of real flicks
#   and ~25% of hard handling events don't have that many) — see
#   classify_tap_or_flick's own docstring for how the missing case is
#   handled, and gesture-envelope.md §10 for why a classifier doesn't do
#   any better here (~80% ceiling either way).
POSITION_THRESHOLD_MG = getattr(config, "POSITION_THRESHOLD_MG", 151)  #
#   only read if GESTURE_POSITION_ENABLED
ORIENTATION_STABLE_MG = getattr(config, "ORIENTATION_STABLE_MG", 700)  #
#   below this, treat orientation as "mid-motion", not a resting state —
#   matches orientation_test.py's proven STABLE_READING_MG
ORIENTATION_MAP = getattr(config, "ORIENTATION_MAP", (
    # (state name, dominant axis, sign) — chianti-bottle mounting, from
    # orientation_test.py's real readings (insights.md §9): Y+ ≈ 965mg
    # upright, Z- ≈ 950mg horizontal, Y- ≈ 870mg upside-down. Per-bottle:
    # the IMU's mounting orientation on the glass determines this mapping,
    # not the gesture logic — re-derive with orientation_test.py per unit.
    ("upright", "y", 1),
    ("horizontal", "z", -1),
    ("upside_down", "y", -1),
))

# Scrollwheel / menu — gesture-envelope.md §7. Sketch, not a spec: the real
# option list is a product decision, not a hardware one (§9) — validating
# the mechanism doesn't need real content, same as wake-interaction.md
# shipped its state machine before settling SECONDARY_ACTION's content.
GESTURE_MENU_OPTIONS = getattr(config, "GESTURE_MENU_OPTIONS", ("Item 1", "Item 2", "Item 3"))
GESTURE_MODE_TIMEOUT_MS = getattr(config, "GESTURE_MODE_TIMEOUT_MS", 15_000)  #
#   bounded return to ambient — same "must not be a state you can get stuck
#   in" philosophy WAKE_MINUTES already established

# Terminal-only validation loop — deliberately its OWN flag, not
# WAKE_INTERACTION_ENABLED: this exercises a different, newer subsystem and
# should stay fully isolated from the existing tested loop. OFF by default,
# same safety-gate precedent as everything else opt-in here.
GESTURE_DEBUG_ENABLED = getattr(config, "GESTURE_DEBUG_ENABLED", False)

# V1 minimal gesture contract — gesture-envelope.md §11. A deliberate
# SPECIALIZATION of the recognizer/scrollwheel above (tap-vs-noise only,
# GESTURE_POSITION_ENABLED/GESTURE_FLICK_ENABLED stay False), not a
# replacement — see that section for why. TAP_ENERGY_THRESHOLD is the one
# threshold this path needs; the timing knobs below drive the two-phase
# ACK/CONFIRM state machine (_TapCycleState).
TAP_ENERGY_THRESHOLD = getattr(config, "TAP_ENERGY_THRESHOLD", 138000)  #
#   per-bottle — 98.4% across pooled tap vs. pooled handling-noise sessions
#   (chianti bottle), see §11
ACK_FLASH_MS = getattr(config, "ACK_FLASH_MS", 50)  # instant acknowledgment
#   on trigger, before the verdict is known — as close to 0 as FRAME_MS/
#   hardware allow
WAKE_JOLT_MS = getattr(config, "WAKE_JOLT_MS", 500)  # confirmed-wake jolt
#   duration, no input accepted — flagged too slow as-is (§11), timing is
#   a feel question to iterate visually, not a logic one
WAKE_JOLT_BRIGHTNESS_MULT = getattr(config, "WAKE_JOLT_BRIGHTNESS_MULT", 2.0)

# Tap-strength → brightness, "hardware-defined software": a harder tap reads
# brighter on both the ACK peak (the "up") and the shelf it settles onto (the
# "down"). Every one of these defaults was tuned on real hardware across five
# rounds — bare strip first, then IN-BOTTLE, which needed a wider range
# because frosted glass compresses contrast. Full history:
# gesture-envelope.md §11. Per-enclosure, like every amplitude number here.
STRENGTH_MIN_DEV_MG = getattr(config, "STRENGTH_MIN_DEV_MG", TAP_TRIGGER_THRESHOLD_MG)
STRENGTH_MAX_DEV_MG = getattr(config, "STRENGTH_MAX_DEV_MG", 460)
ACK_PEAK_FLOOR = getattr(config, "ACK_PEAK_FLOOR", 0.35)  # lightest-tap ACK peak
ACK_PEAK_CEIL = getattr(config, "ACK_PEAK_CEIL", 6.0)  # hardest-tap ACK peak.
#   ⚠ Bounded by SATURATION, not taste: once BRIGHTNESS * mult * channel
#   hits 255 every harder tap renders identically. 10.0 did exactly that
#   past ~65% strength. tests/test_gesture_sandbox.py guards this.
SHELF_FLOOR = getattr(config, "SHELF_FLOOR", 0.08)  # dim, deliberately not dark
SHELF_CEIL = getattr(config, "SHELF_CEIL", 0.25)  # stays under ACK_PEAK_FLOOR
ACK_HOLD_MS = getattr(config, "ACK_HOLD_MS", 400)  # rise+dip duration. 150ms
#   was too brief to perceive a strength difference before it settled.
WAKE_SETTLE_MS = getattr(config, "WAKE_SETTLE_MS", 1500)  # post-jolt
#   debounce, no input accepted — prevents the same physical contact that
#   triggered WAKE from also registering as an immediate CYCLE
AWAKE_MINUTES = getattr(config, "AWAKE_MINUTES", 15)  # bounded-window,
#   same philosophy as WAKE_MINUTES — no EXTEND gesture, no runtime
#   adjustment, deliberately simpler than the old wake-interaction design
CYCLE_TRANSITION_MS = getattr(config, "CYCLE_TRANSITION_MS", 200)  # flash,
#   then a hard cut to the next station — no crossfade, see §11

# Status heartbeat LED — board-specific, unlike the WS2812B data line above.
# "LED" is a Pico-2W-only alias (routed through the CYW43 WiFi chip, not a plain
# GPIO). Other boards have no such alias: set this to a GPIO number for that
# board's onboard LED (see pinouts/<board>.md), or None to disable the heartbeat
# entirely — the console heartbeat (●/○) still prints either way.
HEARTBEAT_PIN = getattr(config, "HEARTBEAT_PIN", "LED")

# Quiet hours (strip dark). Stored as hours in config; minutes internally.
QUIET_START = getattr(config, "QUIET_START_HOUR", 23) * 60
QUIET_END = getattr(config, "QUIET_END_HOUR", 6) * 60

# ── Onboard indicators (the MCU's own LEDs, not the strip) ───────────
# "off"  — driven dark at boot. Right for a finished object: a jar with a
#          stray LED glowing inside it is not ambient, it is a gadget.
# "keep" — don't touch them. For bring-up, or a future "debug" mode where
#          they carry state (the XIAO RP2350's NEOPIXEL is a full-colour
#          indicator that needs no external strip — pinouts/xiao_rp2350.md,
#          and led-status-messages.md describes what it could say).
ONBOARD_LED_MODE = getattr(config, "ONBOARD_LED_MODE", "off")
# ⚠ POLARITY IS PER-BOARD. The XIAO RP2350's "LED" alias is ACTIVE-LOW
# (verified at the REPL 2026-08-23): driving it HIGH extinguishes it. The
# Pico 2W's is active-high and routed through the CYW43. Getting this
# backwards turns the LED ON while trying to turn it off.
ONBOARD_LED_ACTIVE_LOW = getattr(config, "ONBOARD_LED_ACTIVE_LOW", True)

# Relocated here by the V1.6 split: it is a config read, and this
# module owns those. diag.py imports it.
MEM_DEBUG_ENABLED = getattr(config, "MEM_DEBUG_ENABLED", False)

# Relocated by the V1.6 tightening: a config read belongs here,
# not stranded inside gestures.py.
GESTURE_POLL_MS = getattr(config, "GESTURE_POLL_MS", 4)
