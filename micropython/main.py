# main.py — eki-bin, V1
# MicroPython on Raspberry Pi Pico 2W
# Reads schedule from schedule.json on device filesystem.
# See docs/contracts/schedule-json.md, config.md, display-contract.md
#
# Display architecture (Step 2):
#   time → LeaveSignal (abstract snapshot) → DisplayContract (renderer) → LEDs
# "What's the urgency?" is computed once per tick and is independent of "how do
# we show it?" — swap visual strategies by changing CONTRACT in config.py.

import gc
import json
import math
import time

import config
import network
import ntptime
from machine import I2C, Pin
from neopixel import NeoPixel

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
MARKER_BRIGHTNESS = getattr(config, "MARKER_BRIGHTNESS", 0.15)  # LINEAR multiplier
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
_UTC_OFFSET_APPLIED = 0 if TIME_SOURCE == "rtc" else UTC_OFFSET_HOURS
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

np = NeoPixel(Pin(LED_PIN, Pin.OUT), NUM_LEDS)


# ═════════════════════════════════════════════════════════════
# STAGE 1 — time → abstract signal
# ═════════════════════════════════════════════════════════════


# Urgency is a *pure abstract level* — no colour, no animation. Those are
# rendering decisions and live on the contracts (Stage 2). V1 stand-in for a
# future Rust `enum Urgency`.
class Urgency:
    def __init__(self, name, level):
        self.name = name
        self.level = level  # 0 = hidden, 1 = most urgent … higher = more relaxed

    def __repr__(self):
        return self.name


# Singletons — compare with `is`, like enum variants. Band edges are configurable
# (URGENCY_THRESHOLDS); the comments show the defaults (2, 5).
HIDDEN = Urgency("HIDDEN", 0)
LEVEL_1 = Urgency("LEVEL 1", 1)  # below threshold[0] — go now
LEVEL_2 = Urgency("LEVEL 2", 2)  # threshold[0]–[1] — get ready
LEVEL_3 = Urgency("LEVEL 3", 3)  # above threshold[1] — plenty of time


def time_to_leave(minutes_until):
    """Departure (minutes away) → minutes until you must LEAVE the room.
    Returns None if uncatchable (you'd miss it even leaving now)."""
    if minutes_until is None:
        return None
    ttl = minutes_until - WALK_TO_STATION_MINS
    return ttl if ttl >= 0 else None  # drop trains you've already lost


def classify(ttl):
    """PURE: time-to-leave (minutes) → Urgency. Band edges from URGENCY_THRESHOLDS;
    no colour, no rendering."""
    if ttl is None:
        return HIDDEN
    near, mid = URGENCY_THRESHOLDS
    if ttl < near:
        return LEVEL_1
    if ttl < mid:
        return LEVEL_2
    return LEVEL_3


class LeaveSignal:
    """Per-tick snapshot of when to leave. Pure data, rebuilt every tick — owns
    no state and survives nothing, so there's no staleness to manage.

    ttls    : catchable times-to-leave, soonest first (continuous, minutes)
    primary : ttls[0] or None — drives the headline display
    urgency : classify(primary) — derived convenience for colour bands
    """

    def __init__(self, ttls):
        self.ttls = ttls
        self.primary = ttls[0] if ttls else None
        self.urgency = classify(self.primary)


def leave_signal(departures, now):
    """Build a LeaveSignal from a direction's schedule and the current time."""
    raw = next_departures(departures, now)  # minutes-until for the next few trains
    ttls = [t for t in (time_to_leave(m) for m in raw) if t is not None]
    return LeaveSignal(ttls)


# ═════════════════════════════════════════════════════════════
# STAGE 2 — signal → pixels (display contracts)
# ═════════════════════════════════════════════════════════════

# Named urgency→colour schemes. Pick one via COLOR_SCHEME in config.py; add your
# own here. HIDDEN never appears (handled by clear()).
#   default — calm blue (relaxed) → amber (urgent)
#   sunset  — warm amber → magenta
#   mono    — one hue for every level; urgency shows only via arc length
SCHEMES = {
    "default": {LEVEL_1: (255, 100, 0), LEVEL_2: (200, 180, 0), LEVEL_3: (0, 100, 255)},
    "sunset": {LEVEL_1: (255, 40, 0), LEVEL_2: (255, 120, 0), LEVEL_3: (180, 0, 120)},
    "mono": {LEVEL_1: (255, 90, 0), LEVEL_2: (255, 90, 0), LEVEL_3: (255, 90, 0)},
}
PALETTE = SCHEMES.get(COLOR_SCHEME, SCHEMES["default"])


def clear():
    """All LEDs off."""
    for i in range(NUM_LEDS):
        np[i] = (0, 0, 0)
    np.write()


def _arc_len(ttl):
    """time-to-leave (minutes) → number of lit LEDs, MINUTES_PER_LED minutes per
    LED, shrinking toward 1 as the deadline approaches and capped at NUM_LEDS.
    (ttl is guaranteed ≥0 — uncatchable was dropped.)"""
    lit = math.ceil(ttl / MINUTES_PER_LED)
    return max(1, min(lit, NUM_LEDS))


def _physical(logical):
    """Map a *logical* arc position (0 = the arc's origin) to a *physical* LED
    index, honouring ARC_ORIGIN. This is the seam a future per-hardware driver
    would own (reversed strips, ring wrap-around, dead-pixel gaps, …) — contracts
    stay blissfully unaware of the wiring."""
    if ARC_ORIGIN == "far":
        return NUM_LEDS - 1 - logical
    return logical  # "near" (default): logical index == physical index


def _position_offset(ttl):
    """time-to-leave (minutes) → integer offset from the anchor (always ≥1),
    POSITION_MINUTES_PER_LED minutes per LED — the ApproachContract analogue of
    _arc_len, but a single step count rather than a growing arc length. (ttl is
    guaranteed ≥0 — uncatchable was already dropped in Stage 1.)"""
    return max(1, math.ceil(ttl / POSITION_MINUTES_PER_LED))


def _arm_target(ttl, arm_len, direction):
    """time-to-leave → a logical strip index along one arm of ApproachContract's
    anchor/arm geometry, or None if the offset exceeds that arm's length —
    dropped, the same "uncatchable" precedent time_to_leave() already applies
    for trains inside WALK_TO_STATION_MINS: an approach contract can't show a
    train further out than the strip's physical arm reaches, just like an arc
    contract can't grow an arc past NUM_LEDS.

    direction: "a" walks outward with increasing indices (ANCHOR_INDEX + offset,
    phase 1's only active arm); "b" walks the other way (ANCHOR_INDEX - offset,
    phase 2 / bidirectional). Same function either way — arm choice is a config
    question (ARM_A_LEN vs ARM_B_LEN), not a code fork."""
    offset = _position_offset(ttl)
    if offset > arm_len:
        return None
    return ANCHOR_INDEX + offset if direction == "a" else ANCHOR_INDEX - offset


# ─────────────────────────────────────────────────────────────
# Memory instrumentation — docs/insights.md §11
#
# Why this exists rather than poking gc.mem_free() by hand: the ESP32-C3
# investigation cost days, and the expensive part wasn't the measuring, it
# was measuring the WRONG POOL and drawing a confident wrong conclusion.
# gc.mem_free() reported 155KB free while esp_wifi was starving, because
# MicroPython's GC heap and ESP-IDF's malloc heap are separate arenas
# competing for the same SRAM. Automating only gc.mem_free() would have
# automated that mistake, so this reports every heap the platform has and
# names them.
#
# Reports DELTAS between labelled checkpoints, not totals — "how much did
# THIS step cost" is the question that actually gets answered; a single
# free-bytes number never told us anything useful.
#
# ⚠ REAL LIMIT, worth knowing before trusting this to explain an OOM:
# each checkpoint samples AFTER a step completes, so it captures the
# step's RESIDENT cost, not its transient PEAK. The C3's actual failure
# was a compile-time spike that permanently enlarged the GC heap — this
# table would show the aftermath, not the spike. Per-frame render
# allocation is likewise not captured; that's a different question needing
# a different tool.
# ─────────────────────────────────────────────────────────────
MEM_DEBUG_ENABLED = getattr(config, "MEM_DEBUG_ENABLED", False)

_mem_marks = []  # [(label, free, alloc)] — only populated when enabled


def _mem_checkpoint(label):
    """Record free/alloc under `label`. No-op unless MEM_DEBUG_ENABLED, so
    production pays one boolean test and this can't itself become a
    consumer of the thing it measures."""
    if not MEM_DEBUG_ENABLED:
        return
    gc.collect()  # measure reclaimable-vs-live, not "whatever hasn't been
    #               swept yet" — otherwise deltas are dominated by GC timing
    _mem_marks.append((label, gc.mem_free(), gc.mem_alloc()))


def _mem_report():
    """Print the checkpoint table with per-step deltas. Called once after
    boot; safe to call with nothing recorded."""
    if not MEM_DEBUG_ENABLED or not _mem_marks:
        return
    print("\n  ── memory ─────────────────────────────────────")
    prev_free = None
    for label, free, alloc in _mem_marks:
        if prev_free is None:
            print("    %-22s free %7d  alloc %7d" % (label, free, alloc))
        else:
            delta = free - prev_free
            print("    %-22s free %7d  alloc %7d   (%+d)"
                  % (label, free, alloc, delta))
        prev_free = free

    # The §11 lesson, encoded: on ESP32 the GC heap above is NOT the pool a
    # WiFi failure comes from. Show the real one too, or this tool repeats
    # the exact error it exists to prevent.
    try:
        import esp32
        print("    ESP-IDF heap (the pool esp_wifi allocates from —")
        print("    NOT the GC heap above; see insights.md §11):")
        for i, region in enumerate(esp32.idf_heap_info(esp32.HEAP_DATA)):
            total, free, largest, minimum = region
            print("      region %d: total %7d  free %7d  largest %7d"
                  % (i, total, free, largest))
    except (ImportError, AttributeError):
        pass  # not an ESP32 — one heap, already reported above
    print()


def _heartbeat_pin(name):
    """Construct the status-heartbeat Pin, or None if disabled. Pulled out as its
    own function (rather than inline in main()) purely so it's host-testable
    without pulling in WiFi/NTP/the live loop."""
    return Pin(name, Pin.OUT) if name else None


# Temporal-dither state: one carried rounding-error per (physical LED, channel).
# It PERSISTS across frames — that's the whole point (sigma-delta), so a sub-integer
# brightness like 1.4 averages to 1.4 over time instead of truncating to 1. The
# staggered init decorrelates the pattern across LEDs so they don't flicker in
# lockstep (spatial + temporal averaging → a smooth glow).
_residual = [[((i * 3 + ch) % 5) / 5.0 for ch in range(3)] for i in range(NUM_LEDS)]


def _quantize(value, res, ch):
    """Round `value` (float 0..255) to an int, carrying the error to the next
    frame via res[ch]. Over many frames, mean(output) == value. Integer inputs
    stay exact (no flicker); only fractional values dither."""
    v = value + res[ch]
    q = int(v + 0.5)
    if q < 0:
        q = 0
    elif q > 255:
        q = 255
    res[ch] = v - q
    return q


def _clamp255(value):
    """Clip a float channel value into the valid 0..255 output range, then
    truncate to int. `_quantize` does its own clamping for the dithered path;
    this covers the two plain-truncation paths (DITHER off, and the STATIC
    path in _write_frame) — both matter now that `mult` isn't guaranteed to
    stay within 0..1 (e.g. ANCHOR_BRIGHTNESS > 1.0 to render brighter than a
    normal "full" position)."""
    if value < 0:
        return 0
    if value > 255:
        return 255
    return int(value)


def _layer_mult(index):
    """Relative brightness (0..1) for the `index`-th train layer. index 0 (the
    primary) is always full-relative (1.0); each layer beyond it is dimmer by
    another factor of BACKGROUND_BRIGHTNESS — geometric falloff, so N_TRAINS can
    grow (2, 3, ...) without needing a config knob per layer."""
    return 1.0 if index == 0 else BACKGROUND_BRIGHTNESS ** index


def _layer_hue_shift(index):
    """Hue-rotation degrees for the `index`-th train layer, for EchoContract.
    index 0 (the primary) gets none; each layer beyond it rotates further
    (2nd = ×1, 3rd = ×2, ...) — same per-index scaling idea as _layer_mult, but
    linear rather than geometric: hue is an angle, so "further back → further
    rotated" is the natural analogue of "further back → dimmer" for a hue
    differentiator, not a diminishing-returns curve."""
    return 0 if index == 0 else SECONDARY_HUE_SHIFT_DEG * index


def _write_frame(frame):
    """Composite a resolved frame onto the physical strip in ONE np.write().
    This is the shared tail every render path converges on, and honours the
    `_physical()` HAL seam either way. `_paint_layers` builds `frame` from
    arc-shaped layers; a contract with different geometry (e.g.
    ApproachContract's single positions, not arcs) can build `frame` directly
    and call this instead.

    Each entry in `frame` is one of:
      None                    — LED off
      (color, mult)           — ANIMATED: gamma-corrects `mult`, then dithers
                                 (if DITHER) — for a pixel whose value is
                                 genuinely changing frame-to-frame (a mid-
                                 crossfade position, a breathing arc). Dithering
                                 approximates a fractional brightness by
                                 averaging across frames — it has something to
                                 average *because the target is moving*.
      (color, mult, "static") — STATIC: `level = BRIGHTNESS * mult` directly
                                 (no gamma, no dither) for a pixel whose target
                                 does NOT change between frames (an idle/floor
                                 LED, the always-on anchor, a train position
                                 that's finished crossfading and is just
                                 sitting there). Dithering a CONSTANT value
                                 has nothing to average against — it just
                                 toggles the same one-or-two codes forever,
                                 which at low absolute brightness (few output
                                 codes to work with) reads as visible flicker,
                                 and because each of R/G/B is deliberately
                                 phase-staggered per-LED (see `_residual` below
                                 — decorrelation so LEDs don't flicker in
                                 lockstep), that flicker shows up as
                                 asynchronous per-channel noise: a "sparkling
                                 rgb" idle LED instead of a smooth dim glow.
                                 Same root cause docs/insights.md §6 already
                                 hit with EchoContract's dimmed secondary layer
                                 — see docs/contracts/approach-contract.md."""
    for logical in range(NUM_LEDS):
        phys = _physical(logical)
        entry = frame[logical]
        if entry is None:
            np[phys] = (0, 0, 0)
            continue
        color, mult = entry[0], entry[1]
        if len(entry) > 2 and entry[2] == "static":
            level = BRIGHTNESS * mult
            np[phys] = tuple(_clamp255(color[ch] * level) for ch in range(3))
            continue
        level = BRIGHTNESS * gamma(mult)
        if DITHER:
            res = _residual[phys]
            np[phys] = tuple(_quantize(color[ch] * level, res, ch) for ch in range(3))
        else:
            np[phys] = tuple(_clamp255(color[ch] * level) for ch in range(3))
    np.write()


def _paint_layers(layers):
    """Composite multiple (color, lit, mult) arcs into a frame — the
    paradigm-independent primitive `_paint` is built on. Each layer is a
    logical-position count (`lit`) exactly like `_paint` takes; this is what
    makes "N trains" work identically for a bar, a ring, or a randomized layout:
    none of this function's geometry knowledge is paradigm-specific — that all
    lives in `_physical()`, which every layer still goes through.

    Layers are composited back-to-front: entries LATER in `layers` are painted
    FIRST, so entries EARLIER in the list win where arcs overlap. In practice
    `layers` is ordered primary-first (brightest, usually shortest), so the
    primary always wins the overlap — this holds even in the edge case where two
    trains happen to produce the same arc length."""
    frame = [None] * NUM_LEDS  # logical position → (color, mult) or None (dark)
    for color, lit, mult in layers[::-1]:  # slicing, not reversed() — some
        # MicroPython builds omit the reversed() builtin; slicing is universal
        for logical in range(lit):
            frame[logical] = (color, mult)
    _write_frame(frame)


def _paint(color, lit, mult=1.0):
    """Light the first `lit` LEDs along the arc (logical 0 = origin) in `color`,
    scaled by the global BRIGHTNESS ceiling × `mult`. (`mult` lets animations dim
    the whole arc without touching the palette.) Dark LEDs off. One np.write().

    A single-layer call to _paint_layers() — kept as its own function since most
    contracts only ever need one layer, and this reads more directly than
    wrapping every call site in a one-element list."""
    _paint_layers([(color, lit, mult)])


# ─────────────────────────────────────────────────────────────
# Animation primitives  ←  YOUR PART (reusable building blocks)
# ─────────────────────────────────────────────────────────────
# Pure, LED-free helpers that contracts compose into motion. Keeping them pure
# means they're host-testable (no hardware) and reused across every contract,
# instead of each one re-deriving wave math. Three layers:
#   A. phase / shape — turn elapsed time into a 0.0–1.0 wave
#   B. envelopes     — named brightness multipliers (breathe / blink / pulse)
#   C. colour        — interpolate / dim (r, g, b) tuples
# Candidates to extract into a separate animations.py once they settle.
#
# `dim` and `lerp_color` are worked examples — they set the pattern; you draft
# the rest. None are wired into a contract yet, so stubs are safe to leave.


# ── A. phase / shape (all take/return 0.0–1.0) ──────────────────
def phase_sawtooth(elapsed_ms, period_ms):
    """Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return elapsed_ms % period_ms / period_ms


def phase_exp_sawtooth(elapsed_ms, period_ms):
    """Exponential/surved Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return ((elapsed_ms % period_ms) / period_ms) ** 2


def phase_inv_parabola(elapsed_ms, period_ms):
    """inverse parabolic Sawtooth: position within the current cycle, 0.0 → 1.0, then repeats."""
    return 1 - ((elapsed_ms % period_ms) / period_ms) ** 2


def tri01(p):
    """Triangle from a 0..1 phase: 0 → 1 (at p=0.5) → 0."""
    return 1 - abs(2 * p - 1)


def sine01(p):
    """Smooth sine from a 0..1 phase, starting at 0: 0 → 1 → 0."""
    return 0.5 * (1 - math.cos(2 * math.pi * p))


def square01(p, duty=0.5):
    """Hard gate from a 0..1 phase: 1.0 while p < duty, else 0.0."""
    return 1.0 if p < duty else 0.0


# ── B. brightness envelopes (elapsed_ms → 0.0–1.0 multiplier) ───
# Each composes layer A and maps into [floor, ceiling] so the arc never fully
# dies (floor) and — new — never needs to reach full-static brightness either
# (ceiling). Default ceiling=1.0 keeps every existing call byte-identical;
# pass a lower ceiling for a layer that should never be mistaken for a
# fully-lit primary at its peak (e.g. a breathing 2nd-train band — see
# docs/insights.md §6: "don't want to mistake bright mode for all lit").
def breathe(elapsed_ms, period_ms=8000, floor=0.2, ceiling=1.0):
    """Smooth in/out glow."""
    return floor + (ceiling - floor) * sine01(phase_sawtooth(elapsed_ms, period_ms))


def breathe_exponent(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """exponential build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_exp_sawtooth(elapsed_ms, period_ms))


def breathe_inverse(elapsed_ms, period_ms=2200, floor=0.2, ceiling=1.0):
    """inverse build in/out glow"""
    return floor + (ceiling - floor) * sine01(phase_inv_parabola(elapsed_ms, period_ms))


def blink(elapsed_ms, period_ms=600, duty=0.5, floor=0.2, ceiling=1.0):
    """Hard on/off between `floor` and `ceiling` (`duty` = fraction of the cycle 'on')."""
    return floor + (ceiling - floor) * square01(phase_sawtooth(elapsed_ms, period_ms), duty)


def pulse(elapsed_ms, period_ms=1000, floor=0.1, ceiling=1.0):
    """Sharp triangular ramp up/down, mapped into [floor, ceiling]."""
    return floor + (ceiling - floor) * tri01(phase_sawtooth(elapsed_ms, period_ms))


# ── C. colour helpers ───────────────────────────────────────────
def dim(color, mult):
    """Scale an (r, g, b) by mult (0.0–1.0). Worked example — the pattern."""
    return tuple(int(c * mult) for c in color)


def lerp_color(c0, c1, t):
    """Blend c0 → c1 as t goes 0 → 1 (per-channel linear). Worked example.
    Lets a contract *fade* between urgency colours instead of snapping bands."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def _rgb_to_hsv(r, g, b):
    """(r,g,b) each 0..1 → (h,s,v) each 0..1. Standard reference algorithm
    (same one CPython's colorsys uses — not reinvented, just inlined since
    MicroPython doesn't ship that module)."""
    maxc, minc = max(r, g, b), min(r, g, b)
    v = maxc
    if maxc == minc:
        return 0.0, 0.0, v
    s = (maxc - minc) / maxc
    rc = (maxc - r) / (maxc - minc)
    gc = (maxc - g) / (maxc - minc)
    bc = (maxc - b) / (maxc - minc)
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    return (h / 6.0) % 1.0, s, v


def _hsv_to_rgb(h, s, v):
    """(h,s,v) each 0..1 → (r,g,b) each 0..1. Inverse of _rgb_to_hsv."""
    if s == 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    return v, p, q


def hue_rotate(color, degrees):
    """Shift a colour's HUE by `degrees` (can be any number, wraps mod 360),
    keeping saturation and brightness the same — a "similar yet distinguishable"
    variant, e.g. for a 2nd train's colour instead of dimming it (dimming alone
    doesn't work well on bare-strip hardware — see docs/insights.md §6: at low
    brightness, dithering runs out of headroom and diffusion runs out of light).
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r, g, b = _hsv_to_rgb(h, s, v)
    # round, not truncate — a 360° round-trip should be a lossless identity,
    # not off-by-one from floating-point drift through the hsv conversion.
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def desaturate(color, saturation):
    """Scale a colour's SATURATION by `saturation` (0.0 = fully gray, 1.0 =
    unchanged), keeping hue and value the same — a genuinely MUTED variant of
    a colour, not just a dimmer one. `hue_rotate()`'s counterpart on the other
    HSV axis: hue_rotate keeps the same brightness/vividness and shifts which
    colour it is; desaturate keeps the same colour/brightness and shifts how
    vivid it is.

    Distinct from just lowering a render `mult` (brightness): scaling
    brightness scales R/G/B by the same factor, which is mathematically
    identical to picking a *dimmer* version of the same colour — it can't
    produce a *muted* (desaturated, toward-gray) version, since that requires
    each channel to move toward the colour's own maximum channel value, not
    toward zero. Used for ApproachContract's LINE_COLOR (LINE_SATURATION) —
    see docs/contracts/approach-contract.md.
    """
    r, g, b = (c / 255.0 for c in color)
    h, s, v = _rgb_to_hsv(r, g, b)
    s *= max(0.0, saturation)
    r, g, b = _hsv_to_rgb(h, s, v)
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


# ── D. perceptual correction  ←  YOUR PART ──────────────────────
def gamma(mult, g=GAMMA):
    """Perceptual-brightness correction for an animation multiplier (0..1 → 0..1).

    Why: the eye responds ~logarithmically but WS2812B PWM is linear, so a linear
    fade looks steppy/uneven — worst at the dim end. Raising the multiplier to a
    power `g` (≈2.2–2.8) spreads the visible steps to match perception. This is
    the single biggest smoothness win for the breath — bigger than frame rate.

    Contract: monotonic; endpoints fixed (gamma(0)=0, gamma(1)=1); stays in [0,1].
    Applied to `mult` in _paint (not the base colour), so static contracts — which
    pass mult=1.0 → gamma(1.0)=1.0 — are unaffected.

    TODO(you): return mult ** g   (that's the whole thing; g comes from config).
    Currently a no-op pass-through so the display keeps working until you fill it.

    ⚠ Interaction to watch: gamma pushes the dim end *down* (0.2 ** 2.2 ≈ 0.03), so
    after you enable it the breath will dip closer to black — you may want to raise
    BREATHE_FLOOR to keep it visible through the jar.
    """
    return mult ** g


class DisplayContract:
    """A rendering strategy. The main loop treats every contract identically:
    it calls render(signal, phase_ms) and honours frame_ms for timing.

      frame_ms = None  → static: draw one frame, then sleep the interval
                         (deep-sleep-friendly — the V2 power path)
      frame_ms = int   → animated: redraw every frame_ms across the interval
                         (cannot deep-sleep while animating)
    """

    frame_ms = None

    def render(self, signal, phase_ms):
        """Draw a single frame. `phase_ms` is a monotonic ms clock (absolute
        `time.ticks_ms()`; `0` for static contracts, which ignore it). Animated
        contracts feed it to the phase functions, which reduce it mod their period
        — so it flows continuously across intervals."""
        raise NotImplementedError


class SandTimerContract(DisplayContract):
    """Shrinking arc, colour by urgency band, no pulse. The default.

    Shows up to N_TRAINS departures as nested arcs: the primary lights up
    bright out to its own length; each further-out train (same colour, always
    equal-or-longer since it's further away) extends a dimmer band beyond
    that — "and if you miss this one, you've got until here for the next."
    """

    frame_ms = None
    COLOR = PALETTE

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        color = self.COLOR[signal.urgency]  # one colour for every layer, per spec
        layers = [
            (color, _arc_len(ttl), _layer_mult(i))
            for i, ttl in enumerate(signal.ttls[:N_TRAINS])
        ]
        _paint_layers(layers)


class ColorContract(DisplayContract):
    """Full bar always; only the COLOUR changes with urgency. No shrinking arc,
    no pulse — the calmest, most abstract strategy.

    Deliberately ignores N_TRAINS: it has no arc/length axis to hang a second
    train on (the whole strip is always lit) — not every contract needs to
    consume every signal field.
    """

    frame_ms = None
    COLOR = PALETTE

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        _paint(self.COLOR[signal.urgency], NUM_LEDS)


class BreathingContract(DisplayContract):
    """Arc that breathes — with configurable envelope function.

    Same N_TRAINS nesting as SandTimerContract; the breath multiplier is
    combined with each layer's falloff (_layer_mult(i) * breath), so every
    train's band breathes together rather than independently."""

    frame_ms = FRAME_MS
    COLOR = PALETTE
    # staticmethod so a plain function stored as a class attr doesn't bind `self`
    # (otherwise self.breathe_fn(phase_ms) would call breathe(self, phase_ms)).
    breathe_fn = staticmethod(breathe)

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        breath = self.breathe_fn(phase_ms, BREATHE_PERIOD_MS, BREATHE_FLOOR)
        color = self.COLOR[signal.urgency]
        layers = [
            (color, _arc_len(ttl), _layer_mult(i) * breath)
            for i, ttl in enumerate(signal.ttls[:N_TRAINS])
        ]
        _paint_layers(layers)


class BreathingExponentContract(BreathingContract):
    """Same as Breathing, but with exponential curve."""

    breathe_fn = staticmethod(breathe_exponent)


class BreathingInverseContract(BreathingContract):
    """Same as Breathing, but inverted."""

    breathe_fn = staticmethod(breathe_inverse)


class EchoContract(DisplayContract):
    """Primary train: static, full brightness (SandTimer's treatment). Every
    train beyond it: hue-shifted + gently breathing (never dipping below
    SECONDARY_BREATHE_FLOOR) — "echoes" the primary rather than dimming it.

    This exists because brightness-only differentiation didn't hold up on
    real hardware (docs/insights.md §6: at low absolute brightness, dithering
    runs out of headroom and diffusion runs out of light — flicker + visible
    LED die instead of ambient glow). Colour + subtle motion sidesteps both
    problems by keeping every layer near full brightness.

    Composes existing primitives rather than reinventing them: _arc_len for
    geometry (same as SandTimer/Breathing), breathe_fn for motion (same
    envelope functions Breathing uses, just with its own period/floor so
    tuning one doesn't fight the other), hue_rotate for colour.
    """

    frame_ms = FRAME_MS  # animated — secondary layers breathe
    COLOR = PALETTE
    breathe_fn = staticmethod(breathe)  # overridable per subclass, like Breathing*

    def render(self, signal, phase_ms):
        if signal.urgency is HIDDEN:
            clear()
            return
        base_color = self.COLOR[signal.urgency]
        layers = []
        for i, ttl in enumerate(signal.ttls[:N_TRAINS]):
            if i == 0:
                color, mult = base_color, 1.0  # primary: static, full brightness
            else:
                color = hue_rotate(base_color, _layer_hue_shift(i))
                mult = self.breathe_fn(
                    phase_ms, SECONDARY_BREATHE_PERIOD_MS, SECONDARY_BREATHE_FLOOR
                )
            layers.append((color, _arc_len(ttl), mult))
        _paint_layers(layers)


class _TrainState:
    """CHASE-transition state for ONE train marker. Phase 1/2 (single train
    per arm) needed exactly one of these per arm; N_TRAINS>1 (iteration 2)
    keeps a LIST of these per arm — one per rank (closest, 2nd-closest, …) —
    so every simultaneous marker animates independently, on its own clock,
    without interfering with any other slot's."""

    def __init__(self):
        self.index = None  # current/incoming train position, or None
        self.color = None
        self.sweep_from = None  # index a sweep is currently animating FROM,
        #   or None if settled (or nothing to sweep between — see below)
        self.transition_start = None  # phase_ms the current sweep began


def _advance_train(frame, train, target, color, phase_ms):
    """Advance one train's CHASE transition given this tick's target index
    (or None), and paint its contribution into `frame` (mutated in place,
    NOT returned). The one place the transition logic lives — every call
    site (single train, N_TRAINS>1, bidirectional) goes through this, once
    per train slot, so the logic exists exactly once regardless of how many
    are active.

    A moving highlight sweeps LED-by-LED from the old position to the new
    one, one LED lit at a time, always at FULL brightness (mult=1.0,
    STATIC). This deliberately replaced an earlier brightness/colour-blend
    crossfade: that design necessarily passed through low-brightness
    intermediate values, and at low enough absolute brightness temporal
    dithering breaks down on this hardware (visible flicker — the exact
    failure mode docs/insights.md §6 and the marker-tick fix both already
    hit). CHASE never asks for anything between "off" and "full" — every
    touched LED is always a fully-populated 8-bit code, so dithering is
    never needed at all during a transition, not just tuned to be less
    visible. See docs/contracts/approach-contract.md § Chase transition."""
    if target != train.index:
        # A sweep only makes sense between two KNOWN positions. Appearing
        # from nothing (a train's first tick) or vanishing to nothing (no
        # longer catchable) has no LED to sweep from/to — snap instead, no
        # animation possible or needed.
        if target is not None and train.index is not None:
            train.sweep_from = train.index
        else:
            train.sweep_from = None
        train.index = target
        train.color = color
        train.transition_start = phase_ms

    if train.index is None:
        return  # nothing to show for this slot right now

    if train.sweep_from is None:
        # Settled (or just snapped in/out with nothing to sweep between) —
        # identical every frame until the position next changes.
        frame[train.index] = (train.color, 1.0, "static")
        return

    progress = 1.0
    if TRANSITION_MS > 0 and train.transition_start is not None:
        elapsed = phase_ms - train.transition_start  # phase_ms: absolute
        #   ticks_ms(), same "no snap-back across intervals" pattern the
        #   breathing envelopes use — see render_for_interval().
        progress = min(1.0, max(0.0, elapsed / TRANSITION_MS))

    # Divide the sweep into `distance` equal LED-to-LED steps (distance=1 for
    # the common one-LED-per-tick hop → a single sharp switch at the
    # halfway point; larger jumps sweep through every LED in between, each
    # getting an equal time-slice). `min(distance, ...)` clamps the final
    # step to land exactly on `train.index` at progress=1.0.
    distance = abs(train.index - train.sweep_from)
    sign = 1 if train.index > train.sweep_from else -1
    step = min(distance, int(progress * (distance + 1)))
    frame[train.sweep_from + sign * step] = (train.color, 1.0, "static")

    if progress >= 1.0:
        train.sweep_from = None  # sweep finished — future frames render settled


def _advance_arm(frame, slots, signal, arm_len, direction, base_color, phase_ms):
    """Advance every train slot for ONE arm (up to len(slots) == N_TRAINS,
    soonest-first, same rank convention as _paint_layers' N_TRAINS handling
    elsewhere) and paint each into `frame`.

    Slot 0 (the primary/closest train) renders `base_color` unshifted; every
    slot beyond it is hue-rotated (_layer_hue_shift — the same per-index
    scaling EchoContract already uses) so multiple simultaneous markers stay
    visually distinguishable WITHOUT dimming. Dimming a secondary layer is
    exactly the failure mode docs/insights.md §6 already ruled out (breaks
    at low absolute brightness on this hardware) — hue doesn't have that
    problem, and every CHASE-rendered train is full brightness anyway (see
    _advance_train), so dimming a slot would also silently undo that.

    Slots are advanced/painted in REVERSE order (last slot first) so slot 0
    is painted LAST and wins any index collision — same convention
    _paint_layers uses for arc-based contracts.

    Note on identity: Stage 1 (LeaveSignal) is deliberately ephemeral and
    tracks no train identity across ticks — "slot 0" means "whichever train
    is currently closest," not a specific physical train. If the current
    primary departs and the former rank-1 train becomes rank-0, slot 0's
    CHASE will animate from the old primary's position to wherever that
    train already was, rather than continuing rank-1's own animation. This
    is an accepted simplification consistent with Stage 1's existing
    "ephemeral, rebuilt every tick, no identity" design — true per-train
    identity tracking would be a bigger structural change than "N trains,
    set in config" scoped for this iteration."""
    ttls = signal.ttls if signal.urgency is not HIDDEN else []
    n = len(slots)
    targets = [None] * n
    for i, ttl in enumerate(ttls[:n]):
        targets[i] = _arm_target(ttl, arm_len, direction)

    for i in range(n - 1, -1, -1):
        color = base_color if i == 0 else hue_rotate(base_color, _layer_hue_shift(i))
        _advance_train(frame, slots[i], targets[i], color, phase_ms)


class ApproachContract(DisplayContract):
    """Positional/approach paradigm: each train renders as a SINGLE LED that
    moves toward ANCHOR_INDEX as its time-to-leave shrinks, rather than an
    arc that grows/shrinks from a fixed origin. See
    docs/contracts/approach-contract.md for the full design rationale.

    Phase 1: ARM_B_LEN=0, single direction — call render(signal, phase_ms),
    exactly as before. Phase 2 (bidirectional, DISPLAY_DIRECTION_B configured):
    call render_dual(signal_a, signal_b, phase_ms) instead — one arm's worth
    of trains per direction. main()'s loop picks the entry point;
    ApproachContract itself doesn't know which mode it's in beyond which
    method got called.

    N_TRAINS (iteration 2, reusing the same knob the arc contracts use)
    controls how many simultaneous markers each arm shows, soonest-first —
    default 1, phase 1/2's original single-train-per-arm behaviour unchanged.

    Two independent brightness surfaces, matching how this actually reads to
    a viewer: ANCHOR_BRIGHTNESS (the "0") and MARKER_BRIGHTNESS/MARKER_COLOR
    (the idle "tick" LEDs — every position that isn't the anchor or a train
    right now). A train is never dimmer than BRIGHTNESS itself — no separate
    knob, and (since the CHASE transition below) no dim intermediate state
    either. MARKER_COLOR is deliberately a different colour from LINE_COLOR,
    not a dimmed version of it, so an idle tick can't be mistaken for "a
    very distant train" (see the concept doc's Marker ticks section).
    """

    frame_ms = FRAME_MS
    line_color = desaturate(LINE_COLOR, LINE_SATURATION)  # computed once at
    #   module load — LINE_SATURATION=1.0 (default) is a no-op identity

    def __init__(self):
        # Instance state, not class state: tracks the *last actually rendered*
        # position across calls, so a change in position can be detected and
        # crossfaded — unlike every other contract here, this one is not a
        # pure function of (signal, phase_ms) alone. Two arms' worth of slots
        # always exist; phase 1 (render()) simply never touches _arm_b.
        self._arm_a = [_TrainState() for _ in range(N_TRAINS)]
        self._arm_b = [_TrainState() for _ in range(N_TRAINS)]

    def set_line_color(self, color):
        """Point this contract at one line's colour. Shadows the class-level
        default with an instance attribute; passing None restores it.

        This is what makes a line identifiable **at a glance**, which is the
        whole requirement: the premise is looking over at a random moment, so
        identity has to live in the static view rather than in a cue that
        only fires when you cycle (gesture-envelope.md §11). The anchor stays
        neutral — set ANCHOR_COLOR to white — and the moving train dots carry
        the colour, exactly like a metro map.

        LINE_SATURATION still applies, so a per-enclosure desaturation
        setting keeps working across every line rather than being defeated by
        the schedule's nominal colours."""
        self.line_color = desaturate(color or LINE_COLOR, LINE_SATURATION)

    def render(self, signal, phase_ms):
        """Phase 1 — single direction. Kept as its own method (not
        render_dual with a None second signal) so a phase-1 config's
        behaviour can never be perturbed by phase-2 code."""
        frame = [(MARKER_COLOR, MARKER_BRIGHTNESS, "static")] * NUM_LEDS
        _advance_arm(frame, self._arm_a, signal, ARM_A_LEN, "a", self.line_color, phase_ms)

        # Anchor is painted last so it always wins, even the instant a train
        # lands on ANCHOR_INDEX itself — it never participates in train logic.
        # Always STATIC: it's a fixed brightness forever, never animated.
        frame[ANCHOR_INDEX] = (ANCHOR_COLOR, ANCHOR_BRIGHTNESS, "static")
        _write_frame(frame)

    def render_dual(self, signal_a, signal_b, phase_ms):
        """Phase 2 — bidirectional: one arm's worth of trains per direction,
        each with its own independent CHASE transition, composited into the
        same frame. Arm "a" and arm "b" occupy disjoint index ranges
        (ANCHOR_INDEX+offset vs ANCHOR_INDEX-offset — see _arm_target), so
        there's no overlap to resolve between them; only the anchor itself
        can coincide, and it's painted last regardless."""
        frame = [(MARKER_COLOR, MARKER_BRIGHTNESS, "static")] * NUM_LEDS
        _advance_arm(frame, self._arm_a, signal_a, ARM_A_LEN, "a", self.line_color, phase_ms)
        _advance_arm(frame, self._arm_b, signal_b, ARM_B_LEN, "b", self.line_color, phase_ms)
        frame[ANCHOR_INDEX] = (ANCHOR_COLOR, ANCHOR_BRIGHTNESS, "static")
        _write_frame(frame)


# Registry: config's CONTRACT name → class. Add new contracts here so they're
# selectable from config.py without touching the main loop.
CONTRACTS = {
    "sandtimer": SandTimerContract,
    "color": ColorContract,
    "breathing": BreathingContract,
    "breathing_exponent": BreathingExponentContract,
    "breathing_inverse": BreathingInverseContract,
    "echo": EchoContract,
    "approach": ApproachContract,
}
ACTIVE_CONTRACT = CONTRACTS.get(CONTRACT_NAME, SandTimerContract)()


def is_quiet(now):
    """True during the configured quiet hours. The window can wrap past midnight
    (e.g. 23:00 → 06:00), so we test the gap with OR, not a simple range."""
    return now >= QUIET_START or now < QUIET_END


# ─────────────────────────────────────────────────────────────
# Schedule loading
# [→ Rust] build.rs reads schedule.json at compile time and emits
#          const arrays — zero runtime parsing cost on device.
# ─────────────────────────────────────────────────────────────
def load_schedule(filename):
    """
    Load schedule.json from device filesystem.
    Returns the full parsed dict (station, weekday, weekend).
    Raises (OSError: missing file; ValueError: malformed JSON) rather than
    halting itself — the caller decides what "failed to load" looks like on
    the LEDs (see main()'s call site and
    docs/contracts/led-status-messages.md's schedule-load-failure entry).
    """
    try:
        with open(filename) as f:
            return json.load(f)
    except OSError:
        print(f"✗ Schedule file not found: {filename}")
        print("  Upload it with: make upload")
        raise
    except ValueError:
        print(f"✗ Schedule file malformed (bad JSON): {filename}")
        print("  Regenerate it with: make schedule && make upload")
        raise


# ─────────────────────────────────────────────────────────────
# Time helpers
# [→ Rust] read_rtc() reads DS3231 over I2C → (hours, minutes, weekday)
# ─────────────────────────────────────────────────────────────
def local_time():
    """
    Return (minutes_since_midnight, weekday) in local time.
    weekday: 0=Monday … 6=Sunday (MicroPython convention)

    NTP sets the RTC to UTC, so we add UTC_OFFSET_HOURS to get local time —
    and also account for the day boundary, so the correct weekday is used
    when UTC and local time are on different calendar days.
    (e.g. UTC 22:00 Thursday = JST 07:00 Friday)

    With TIME_SOURCE="rtc" the clock is ALREADY local (`mpremote rtc --set`
    writes host local time), so no offset is applied — see
    _UTC_OFFSET_APPLIED. Reading the raw clock as UTC in that case would
    put the display UTC_OFFSET_HOURS ahead of reality.
    """
    raw = time.localtime()  # (year, mon, mday, hour, min, sec, weekday, yearday)
    utc_minutes = raw[3] * 60 + raw[4]
    local_minutes_abs = utc_minutes + _UTC_OFFSET_APPLIED * 60

    day_overflow = local_minutes_abs // (24 * 60)  # 0 or 1
    local_minutes = local_minutes_abs % (24 * 60)
    local_weekday = (raw[6] + day_overflow) % 7

    return local_minutes, local_weekday


def current_period(weekday):
    """Return 'weekday' or 'weekend' for the given weekday index."""
    return "weekend" if weekday >= 5 else "weekday"


def fmt_time(minutes):
    """Format minutes-since-midnight as HH:MM."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ─────────────────────────────────────────────────────────────
# Schedule logic
# [→ Rust] Iterator::filter().take(n) on a sorted &[u16]
# ─────────────────────────────────────────────────────────────
def next_departures(schedule, now, count=3):
    """
    Return list of up to `count` minutes-until-departure values (ints).
    Empty list means no trains remain today.
    """
    return [m - now for m in schedule if m > now][:count]


# ─────────────────────────────────────────────────────────────
# Startup sequence ("boot ceremony") — docs/contracts/startup-sequence.md
# Runs once at power-on, before the main loop; never recurs during normal
# operation. Not a DisplayContract — at boot there's no LeaveSignal yet (no
# WiFi, no NTP time, schedule not even loaded), so this is boot-time
# procedural code that observes LIVE connection state, not a pure render of
# an already-known value.
# ─────────────────────────────────────────────────────────────
def _startup_circle_index(elapsed_ms):
    """PURE: elapsed ms of the loading-circle spin → which LED is lit, at
    STARTUP_SPIN_HZ revolutions/sec. Host-testable in isolation from the real
    connect_wifi() poll loop below, which isn't (real time.ticks_ms())."""
    period_ms = 1000.0 / STARTUP_SPIN_HZ
    return int(phase_sawtooth(elapsed_ms, period_ms) * NUM_LEDS) % NUM_LEDS


def _draw_startup_circle(elapsed_ms):
    """One frame of the loading-circle spin: a single lit LED, everything
    else off. No dim intermediate value at all (fully on or fully off) —
    STATIC path (see _write_frame), no dithering needed."""
    frame = [None] * NUM_LEDS
    frame[_startup_circle_index(elapsed_ms)] = (STARTUP_COLOR, 1.0, "static")
    _write_frame(frame)


def _startup_burst_mult(elapsed_ms):
    """PURE: elapsed ms into the success burst → brightness mult (0..1).
    Rises linearly over STARTUP_BURST_MS, then decays linearly over
    STARTUP_FADE_MS. Host-testable; the real-time loop that calls this
    (_play_startup_burst) isn't — same split render_for_interval/
    _render_dispatch already established."""
    if STARTUP_BURST_MS > 0 and elapsed_ms < STARTUP_BURST_MS:
        return elapsed_ms / STARTUP_BURST_MS
    decay_elapsed = elapsed_ms - STARTUP_BURST_MS
    if STARTUP_FADE_MS <= 0 or decay_elapsed >= STARTUP_FADE_MS:
        return 0.0
    return 1.0 - (decay_elapsed / STARTUP_FADE_MS)


def _play_startup_burst():
    """The 'hanabi' success cue: all LEDs together (contract-agnostic — no
    CONTRACT is "current" yet), a quick bright rise then a slow decay. This
    genuinely changes every frame, unlike a settled/idle pixel, so the
    ANIMATED path (gamma + dither, via a 2-tuple frame entry) is the right
    one here — dithering only causes trouble on a value that ISN'T changing
    (see docs/contracts/approach-contract.md § Marker ticks); a decaying
    pulse has something to average against. Ends by clearing the strip —
    the main loop's first real frame follows immediately after."""
    start = time.ticks_ms()
    total_ms = STARTUP_BURST_MS + STARTUP_FADE_MS
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= total_ms:
            break
        mult = _startup_burst_mult(elapsed)
        _write_frame([(STARTUP_COLOR, mult)] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _startup_error_mult(elapsed_ms):
    """PURE: elapsed ms → brightness mult for the persistent failure breathe.
    Thin wrapper over the existing breathe() envelope, its own dedicated
    period (ERROR_BREATHE_PERIOD_MS, not BREATHE_PERIOD_MS)."""
    return breathe(elapsed_ms, ERROR_BREATHE_PERIOD_MS, floor=0.15)


def _run_startup_failure_forever(color=None):
    """Persistent breathe — a genuine DEAD END, not a retry loop, by design
    (see docs/contracts/startup-sequence.md § Failure recovery).
    Distinguishes "broken, needs help" from every other state at a glance,
    and doesn't pretend to work when it can't. Needs a physical reset/
    power-cycle to leave this state; never returns on its own.

    `color` defaults to ERROR_COLOR (WiFi/NTP connect failure) — pass
    SCHEDULE_ERROR_COLOR for a schedule-load failure instead. Different
    failure CAUSES get visually distinct colours on purpose, so whoever's
    looking at a dead jar with no laptop handy can tell which one happened
    — see docs/contracts/led-status-messages.md."""
    color = ERROR_COLOR if color is None else color
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _write_frame([(color, _startup_error_mult(elapsed))] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)


def run_startup_sequence():
    """The whole boot ceremony. On success: connecting spin, then the
    success burst, then returns — the main loop takes over immediately
    after. On WiFi failure: _run_startup_failure_forever(), which NEVER
    RETURNS (see its docstring) — this function correspondingly never
    returns either, in that case.

    TIME_SOURCE="rtc" skips WiFi and NTP entirely and trusts whatever the
    board's RTC already holds (set it at provisioning time with
    `make set-time`). Added because the ESP32-C3 genuinely cannot fit
    esp_wifi alongside a MicroPython app this size — see docs/insights.md
    §11 — so on that board this is the difference between a working unit
    and no unit. It also happens to be the direction V2 is going anyway
    (DS3231 RTC, no WiFi in normal operation), so this is a step toward
    the planned architecture rather than a detour around a bug."""
    if TIME_SOURCE == "rtc":
        print("  TIME_SOURCE='rtc' — skipping WiFi/NTP, trusting the board clock.")
        print("  (Set it with `make set-time`; it survives soft reset, NOT power loss.)")
        _play_startup_burst()
        return
    if not connect_wifi():
        print("  ✗ WiFi failed — check config.py. Reset to retry.")
        _run_startup_failure_forever(ERROR_COLOR)
    if not sync_ntp():
        print("  Warning: time may be wrong.")
    _play_startup_burst()


# ─────────────────────────────────────────────────────────────
# Gesture envelope (IMU HAL) — docs/contracts/gesture-envelope.md §2
# The only code below that touches i2c.readfrom_mem/writeto_mem — same
# seam the LED side already has (_paint/clear are the only code touching
# np[i]). Register facts verified against ST's own driver source, same as
# imu_test.py/vibration_sandbox.py — see those files' headers for the
# reference. NOT host-testable (real I/O), same category
# _imu_tap_detected() below already is. Lazily constructed, not built at
# import time like `np` — this is opt-in hardware, unlike the LED strip
# which every deployment has.
# ─────────────────────────────────────────────────────────────
_IMU_WHO_AM_I_REG = 0x0F
_IMU_WHO_AM_I_EXPECTED = 0x70
_IMU_CTRL1_REG = 0x10
_IMU_CTRL1_240HZ_HIGH_PERF = 0x07
_IMU_CTRL1_POWER_DOWN = 0x00
_IMU_OUTX_L_A = 0x28
_IMU_CANDIDATE_ADDRS = (0x6A, 0x6B)

_imu_i2c = None  # lazy singleton — see _get_imu()
_imu_addr = None


def _imu_find_device(i2c):
    """Scan the bus, confirm WHO_AM_I. Returns the confirmed 7-bit address,
    or None — mirrors imu_test.py's _find_device exactly."""
    found = i2c.scan()
    for addr in _IMU_CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, _IMU_WHO_AM_I_REG, 1)[0]
        if who == _IMU_WHO_AM_I_EXPECTED:
            return addr
    return None


def _get_imu():
    """Lazily construct + confirm the IMU, caching the result. Returns
    (i2c, addr), or (None, None) if no sensor responds — callers must
    handle the "not found" case, not assume hardware is present."""
    global _imu_i2c, _imu_addr
    if _imu_i2c is None:
        i2c = I2C(IMU_I2C_ID, scl=Pin(IMU_SCL_PIN), sda=Pin(IMU_SDA_PIN), freq=400000)
        addr = _imu_find_device(i2c)
        if addr is None:
            return None, None
        i2c.writeto_mem(addr, _IMU_CTRL1_REG, bytes([_IMU_CTRL1_240HZ_HIGH_PERF]))
        _imu_i2c, _imu_addr = i2c, addr
    return _imu_i2c, _imu_addr


def _imu_read_accel_raw(i2c, addr):
    """One burst read, signed int16 LSB counts — no unit conversion here
    (see _gesture_magnitude_mg in the feature-extraction layer below),
    matching vibration_sandbox.py's _read_accel_raw exactly."""
    data = i2c.readfrom_mem(addr, _IMU_OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    return tuple(v - 65536 if v > 32767 else v for v in (x, y, z))


# ─────────────────────────────────────────────────────────────
# Gesture envelope (feature extraction) — gesture-envelope.md §3
# PURE — a raw sample buffer in, an engineered-feature dict out. Same math
# as scripts/prepare_tap_dataset.py's engineer_features(), ported from host
# Python to MicroPython (no numpy/statistics module on either side — both
# avoid it already). Host-tested with synthetic sample lists, same
# "separate the decision logic from real-time I/O" split
# _render_dispatch/_classify_wake_response already established.
# samples: list of (t_ms, x, y, z) raw int16 LSB tuples — the HAL's
# _imu_read_accel_raw() output, not the dict shape the host scripts use
# (that shape only exists because JSON round-trips through dicts; on-device
# there's no reason to pay for it).
# ─────────────────────────────────────────────────────────────
_GESTURE_CROSSING_FRAC = 0.3  # matches prepare_tap_dataset.py's
#   CROSSING_THRESHOLD_FRAC exactly — see that file for why 0.3, not
#   analyze_taps.py's stricter 0.5 (this wants to see every excursion,
#   including rocking echoes, not just plausible "real" taps)
_GESTURE_SETTLE_FRAC = 0.1  # matches prepare_tap_dataset.py's SETTLE_FRAC


def _gesture_magnitude_mg(sample):
    """0.061 mg/LSB at power-on-default full-scale (±2g) — same
    approximation imu_test.py/vibration_sandbox.py already use."""
    _, x, y, z = sample
    return math.sqrt(x * x + y * y + z * z) * 0.061


def _gesture_median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def _gesture_mean(values):
    return sum(values) / len(values)


def _gesture_stdev(values):
    """Sample standard deviation. Caller's responsibility to only call this
    with len(values) >= 2 — same contract prepare_tap_dataset.py's
    statistics.stdev() usage already has."""
    m = _gesture_mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _gesture_dominant_axis(sample):
    _, x, y, z = sample
    axis, value = "x", x
    if abs(y) > abs(value):
        axis, value = "y", y
    if abs(z) > abs(value):
        axis, value = "z", z
    return axis


def extract_gesture_features(samples):
    """PURE: raw (t_ms, x, y, z) samples → the same feature set
    prepare_tap_dataset.py validated (docs/insights.md §8-9). `samples`
    must have at least 2 entries — the caller (the capture-window logic in
    the recognizer layer) guarantees this, same as the sandbox tools always
    captured at least one sample before returning."""
    mags = [_gesture_magnitude_mg(s) for s in samples]
    baseline = _gesture_median(mags)
    deviations = [m - baseline for m in mags]

    peak_dev = max(deviations)
    peak_idx = deviations.index(peak_dev)
    peak_t = samples[peak_idx][0]
    duration_ms = samples[-1][0]

    energy = sum(d * d for d in deviations if d > 0)

    ring_down_ms = None
    settle_dev = _GESTURE_SETTLE_FRAC * peak_dev
    for i in range(peak_idx, len(samples)):
        if deviations[i] < settle_dev:
            ring_down_ms = samples[i][0] - peak_t
            break

    # peak_dev <= 0 means no real excursion at all (a perfectly flat
    # buffer — never happens with real sensor noise, but a threshold of 0
    # would otherwise register every sample as "above" it). No crossings,
    # not a divide-by-zero, just nothing happened.
    threshold = _GESTURE_CROSSING_FRAC * peak_dev
    crossing_times = []
    above = False
    for i in range(len(samples) if peak_dev > 0 else 0):
        dev = deviations[i]
        if not above and dev >= threshold:
            above = True
            crossing_times.append(samples[i][0])
        elif above and dev < threshold:
            above = False
    gaps = [crossing_times[i + 1] - crossing_times[i] for i in range(len(crossing_times) - 1)]

    return {
        "peak_deviation_mg": peak_dev,
        "ring_down_ms": ring_down_ms,
        "energy": energy,
        "duration_ms": duration_ms,
        "dominant_axis": _gesture_dominant_axis(samples[peak_idx]),
        "num_crossings": len(crossing_times),
        "spacing_mean_ms": _gesture_mean(gaps) if gaps else None,
        "spacing_stdev_ms": _gesture_stdev(gaps) if len(gaps) > 1 else None,
    }


# ─────────────────────────────────────────────────────────────
# Gesture envelope (recognizer) — gesture-envelope.md §4
# PURE — classifies WHAT physically happened (tap/flick/position/
# orientation), agnostic of current interaction state. What that means
# (an abstract GestureEvent, state-dependent) is the scrollwheel layer's
# job below, same split _classify_wake_response already draws for the
# older tap-count design. Every threshold here is a bare module global,
# same pattern _TapClassifier.advance already uses for DOUBLE_TAP_WINDOW_MS
# — not passed as a parameter, read directly, and overridable per-test via
# load_main(...) config overrides.
# ─────────────────────────────────────────────────────────────
def classify_tap_or_flick(features):
    """"tap", "flick", or None (below the trigger floor). Real-hardware
    testing found a real bug in an earlier version: treating "spacing_stdev
    unavailable" (< 3 crossings — true for ~70% of real flicks and ~25% of
    hard handling events, see FLICK_SPACING_STDEV_THRESHOLD_MS's comment)
    as automatic REJECTION silently killed almost every hard tap/flick,
    which is why shoulder taps never registered as anything at all
    (gesture-envelope.md §10). Fixed: when spacing IS computable, it's
    still the primary discriminator, unchanged. When it ISN'T,
    num_crossings is the best available single feature in that regime
    (~80%, 1 crossing leans flick, 2+ leans hard-handling) — not great,
    but confirmed via a cross-validated classifier on every available
    feature to be a real ceiling here, not a "combine more features" gap
    (gesture-envelope.md §10 has the full analysis)."""
    peak = features["peak_deviation_mg"]
    if peak < TAP_TRIGGER_THRESHOLD_MG:
        return None
    if peak >= FLICK_MAGNITUDE_THRESHOLD_MG:
        spacing = features["spacing_stdev_ms"]
        if spacing is not None:
            return "flick" if spacing >= FLICK_SPACING_STDEV_THRESHOLD_MS else None
        return "flick" if features["num_crossings"] <= 1 else None
    return "tap"


def classify_position(features):
    """"shoulder" or "base" — only meaningful if GESTURE_POSITION_ENABLED
    (insights.md §9: ~78-81% pooled even on a bottle it's tuned for, an
    optional signal, not a reliable one on its own). Returns None when the
    capability is off, same "capability flag gates the whole path" pattern
    GESTURE_FLIP_ENABLED uses for classify_orientation below."""
    if not GESTURE_POSITION_ENABLED:
        return None
    return "shoulder" if features["peak_deviation_mg"] >= POSITION_THRESHOLD_MG else "base"


def classify_orientation(sample):
    """One of ORIENTATION_MAP's state names, or "unclear" (mid-motion, or
    an axis/sign combination not in the map). A single steady-state
    (t, x, y, z) reading, NOT a captured window — different code path from
    classify_tap_or_flick/classify_position on purpose (gesture-envelope.md
    §3: orientation is steady-state, not a transient to window/classify)."""
    _, x, y, z = sample
    values = {"x": x * 0.061, "y": y * 0.061, "z": z * 0.061}
    axis = max(values, key=lambda a: abs(values[a]))
    value = values[axis]
    if abs(value) < ORIENTATION_STABLE_MG:
        return "unclear"
    sign = 1 if value > 0 else -1
    for name, map_axis, map_sign in ORIENTATION_MAP:
        if map_axis == axis and map_sign == sign:
            return name
    return "unclear"


def classify_valid_input(features):
    """V1 minimal contract (gesture-envelope.md §11) — deliberate touch
    vs. ambient handling, the ONLY distinction this path needs. energy
    alone: 98.4% across pooled tap sessions vs. pooled handling-noise
    sessions (pickup/carry/setdown/bump) — not a single-session number, and
    a much bigger margin than anything classify_tap_or_flick/
    classify_position ever reached (median tap energy ~27K vs. median
    handling-noise energy ~2.3M, nearly two orders of magnitude apart, not
    a close call). Deliberately does NOT distinguish tap from flick or
    classify position — this is the specialization gesture-envelope.md §11
    describes, not a replacement for classify_tap_or_flick, which stays
    defined and tested for when GESTURE_FLICK_ENABLED/GESTURE_POSITION_
    ENABLED come back on."""
    return features["energy"] < TAP_ENERGY_THRESHOLD


# ─────────────────────────────────────────────────────────────
# Gesture envelope (scrollwheel) — gesture-envelope.md §7
# The interaction state machine — what an abstract event MEANS, not what
# physically happened (that's the recognizer above). Same split
# _classify_wake_response already draws for the old design: "gesture A
# doesn't always mean X" happens here, not in the recognizer.
# ─────────────────────────────────────────────────────────────
class _GestureMenu:
    """The scrollwheel's own state — separate from _WakeState's
    AWAKE/ASLEEP (this is a layer on top: GESTURE_MODE is a state you can
    only be in while the display is otherwise AWAKE, per gesture-
    envelope.md §7). Same class-based pure-state-mutation style
    _WakeState/_StatusMessage already use."""

    def __init__(self, options):
        self.options = options
        self.active = False
        self.cursor = 0
        self.entered_at = None

    def wake(self, now_ms):
        """Enter GESTURE_MODE at cursor 0. Idempotent — waking while
        already active resets the cursor and the timeout, same "wake()
        also handles re-entry" pattern _WakeState.wake() uses."""
        self.active = True
        self.cursor = 0
        self.entered_at = now_ms

    def scroll(self, now_ms, direction):
        """direction: +1 or -1. No-op if not active. Wraps around the
        option list rather than clamping — a scrollwheel, not a slider.
        Refreshes the idle timeout (now_ms) — deliberately different from
        _WakeState's WAKE_MINUTES countdown, which does NOT auto-refresh
        (that's a power-budget decision, extending it needs its own
        deliberate double-tap gesture). GESTURE_MODE_TIMEOUT_MS is an idle
        timeout on an active interaction, not a power budget — a
        scrollwheel that can time out mid-browse just because the session
        ran long has no upside, same as an ATM or screensaver idle timer
        resets on activity, not on a fixed session clock."""
        if not self.active:
            return
        self.cursor = (self.cursor + direction) % len(self.options)
        self.entered_at = now_ms

    def select(self):
        """Returns the selected option's label, or None if not active.
        Exits GESTURE_MODE — one-shot, not sticky, same spirit as the old
        SECONDARY_ACTION dispatch firing once per tap."""
        if not self.active:
            return None
        selected = self.options[self.cursor]
        self.exit()
        return selected

    def exit(self):
        self.active = False
        self.entered_at = None

    def is_expired(self, now_ms):
        # Plain subtraction, not time.ticks_diff — same choice _WakeState
        # and _TapClassifier already made for comparisons over this short
        # a window (see their is_expired()/advance()).
        return (
            self.active
            and self.entered_at is not None
            and now_ms - self.entered_at >= GESTURE_MODE_TIMEOUT_MS
        )


def _classify_menu_response(menu_active, physical_gesture):
    """PURE: given whether the menu is currently active and what the
    recognizer detected this tick, decide the abstract response —
    "wake"/"select"/"scroll"/None. Mirrors _classify_wake_response's role
    for the old design exactly. Caller applies the resulting mutation via
    menu.wake()/.scroll()/.select() — this function only decides, same
    split as before."""
    if physical_gesture is None:
        return None
    if not menu_active:
        if physical_gesture in ("tap", "flick"):
            return "wake"
        return None
    if physical_gesture == "flick":
        return "select"
    if physical_gesture == "tap":
        return "scroll"
    return None


def _scroll_direction(position):
    """tap-shoulder = up/back, tap-base = down/forward — gesture-
    envelope.md §6's SCROLL(direction). Defaults to always-forward (+1)
    when GESTURE_POSITION_ENABLED is off or position wasn't classified,
    matching the design doc's stated fallback ("otherwise SCROLL fires
    with no direction" — a scrollwheel that only goes one way is still a
    scrollwheel, just a slower one)."""
    if position == "base":
        return -1
    return 1


# ─────────────────────────────────────────────────────────────
# Gesture envelope (v1 minimal contract) — gesture-envelope.md §11
# The two-phase ACK/CONFIRM state machine. Separate class from
# _GestureMenu/_WakeState above — those drive the richer scrollwheel
# design; this is the narrower, actually-shipping v1 path, built
# alongside them, not replacing them.
# ─────────────────────────────────────────────────────────────
class _TapCycleState:
    """ASLEEP -> WAKING -> SETTLING -> AWAKE, with CYCLING as a brief
    same-phase action rather than its own state (a flash+cut, not
    somewhere you can get stuck). Two-phase because classify_valid_input
    needs the full ~1200ms capture window to decide anything, which fails
    the "instant" feel a wake gesture needs on its own (§11's latency
    finding). acknowledge() marks a trigger the INSTANT it fires, before
    any verdict exists; resolve() applies the verdict once the window's
    capture completes — same class-based pure-state-mutation style
    _WakeState/_GestureMenu already use."""

    def __init__(self):
        self.awake = False  # v1 starts ASLEEP — no lights until a real tap
        #   wakes it, unlike the classic loop (which starts AWAKE)
        self.phase = "asleep"  # "asleep" | "waking" | "settling" | "awake"
        self.phase_started_at = None
        self.awake_until = None
        self.ack_pending = False

    def accepts_input(self):
        """False during WAKING/SETTLING — the debounce gesture-envelope.md
        §11 calls for, so the same physical contact that triggered WAKE
        can't also register as an immediate CYCLE."""
        return self.phase in ("asleep", "awake")

    def acknowledge(self):
        """Call the instant a trigger fires (caller already checked
        accepts_input() first) — before the capture window or any verdict
        exists. Purely a bookkeeping flag; the caller's own immediate
        ACK-flash print/render doesn't depend on this."""
        self.ack_pending = True

    def resolve(self, now_ms, valid):
        """Call once classify_valid_input's verdict on the completed
        capture is known. Returns "wake", "cycle", or None (noise, or a
        trigger that landed while WAKING/SETTLING — re-checked here since
        the capture window can outlast a phase change)."""
        self.ack_pending = False
        if not valid or not self.accepts_input():
            return None
        if not self.awake:
            self.awake = True
            self.phase = "waking"
            self.phase_started_at = now_ms
            return "wake"
        return "cycle"

    def advance(self, now_ms):
        """Call every tick — advances WAKING->SETTLING->AWAKE on their own
        timers, and AWAKE->ASLEEP on AWAKE_MINUTES timeout. Returns the
        phase just entered, or None if nothing changed this tick. Plain
        subtraction, not time.ticks_diff — same choice _WakeState/
        _TapClassifier/_GestureMenu already made for windows this short."""
        if self.phase == "waking" and now_ms - self.phase_started_at >= WAKE_JOLT_MS:
            self.phase = "settling"
            self.phase_started_at = now_ms
            return "settling"
        if self.phase == "settling" and now_ms - self.phase_started_at >= WAKE_SETTLE_MS:
            self.phase = "awake"
            self.awake_until = now_ms + AWAKE_MINUTES * 60_000
            return "awake"
        if self.phase == "awake" and self.awake_until is not None and now_ms >= self.awake_until:
            self.awake = False
            self.phase = "asleep"
            self.awake_until = None
            return "asleep"
        return None


_GESTURE_TRIGGER_BUFFER_LEN = 8  # rolling context for the trigger's cheap
#   "local baseline" — small and cheap, NOT the same thing as
#   extract_gesture_features()'s own median-of-the-whole-capture baseline
_GESTURE_WINDOW_MS = 1200  # fixed capture duration once triggered — see
#   _capture_gesture_window's docstring for the honest simplification this is

GESTURE_POLL_MS = getattr(config, "GESTURE_POLL_MS", 4)
#   ⚠ The trigger MUST poll faster than FRAME_MS. Every validated recognizer
#   number (95-98%, insights.md §8-9) was measured at 4ms/240Hz, and
#   gesture_sandbox.py's header records that polling at FRAME_MS (16ms)
#   instead was "a real cause of missed taps, not a hardware limit."
#   _run_interactive_loop therefore ticks at THIS rate and time-gates its
#   render at FRAME_MS — one more elapsed-gated task in the same cooperative
#   super-loop, not a second loop.

I2C_ERROR_PRINT_INTERVAL_MS = 1000


def _safe_read_accel(i2c, addr, now_ms, last_error_print):
    """Returns (raw_xyz_or_None, updated last_error_print). A jostled
    connection — plausible in a device whose input method is being tapped —
    raises OSError mid-read; skip that one sample rather than taking the
    whole display down. Ported from gesture_sandbox.py, where this was
    found the hard way (insights.md §10). Diagnostic throttled so a truly
    dead sensor can't flood the console at the poll rate."""
    try:
        return _imu_read_accel_raw(i2c, addr), last_error_print
    except OSError as e:
        if time.ticks_diff(now_ms, last_error_print) >= I2C_ERROR_PRINT_INTERVAL_MS:
            print(f"  ⚠ IMU read failed ({e}) — skipping sample; check wiring if this repeats")
            last_error_print = now_ms
        return None, last_error_print


def _tap_strength(dev_mg):
    """0..1, how hard the triggering contact read AT THE MOMENT OF CONTACT.
    Deliberately uses `dev` (deviation from the rolling baseline) rather
    than `energy`: energy is the accurate signal but isn't known until the
    capture window closes ~1.2s later, and the ACK has to render NOW. See
    gesture-envelope.md §11."""
    span = STRENGTH_MAX_DEV_MG - STRENGTH_MIN_DEV_MG
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (dev_mg - STRENGTH_MIN_DEV_MG) / span))


def _ack_flick(phase_ms, peak_mult, shelf_mult, ack_ms):
    """Rise to peak, then settle onto the "continental shelf" — a dim but
    NON-ZERO hold, not black. Real-hardware finding: dropping to black made
    ACK and CONFIRM read as two disconnected blips with a stall between
    them instead of one continuous gesture (gesture-envelope.md §11)."""
    half = ack_ms / 2
    if phase_ms < half:
        return (phase_ms / half) * peak_mult
    if phase_ms < ack_ms:
        return peak_mult + (shelf_mult - peak_mult) * ((phase_ms - half) / half)
    return shelf_mult


def _confirm_jolt_mult(phase_ms, start_mult):
    """Rises FROM the shelf (not from black) to WAKE_JOLT_BRIGHTNESS_MULT,
    then decays all the way to 0 — the shelf meant "still deciding", so
    decaying past it means "decided, done". Same rise:decay ratio as the
    boot burst, scaled to WAKE_JOLT_MS."""
    rise_ms = WAKE_JOLT_MS * (STARTUP_BURST_MS / (STARTUP_BURST_MS + STARTUP_FADE_MS))
    decay_ms = WAKE_JOLT_MS - rise_ms
    if phase_ms < rise_ms:
        return start_mult + (phase_ms / rise_ms) * (WAKE_JOLT_BRIGHTNESS_MULT - start_mult)
    decay_elapsed = phase_ms - rise_ms
    if decay_elapsed >= decay_ms:
        return 0.0
    return WAKE_JOLT_BRIGHTNESS_MULT * (1.0 - decay_elapsed / decay_ms)


def _capture_gesture_window(i2c, addr, start_ms):
    """Real hardware I/O — NOT host-testable, same category
    _imu_read_accel_raw already is. Fixed-duration capture, not adaptive
    settling-detection like the sandbox tools' human-gated stop-on-Enter —
    a real simplification worth naming: every validated recognizer
    threshold (insights.md §8-9) was tuned against sandbox captures that
    could run longer when a gesture needed it. Revisit if recognizer
    accuracy here doesn't match the sandbox numbers."""
    samples = []
    while True:
        now = time.ticks_ms()
        elapsed = now - start_ms
        samples.append((elapsed,) + _imu_read_accel_raw(i2c, addr))
        if elapsed >= _GESTURE_WINDOW_MS:
            break
        time.sleep_ms(4)  # matches vibration_sandbox.py's SAMPLE_INTERVAL_MS
    return samples


def _run_gesture_debug_loop():
    """Terminal-only validation of the gesture envelope
    (docs/contracts/gesture-envelope.md §7) — prints state transitions
    instead of touching LEDs, so the scrollwheel mechanism can be exercised
    over `make screen` before any real LED wiring exists for it. Gated by
    GESTURE_DEBUG_ENABLED, not WAKE_INTERACTION_ENABLED — a different,
    newer subsystem, deliberately isolated from the existing tested loop.

    Trigger design, honestly simplified for this first draft: a rolling
    buffer of recent magnitudes gives a cheap "local baseline" to compare
    the newest sample against at FRAME_MS cadence. Real handling motion
    crosses this too (insights.md §9's handling_test.py findings) — that's
    expected, the recognizer layer above (not this trigger) is what
    actually tells a gesture from noise. On trigger, captures a fixed
    _GESTURE_WINDOW_MS window at the sandbox tools' proven 240Hz rate —
    this blocks the loop for ~1.2s, the same accepted-tradeoff category
    the boot burst already established (a rare, bounded stall)."""
    i2c, addr = _get_imu()
    if addr is None:
        print("  ✗ No LSM6DSV16X found — check wiring (see imu_test.py)")
        return

    print("\n══ eki-bin gesture debug ═════════════════════════")
    print(f"  IMU confirmed at {hex(addr)}")
    print(f"  menu: {GESTURE_MENU_OPTIONS}")
    print(
        f"  flip: {GESTURE_FLIP_ENABLED}   position: {GESTURE_POSITION_ENABLED}"
        f"   flick: {GESTURE_FLICK_ENABLED}"
    )
    print("  tap/flick to interact — Ctrl+C to stop\n")

    menu = _GestureMenu(GESTURE_MENU_OPTIONS)
    trigger_buffer = []
    last_orientation = None

    try:
        while True:
            now_ms = time.ticks_ms()
            sample = (now_ms,) + _imu_read_accel_raw(i2c, addr)

            if GESTURE_FLIP_ENABLED:
                orientation = classify_orientation(sample)
                if orientation != last_orientation and orientation != "unclear":
                    print(f"  [ORIENTATION] {orientation}")
                    last_orientation = orientation

            mag = _gesture_magnitude_mg(sample)
            triggered = False
            if len(trigger_buffer) >= _GESTURE_TRIGGER_BUFFER_LEN:
                baseline = _gesture_median(trigger_buffer)
                triggered = abs(mag - baseline) >= TAP_TRIGGER_THRESHOLD_MG

            trigger_buffer.append(mag)
            if len(trigger_buffer) > _GESTURE_TRIGGER_BUFFER_LEN:
                trigger_buffer.pop(0)

            if triggered:
                samples = _capture_gesture_window(i2c, addr, now_ms)
                trigger_buffer = []  # the window already covers this stretch
                features = extract_gesture_features(samples)
                physical = classify_tap_or_flick(features)
                if physical == "flick" and not GESTURE_FLICK_ENABLED:
                    physical = None  # capability off — treat as noise
                if physical is not None:
                    position = classify_position(features)
                    response = _classify_menu_response(menu.active, physical)
                    now_ms = time.ticks_ms()  # stale after the blocking capture
                    if response == "wake":
                        menu.wake(now_ms)
                        print(f"  [WAKE] gesture mode active — cursor: {menu.options[menu.cursor]}")
                    elif response == "select":
                        selected = menu.select()
                        print(f"  [SELECT] {selected}")
                    elif response == "scroll":
                        direction = _scroll_direction(position)
                        menu.scroll(now_ms, direction)
                        arrow = "+" if direction > 0 else "-"
                        print(f"  [SCROLL {arrow}] cursor: {menu.options[menu.cursor]}")

            if menu.is_expired(now_ms):
                menu.exit()
                print("  [TIMEOUT] gesture mode exited")

            time.sleep_ms(FRAME_MS)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  gesture debug stopped")


# ─────────────────────────────────────────────────────────────
# LED status messages — docs/contracts/led-status-messages.md
#
# What used to live here: _imu_tap_detected (an always-False STUB),
# _TapClassifier (single-vs-double-tap disambiguation) and _WakeState.
# All three are gone — superseded by the v1 gesture contract
# (docs/contracts/gesture-envelope.md §11), which ships ONE gesture, so
# there is nothing to disambiguate, and whose _TapCycleState adds the
# WAKING/SETTLING debounce phases _WakeState lacked. The stub in
# particular was actively harmful: it made WAKE_INTERACTION_ENABLED=True
# sleep the display permanently with no way to wake it.
#
# _StatusMessage and _all_signals_hidden below are NOT superseded — the
# quiet-hours and no-data acknowledgments work exactly as designed.
# ─────────────────────────────────────────────────────────────

class _StatusMessage:
    """A brief single-LED acknowledgment (see
    docs/contracts/led-status-messages.md) — non-blocking by design: set
    once via show(), then rendered by the normal fast-tick loop until it
    expires, rather than its own blocking sleep loop (which would stall tap
    classification and schedule refresh for its whole duration)."""

    def __init__(self):
        self.color = None
        self.expires_at = None

    def show(self, now_ms, color, duration_ms):
        self.color = color
        self.expires_at = now_ms + duration_ms

    def active(self, now_ms):
        return self.expires_at is not None and now_ms < self.expires_at


# NOTE: there is deliberately no _classify_tap_response() to mirror the old
# _classify_wake_response(). The v1 state machine absorbed that job:
# _TapCycleState.resolve() already returns "wake"/"cycle"/None from
# (valid, awake), and the quiet-hours precedence that used to live in the
# classifier now sits in _run_interactive_loop's trigger branch — earlier,
# where it can skip the ~1.2s capture entirely instead of paying for it and
# then discarding the result. Two functions both deciding would be worse
# than one. Precedence still matches docs/contracts/led-status-messages.md.


def _capture_with_ack(i2c, addr, start_ms, peak_mult, shelf_mult):
    """Capture the recognizer's window while rendering the ACK on top of it.
    Real hardware I/O — not host-testable.

    The ACK *must* render from inside this loop: it is the only code running
    between "felt something" and "know what it was", and acknowledging
    before the verdict exists is the entire point of the two-phase design
    (gesture-envelope.md §11). Blocking ~1.2s is accepted — the boot burst
    set that precedent — and it reads as no stall at all, because the stall
    IS the ACK animation.

    Rise/dip animates; the shelf is written ONCE and then left alone.
    Repainting a held value every frame is exactly the low-brightness
    flicker bug this codebase has now hit four times. Both legs use the
    STATIC path deliberately: gamma crushes this low range toward black
    before it reaches the shelf's linear value, which was the real "dive
    underground to 0, then back up to a plateau" bug."""
    samples = []
    last_paint = start_ms
    shelf_written = False
    while True:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, start_ms)
        try:
            samples.append((elapsed,) + _imu_read_accel_raw(i2c, addr))
        except OSError:
            pass  # one dropped sample of ~300 is negligible; see _safe_read_accel
        if elapsed < ACK_HOLD_MS:
            if time.ticks_diff(now, last_paint) >= FRAME_MS:
                mult = _ack_flick(elapsed, peak_mult, shelf_mult, ACK_HOLD_MS)
                _write_frame([(STARTUP_COLOR, mult, "static")] * NUM_LEDS)
                last_paint = now
        elif not shelf_written:
            _write_frame([(STARTUP_COLOR, shelf_mult, "static")] * NUM_LEDS)
            shelf_written = True
        if elapsed >= _GESTURE_WINDOW_MS:
            break
        time.sleep_ms(GESTURE_POLL_MS)
    return samples


def _play_confirm_jolt(shelf_mult):
    """WAKE's response: rises from the shelf the ACK left behind, decays to
    black. Blocking ~WAKE_JOLT_MS, and deliberately so — by the time it
    returns, wall-clock time matching the WAKING phase has elapsed, so the
    caller's next tap_state.advance() finds it already due. No second timer
    to keep in sync with the animation."""
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed >= WAKE_JOLT_MS:
            break
        _write_frame([(STARTUP_COLOR, _confirm_jolt_mult(elapsed, shelf_mult))] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _play_cycle_flash():
    """CYCLE's response: flash + hard cut, deliberately simpler than WAKE's
    jolt. No crossfade — the same call CHASE's transition redesign made."""
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < CYCLE_TRANSITION_MS:
        _write_frame([(STARTUP_COLOR, 1.0, "static")] * NUM_LEDS)
        time.sleep_ms(FRAME_MS)
    clear()


def _handle_tap(i2c, addr, trigger_ms, dev_mg, tap_state, signal, signal_b,
                status_message):
    """Trigger → capture (with live ACK) → classify → CONFIRM. Returns the
    dispatched response, or None if the contact was rejected as noise.

    Quiet hours is NOT checked here — the caller short-circuits before this
    is ever reached, so a quiet-hours tap never pays the ~1.2s capture.

    Strength scales both the ACK peak and the shelf from `dev`, the only
    signal available at trigger time (`energy` isn't known until the window
    closes). §11 records the honest consequence: dev and energy correlate,
    so the brightest ACKs are slightly MORE likely to end in rejection."""
    strength = _tap_strength(dev_mg)
    peak_mult = ACK_PEAK_FLOOR + strength * (ACK_PEAK_CEIL - ACK_PEAK_FLOOR)
    shelf_mult = SHELF_FLOOR + strength * (SHELF_CEIL - SHELF_FLOOR)

    tap_state.acknowledge()
    samples = _capture_with_ack(i2c, addr, trigger_ms, peak_mult, shelf_mult)
    features = extract_gesture_features(samples)
    valid = classify_valid_input(features)
    samples = None
    gc.collect()  # ~300 tuples, roughly 8-10KB. Reclaimed at a KNOWN point
    #   rather than whenever the allocator notices: transient spikes are what
    #   grow MicroPython's split heap at the IDF heap's expense, and it never
    #   hands that back (insights.md §11).

    now_ms = time.ticks_ms()  # stale after a ~1.2s blocking capture
    resolved = tap_state.resolve(now_ms, valid)
    if resolved == "wake":
        _play_confirm_jolt(shelf_mult)
        if _all_signals_hidden(signal, signal_b):
            status_message.show(time.ticks_ms(), NO_DATA_COLOR, NO_DATA_DURATION_MS)
    elif resolved == "cycle":
        _play_cycle_flash()
    else:
        clear()  # rejected — hard cut off the shelf, "decided: no"
    return resolved


def schedule_lines(schedule_data):
    """PURE: normalize EITHER schedule shape to a list of line dicts, so no
    caller ever has to branch on which format it was handed.

    Contract: docs/contracts/schedule-json.md § Multiple lines at one
    station. A file with `lines` returns it directly. A file without one is
    a single-line station, and the document itself IS that line — that shape
    is not deprecated, and normalizing here rather than at every use site is
    what keeps every pre-existing schedule working untouched (principle #9).

    Returns at least one entry, so `lines[i % len(lines)]` is always safe.
    Each entry may carry an optional "color" — the line's NOMINAL colour,
    which is what makes a line identifiable at a glance rather than only at
    the moment you cycle to it (gesture-envelope.md §11)."""
    lines = schedule_data.get("lines")
    if lines:
        return lines
    single = {"name": schedule_data.get("station", "line")}
    for period in ("weekday", "weekend"):
        if period in schedule_data:
            single[period] = schedule_data[period]
    return [single]


def _all_signals_hidden(signal, signal_b):
    """True if every active direction's LeaveSignal is HIDDEN (no catchable
    trains) — the trigger for the wake-to-no-data acknowledgment."""
    if signal.urgency is not HIDDEN:
        return False
    if signal_b is not None and signal_b.urgency is not HIDDEN:
        return False
    return True


def _cycle_brightness():
    """Advance BRIGHTNESS to the next value in BRIGHTNESS_PRESETS, wrapping
    around — the default SECONDARY_ACTION (a single tap while AWAKE). The
    visible brightness change IS the confirmation; no separate flash needed
    (see wake-interaction.md). Mutates the module-level BRIGHTNESS global
    directly — every render path already reads it fresh each frame (it was
    never a frozen import-time constant in practice, just never mutated
    until now), so nothing else needs to change to pick this up."""
    global BRIGHTNESS
    try:
        next_index = (BRIGHTNESS_PRESETS.index(BRIGHTNESS) + 1) % len(BRIGHTNESS_PRESETS)
    except ValueError:
        next_index = 0  # current BRIGHTNESS isn't one of the presets — start over
    BRIGHTNESS = BRIGHTNESS_PRESETS[next_index]
    return BRIGHTNESS


def _run_secondary_action():
    """Dispatch whatever SECONDARY_ACTION is configured. Only
    "brightness_cycle" exists today; deliberately pluggable rather than
    hardcoded to one behaviour (see wake-interaction.md) — an unrecognised
    SECONDARY_ACTION is a silent no-op, matching this codebase's
    getattr-default tolerance elsewhere (e.g. _render_dispatch's hasattr
    guard for render_dual)."""
    if SECONDARY_ACTION == "brightness_cycle":
        _cycle_brightness()


# ─────────────────────────────────────────────────────────────
# WiFi + NTP
# [→ Rust] embassy_net + CYW43 driver / replaced entirely by DS3231 in V2
# ─────────────────────────────────────────────────────────────
def connect_wifi():
    """Connect to WiFi, animating the loading-circle spin (see
    _draw_startup_circle) while polling — replaced a blocking `sleep(1)`
    poll loop that drew nothing at all, the main piece of real engineering
    the boot ceremony needed (the animation math itself was nothing new)."""
    # Reclaim before bringing the radio up. esp_wifi allocates real buffers
    # at active(True) and raises `OSError: Wifi Out of Memory` if the heap
    # can't serve them — a failure seen for real on the XIAO ESP32-C3 once
    # main.py passed ~2300 lines. Cheap insurance at a genuine high-water
    # mark; costs nothing on the roomier Pico 2W.
    #
    # ⚠ This does NOT rescue `mpremote run main.py` (i.e. `make run`), which
    # ships the whole ~115KB source over stdin to be held in RAM AND compiled
    # there — that peak happens before this line is ever reached. Run a file
    # this size from flash instead: `make upload`, then `make screen` + Ctrl+D
    # to soft-reset. See docs/provisioning-runbook.md § 6.
    if not WIFI_SSID:
        # Reachable only with TIME_SOURCE="wifi" and no credentials set —
        # a config mistake, not a runtime failure. Say so plainly rather
        # than handing esp_wifi a None to choke on.
        print("  ✗ TIME_SOURCE='wifi' but WIFI_SSID is unset in config.py.")
        print("    Set credentials, or use TIME_SOURCE='rtc' + `make set-time`.")
        return False
    gc.collect()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("  Connecting to WiFi", end="")
    start = time.ticks_ms()
    dots_printed = 0
    while time.ticks_diff(time.ticks_ms(), start) < 20000:  # same ~20s budget
        if wlan.isconnected():                              # the old 20x sleep(1) had
            break
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _draw_startup_circle(elapsed)
        whole_seconds = elapsed // 1000
        if whole_seconds > dots_printed:
            dots_printed = whole_seconds
            print(".", end="")
        time.sleep_ms(FRAME_MS)
    print()
    if wlan.isconnected():
        print(f"  ✓ Connected  IP: {wlan.ifconfig()[0]}")
        return True
    print("  ✗ WiFi failed — check config.py")
    return False


def sync_ntp():
    try:
        ntptime.settime()
        print("  ✓ NTP sync OK")
        return True
    except Exception as e:
        print(f"  ✗ NTP failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────
def _apply_line_color(contract, line):
    """Point the contract at this line's colour, when both sides support it.

    Same capability-probe pattern _render_dispatch uses for render_dual: a
    contract that has no concept of a per-line colour (every arc/urgency
    contract — their palette means URGENCY, not identity) is simply left
    alone, as is a line that declares no colour. So this is a no-op for
    every pre-existing config rather than something they must opt out of."""
    color = line.get("color")
    if color and hasattr(contract, "set_line_color"):
        contract.set_line_color(tuple(color))


def _render_dispatch(contract, signal, signal_b):
    """Pick render() vs render_dual() based on whether signal_b is given AND
    the contract actually implements render_dual — phase-2 bidirectional
    support (ApproachContract only, see DISPLAY_DIRECTION_B). Every other
    contract, and phase-1 ApproachContract configs (DISPLAY_DIRECTION_B
    unset, signal_b is None), fall through to the ordinary single-signal path
    unaffected. Pulled out as its own pure function — no clock involved — so
    this decision is host-testable in isolation from render_for_interval's
    real-time frame loop below, which isn't (it uses actual time.ticks_ms())."""
    if signal_b is not None and hasattr(contract, "render_dual"):
        return lambda phase_ms: contract.render_dual(signal, signal_b, phase_ms)
    return lambda phase_ms: contract.render(signal, phase_ms)


def render_for_interval(contract, signal, seconds, signal_b=None):
    """Hand the signal(s) to the contract for ~`seconds`. Static contracts draw
    once and return immediately (the caller sleeps). Animated contracts get a
    frame loop, fed the **absolute** ms clock so their phase is continuous
    across intervals — no snap-back to the floor every LOOP_INTERVAL_SECS. The
    signal(s) are fixed for the interval; only the clock advances (update/
    render split).

    Safe with the huge absolute value because the envelopes do `(clock % period)`
    — the modulo runs in integer space before the divide, so no float precision is
    lost. `ticks_ms()` wraps ~every 12 days → one harmless single-frame hitch."""
    render = _render_dispatch(contract, signal, signal_b)
    if contract.frame_ms is None:
        render(0)
        return  # caller sleeps the interval
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
        render(time.ticks_ms())
        time.sleep_ms(contract.frame_ms)


def _run_classic_loop(schedule_data, led):
    """The original main loop, unchanged: schedule refresh once every
    LOOP_INTERVAL_SECS, contract renders for the interval via
    render_for_interval(). Used whenever WAKE_INTERACTION_ENABLED is False
    (the default) — every deployment without an IMU wired (e.g.
    config_friend1.py) keeps behaving exactly as it always has, byte for
    byte. See _run_interactive_loop for the wake/sleep + status-message
    version."""
    heartbeat = False
    DIVIDER = "─" * 50
    loop_count = 0

    while True:
        heartbeat = not heartbeat
        if led:
            led.value(heartbeat)
        loop_count += 1
        hb = "●" if heartbeat else "○"

        now, weekday = local_time()
        period = current_period(weekday)
        # Line 0 always: this loop has no gestures, so there is nothing to
        # cycle with. A multi-line schedule still works, it just shows the
        # first line — better than showing nothing, which is what reading
        # the top level gave once departures moved inside lines[].
        line = schedule_lines(schedule_data)[0]
        _apply_line_color(ACTIVE_CONTRACT, line)
        directions = line.get(period, {})

        print(DIVIDER)
        print(
            f"  {hb}  {fmt_time(now)} JST   {period}   {schedule_data['station']}   #{loop_count}"
        )
        print(DIVIDER)

        if not directions:
            print(
                f"  No schedule for {period!r} — run: make schedule && make upload"
            )
        else:
            for direction, departures in directions.items():
                upcoming = next_departures(departures, now)
                marker = "  ← ring" if direction == DISPLAY_DIRECTION else ""
                print(f"\n  {direction}{marker}")
                if not upcoming:
                    print("    —  no more trains today")
                    continue
                for i, until in enumerate(upcoming):
                    arrow = "→" if i == 0 else " "
                    print(
                        f"    {arrow}  {fmt_time(now + until)}   in {until:2d} min"
                    )

        # ── Drive the LED ring ───────────────────────────────────
        # One ring → one direction (no magnetometer in V1) — or two, for
        # phase-2 bidirectional ApproachContract (DISPLAY_DIRECTION_B).
        # Build the abstract signal(s), then let whichever contract is
        # active interpret them.
        signal = leave_signal(directions.get(DISPLAY_DIRECTION, []), now)
        if signal.ttls:
            leaves = ", ".join("{:.1f}".format(t) for t in signal.ttls)
            print(f"\n  ring: leave in [{leaves}] min  →  {signal.urgency.name}")
        else:
            print(f"\n  ring: {signal.urgency.name}  (no catchable trains)")

        signal_b = None
        if DISPLAY_DIRECTION_B is not None:
            signal_b = leave_signal(directions.get(DISPLAY_DIRECTION_B, []), now)
            if signal_b.ttls:
                leaves_b = ", ".join("{:.1f}".format(t) for t in signal_b.ttls)
                print(f"  ring B: leave in [{leaves_b}] min  →  {signal_b.urgency.name}")
            else:
                print(f"  ring B: {signal_b.urgency.name}  (no catchable trains)")

        # Night → dark + sleep. Otherwise the contract renders for the interval
        # (static returns at once → we sleep; animated runs its own frame loop).
        if is_quiet(now):
            print("  (quiet hours — display off)")
            clear()
            time.sleep(LOOP_INTERVAL_SECS)
        else:
            render_for_interval(ACTIVE_CONTRACT, signal, LOOP_INTERVAL_SECS, signal_b)
            if ACTIVE_CONTRACT.frame_ms is None:
                time.sleep(LOOP_INTERVAL_SECS)


def _run_interactive_loop(schedule_data, led):
    """Tap interaction + LED status messages — active when GESTURE_ENABLED
    (or the legacy WAKE_INTERACTION_ENABLED) is True. See
    docs/contracts/gesture-envelope.md §11 for the shipped contract and
    docs/contracts/led-status-messages.md for the acknowledgments.

    Structurally different from _run_classic_loop: ONE fast tick drives
    everything — schedule refresh, gesture trigger, and rendering — as
    elapsed-time-gated tasks, rather than one iteration per
    LOOP_INTERVAL_SECS. The cooperative "super-loop" the wake-interaction
    doc's concurrency section settled on: no RTOS, no threads.

    ⚠ The tick is GESTURE_POLL_MS (4ms), NOT FRAME_MS (16ms), and the
    render is a time-gated task on top of it. That asymmetry is load
    bearing: every validated recognizer number was measured at 4ms/240Hz,
    and polling the trigger at FRAME_MS is a documented cause of missed
    taps (gesture_sandbox.py's header). Rendering still happens at
    FRAME_MS — animations don't need 250fps and the strip write isn't free.

    Formerly drove _TapClassifier/_WakeState against a stubbed
    _imu_tap_detected(), which meant it had never once worked on hardware.
    It now drives the real recognizer end to end."""
    heartbeat = False
    DIVIDER = "─" * 50
    loop_count = 0

    tap_state = _TapCycleState()
    tap_state.awake = True  # boot = the first wake trigger, same rule
    tap_state.phase = "awake"  # _WakeState's constructor used to do this
    tap_state.awake_until = time.ticks_ms() + AWAKE_MINUTES * 60_000
    status_message = _StatusMessage()

    # Gestures degrade gracefully: no IMU found = the display still runs,
    # it just never receives a tap. Better than refusing to boot over a
    # peripheral, and it keeps this loop usable on an IMU-less unit.
    i2c, imu_addr = _get_imu()
    if imu_addr is None:
        print("  ⚠ No IMU found — display runs, taps won't register.")
    trigger_buffer = []
    last_error_print = time.ticks_ms()
    last_render = None

    # Which line is on show. CYCLE advances it (gesture-envelope.md §11) —
    # the station is fixed (the bin lives in one room), so the line is what
    # varies. Kept as a plain index, wrapped at use, so a schedule reload
    # with fewer lines can't leave it dangling.
    lines = schedule_lines(schedule_data)
    line_index = 0
    _apply_line_color(ACTIVE_CONTRACT, lines[0])
    if len(lines) > 1:
        print(f"  Lines: {', '.join(l.get('name', '?') for l in lines)}  (tap to cycle)")

    last_refresh = None
    now = 0
    signal = LeaveSignal([])
    signal_b = None

    while True:
        tick_now = time.ticks_ms()

        # ── slow task: schedule refresh, ~LOOP_INTERVAL_SECS ──────────
        if last_refresh is None or time.ticks_diff(tick_now, last_refresh) >= LOOP_INTERVAL_SECS * 1000:
            last_refresh = tick_now
            heartbeat = not heartbeat
            if led:
                led.value(heartbeat)
            loop_count += 1
            hb = "●" if heartbeat else "○"

            now, weekday = local_time()
            period = current_period(weekday)
            line = lines[line_index % len(lines)]
            directions = line.get(period, {})

            print(DIVIDER)
            print(
                f"  {hb}  {fmt_time(now)} JST   {period}   "
                f"{schedule_data['station']}/{line.get('name', '?')}   #{loop_count}"
            )
            print(DIVIDER)

            if not directions:
                print(
                    f"  No schedule for {period!r} — run: make schedule && make upload"
                )
            else:
                for direction, departures in directions.items():
                    upcoming = next_departures(departures, now)
                    marker = "  ← ring" if direction == DISPLAY_DIRECTION else ""
                    print(f"\n  {direction}{marker}")
                    if not upcoming:
                        print("    —  no more trains today")
                        continue
                    for i, until in enumerate(upcoming):
                        arrow = "→" if i == 0 else " "
                        print(
                            f"    {arrow}  {fmt_time(now + until)}   in {until:2d} min"
                        )

            signal = leave_signal(directions.get(DISPLAY_DIRECTION, []), now)
            if signal.ttls:
                leaves = ", ".join("{:.1f}".format(t) for t in signal.ttls)
                print(f"\n  ring: leave in [{leaves}] min  →  {signal.urgency.name}")
            else:
                print(f"\n  ring: {signal.urgency.name}  (no catchable trains)")

            signal_b = None
            if DISPLAY_DIRECTION_B is not None:
                signal_b = leave_signal(directions.get(DISPLAY_DIRECTION_B, []), now)
                if signal_b.ttls:
                    leaves_b = ", ".join("{:.1f}".format(t) for t in signal_b.ttls)
                    print(f"  ring B: leave in [{leaves_b}] min  →  {signal_b.urgency.name}")
                else:
                    print(f"  ring B: {signal_b.urgency.name}  (no catchable trains)")

        # ── fast task: gesture trigger, polled at GESTURE_POLL_MS ─────
        # This is why the loop ticks faster than it renders: the
        # recognizer's validated accuracy was measured at 4ms/240Hz, and
        # polling at FRAME_MS was documented as a real cause of missed
        # taps (gesture_sandbox.py's header). Render is time-gated below.
        quiet_now = is_quiet(now)

        phase_change = tap_state.advance(tick_now)
        if phase_change == "asleep":
            print("  [SLEEP] awake window expired")

        if imu_addr is not None and tap_state.accepts_input():
            raw, last_error_print = _safe_read_accel(
                i2c, imu_addr, tick_now, last_error_print
            )
            if raw is not None:
                mag = _gesture_magnitude_mg((tick_now,) + raw)
                baseline = None
                if len(trigger_buffer) >= _GESTURE_TRIGGER_BUFFER_LEN:
                    baseline = _gesture_median(trigger_buffer)
                trigger_buffer.append(mag)
                if len(trigger_buffer) > _GESTURE_TRIGGER_BUFFER_LEN:
                    trigger_buffer.pop(0)

                if baseline is not None and abs(mag - baseline) >= TAP_TRIGGER_THRESHOLD_MG:
                    dev = abs(mag - baseline)
                    # Quiet hours short-circuits BEFORE the ~1.2s capture —
                    # led-status-messages.md says quiet hours is checked
                    # first, and honouring that here also means quiet-hours
                    # taps cost nothing instead of stalling the loop.
                    if quiet_now:
                        status_message.show(
                            tick_now, QUIET_TAP_COLOR, QUIET_TAP_DURATION_MS
                        )
                        trigger_buffer = []
                    else:
                        response = _handle_tap(
                            i2c, imu_addr, tick_now, dev, tap_state,
                            signal, signal_b, status_message,
                        )
                        if response == "cycle" and len(lines) > 1:
                            line_index = (line_index + 1) % len(lines)
                            # Recompute NOW rather than waiting up to
                            # LOOP_INTERVAL_SECS for the slow task: a tap
                            # whose effect appears half a minute later reads
                            # as a broken tap, not a slow one.
                            last_refresh = None
                            _apply_line_color(ACTIVE_CONTRACT, lines[line_index])
                            print(f"  [LINE] {lines[line_index].get('name', '?')}")
                        trigger_buffer = []  # the window covered this stretch
                        last_render = None  # force a repaint after the jolt

        # ── render, time-gated to FRAME_MS ──────────────────────────
        if last_render is not None and time.ticks_diff(tick_now, last_render) < FRAME_MS:
            time.sleep_ms(GESTURE_POLL_MS)
            continue
        last_render = tick_now

        if status_message.active(tick_now):
            frame = [None] * NUM_LEDS
            frame[STATUS_LED_INDEX] = (status_message.color, 1.0, "static")
            _write_frame(frame)
        elif quiet_now or not tap_state.awake:
            clear()
        else:
            _render_dispatch(ACTIVE_CONTRACT, signal, signal_b)(tick_now)

        time.sleep_ms(GESTURE_POLL_MS)


def _run_startup_and_mark():
    """run_startup_sequence() + a checkpoint. Wrapped because that function
    NEVER RETURNS on WiFi failure (persistent breathe), so a checkpoint
    written after the call site would silently not happen on the very path
    where memory is most likely to be the culprit."""
    run_startup_sequence()
    _mem_checkpoint("after time source")


def main():
    print("\n══ eki-bin ═══════════════════════════════════════")
    # Baseline: everything main.py's import already cost — bytecode,
    # module globals, the NeoPixel buffer, _residual. Every later delta is
    # relative to this.
    _mem_checkpoint("after import")

    if GESTURE_DEBUG_ENABLED:
        # No WiFi/schedule/boot-ceremony needed — this validates the
        # gesture envelope in isolation, same "standalone, no dependency
        # beyond the IMU" property the sandbox tools already have. Early
        # return, deliberately bypassing everything below rather than
        # threading a flag through the existing schedule/WiFi/boot flow.
        try:
            _run_gesture_debug_loop()
        except KeyboardInterrupt:
            pass
        return

    # Config-value errors get an LED cue too. _heartbeat_pin is the known
    # offender (HEARTBEAT_PIN="LED" is a Pico-2W-only alias; on any other
    # board Pin("LED") raises ValueError) but this guards the whole class:
    # a bad config value used to crash here, BEFORE run_startup_sequence()
    # below ever runs, so nothing lit up at all. On USB you'd see the
    # traceback; on a wall adapter the unit just looked dead.
    #
    # ⚠ Not everything is catchable here: LED_PIN/NUM_LEDS are consumed at
    # IMPORT time to build `np`, so getting those wrong fails before main()
    # is entered and no LED feedback is possible by construction. Those two
    # stay a serial-console diagnosis.
    try:
        led = _heartbeat_pin(HEARTBEAT_PIN)  # None on boards with no onboard-LED alias
    except (ValueError, TypeError) as e:
        print(f"  ✗ Bad config value: HEARTBEAT_PIN={HEARTBEAT_PIN!r} ({e})")
        print("    Pico 2W accepts \"LED\"; every other board needs a GPIO number")
        print("    or bare None. See pinouts/<board>.md.")
        _run_startup_failure_forever(CONFIG_ERROR_COLOR)  # never returns

    try:
        # ⚠ ORDERING IS MEMORY-DRIVEN, NOT ARBITRARY — do not move WiFi back
        # below load_schedule(). On the ESP32-C3, esp_wifi_init() needs
        # ~40KB, and ~26KB of that must come from ONE specific SRAM region
        # (measured: it drains regions 2 and 4 to 4 and 32 bytes free while
        # leaving 111KB untouched in region 3, which can't satisfy its
        # DMA/internal capability requirements). At a bare boot that region
        # has just 26,448 bytes free against WiFi's 26,416 — **32 bytes of
        # margin**. Anything allocated before WiFi comes up competes for it.
        #
        # Parsing schedule.json first cost ~5.5KB of exactly that region and
        # made connect_wifi() raise `OSError: Wifi Out of Memory`. Bringing
        # the radio up first lets MicroPython's heap grow into whatever's
        # left over instead of the other way round.
        #
        # This buys margin; it does not create headroom. See
        # docs/insights.md §11 for the real fix (stop compiling a 115KB
        # module on-device) — this reorder is the cheap half.
        _run_startup_and_mark()  # boot ceremony + WiFi/NTP — never returns on
        #   WiFi failure (persistent red breathe instead), so everything
        #   below only ever runs after a successful connect + burst.

        try:
            schedule_data = load_schedule(SCHEDULE_FILE)
            # The parked multi-line question in concrete terms: this delta
            # IS the schedule's real cost, object graph included, rather
            # than the estimate dev-status.md currently records.
            _mem_checkpoint("after schedule load")
        except (OSError, ValueError):
            # Different failure CAUSE, different colour — see
            # docs/contracts/led-status-messages.md. A missing/corrupt
            # schedule.json used to crash here with a console print and no
            # LED indication at all; now gets the same persistent-failure
            # treatment WiFi/NTP failure already had, just its own colour.
            print("  ✗ Schedule failed to load. Reset to retry.")
            _run_startup_failure_forever(SCHEDULE_ERROR_COLOR)  # never returns

        print(
            f"  Station: {schedule_data['station']}   Ring: {DISPLAY_DIRECTION!r}\n"
            f"  Contract: {type(ACTIVE_CONTRACT).__name__}   Scheme: {COLOR_SCHEME!r}   "

            f"  N trains: {N_TRAINS} "
            f"LEDs: {NUM_LEDS} on GPIO{LED_PIN}"
        )
        print(f"  Loop interval: {LOOP_INTERVAL_SECS}s  |  Ctrl+C to stop\n")

        _mem_checkpoint("entering loop")
        _mem_report()

        if WAKE_INTERACTION_ENABLED:
            _run_interactive_loop(schedule_data, led)
        else:
            _run_classic_loop(schedule_data, led)
    except KeyboardInterrupt:
        pass
    finally:
        clear()  # leave the strip dark on exit, like led_test.py
        print("\n  cleared — bye")


# `mpremote run main.py` and the device boot both execute this as __main__, so
# the loop still starts normally. But `import main` in the REPL does NOT — which
# lets you poke a contract live while iterating, no WiFi needed:
#     import main
#     sig = main.LeaveSignal([3.0])              # a 3-min-to-leave snapshot
#     main.ACTIVE_CONTRACT.render(sig, 0)        # draw it
#     main.clear()
if __name__ == "__main__":
    main()
