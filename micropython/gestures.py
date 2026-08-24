# micropython/gestures.py — eki-bin
# The gesture envelope: IMU register access, feature extraction, the
# recognizer, and the ACK/CONFIRM LED jolt. Extracted from main.py by the
# V1.6 split (docs/v1.6-refactor.md).
#
# Full design + the hardware tuning behind every threshold:
# docs/contracts/gesture-envelope.md. The numbers here were measured on real
# hardware, not chosen — see docs/insights.md §8 for the field log.
#
# The IMU is OPTIONAL. _get_imu() returns (None, None) when no sensor
# answers OR when the pins are misconfigured, and callers must handle that:
# gestures are an enhancement, the clock is the product. A missing IMU must
# never take the display down (docs/insights.md §13).
#
# Note _StatusMessage stayed here rather than moving to status.py. It is
# physically interleaved with the gesture code and shares a comment block
# with _all_signals_hidden; splitting it would have been a rewrite, not a
# move. Worth revisiting in V1.6's final tightening step.

import gc
import math
import time

import settings

from machine import I2C, Pin

from leds import (_write_frame, clear)
from settings import (ACK_HOLD_MS, ACK_PEAK_CEIL, ACK_PEAK_FLOOR,
    AWAKE_MINUTES, BRIGHTNESS_PRESETS, CYCLE_TRANSITION_MS,
    FLICK_MAGNITUDE_THRESHOLD_MG, FLICK_SPACING_STDEV_THRESHOLD_MS,
    FRAME_MS, GESTURE_FLICK_ENABLED, GESTURE_FLIP_ENABLED,
    GESTURE_MENU_OPTIONS, GESTURE_MODE_TIMEOUT_MS, GESTURE_POLL_MS,
    GESTURE_POSITION_ENABLED, IMU_I2C_ID, IMU_SCL_PIN, IMU_SDA_PIN,
    NO_DATA_COLOR, NO_DATA_DURATION_MS, NUM_LEDS, ORIENTATION_MAP,
    ORIENTATION_STABLE_MG, POSITION_THRESHOLD_MG, SECONDARY_ACTION,
    SHELF_CEIL, SHELF_FLOOR, STARTUP_BURST_MS, STARTUP_COLOR,
    STARTUP_FADE_MS, STRENGTH_MAX_DEV_MG, STRENGTH_MIN_DEV_MG,
    TAP_ENERGY_THRESHOLD, TAP_TRIGGER_THRESHOLD_MG,
    WAKE_JOLT_BRIGHTNESS_MULT, WAKE_JOLT_MS, WAKE_SETTLE_MS)
from signals import HIDDEN



# IMU register map — verified against ST's own driver source, same
# standard imu_test.py set. Moved with the code that uses them.
_IMU_WHO_AM_I_REG = 0x0F
_IMU_WHO_AM_I_EXPECTED = 0x70
_IMU_CTRL1_REG = 0x10
_IMU_CTRL1_240HZ_HIGH_PERF = 0x07
_IMU_CTRL1_POWER_DOWN = 0x00
_IMU_OUTX_L_A = 0x28
_IMU_CANDIDATE_ADDRS = (0x6A, 0x6B)


# Lazy singletons — _get_imu() declares these `global` and READS them
# before assigning, so they must exist at module level. They were left
# behind in main.py by the V1.6 split; see tests/test_module_wiring.py.
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
        try:
            i2c = I2C(IMU_I2C_ID, scl=Pin(IMU_SCL_PIN), sda=Pin(IMU_SDA_PIN),
                      freq=400000)
        except ValueError as e:
            # RP2040/RP2350 hard-wire each I2C peripheral to a fixed pin
            # table, so a pin/ID disagreement is rejected HERE, at
            # construction, before any bus activity — meaning no rewiring
            # can fix it. It surfaces as a bare `ValueError: bad SCL pin`
            # with no hint of which value is wrong.
            #
            # This has bitten four times now. imu_test.py and rtc_test.py
            # each grew an explainer; main.py had none, so it took the
            # whole display down mid-loop over an optional sensor. Treat a
            # misconfigured IMU exactly like an absent one: say what's
            # wrong, then let the clock keep running.
            print("  ✗ IMU I2C rejected: %s" % e)
            print("    IMU_I2C_ID=%d with SDA=%d/SCL=%d is not a legal"
                  % (IMU_I2C_ID, IMU_SDA_PIN, IMU_SCL_PIN))
            print("    combination on this chip. XIAO RP2350: GP6/GP7 are")
            print("    I2C **1**, not 0. Run `make i2c-scan` for the values.")
            print("    Continuing without gestures — display is unaffected.")
            return None, None
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
    (see wake-interaction.md). Mutates settings.BRIGHTNESS — the single home
    directly — every render path already reads it fresh each frame (it was
    never a frozen import-time constant in practice, just never mutated
    until now), so nothing else needs to change to pick this up."""
    # NOT `global BRIGHTNESS` — see the settings import above.
    try:
        current = settings.BRIGHTNESS  # NOT the star-imported copy
        next_index = (BRIGHTNESS_PRESETS.index(current) + 1) % len(BRIGHTNESS_PRESETS)
    except ValueError:
        next_index = 0  # not one of the presets — start over
    settings.BRIGHTNESS = BRIGHTNESS_PRESETS[next_index]
    return settings.BRIGHTNESS


def _run_secondary_action():
    """Dispatch whatever SECONDARY_ACTION is configured. Only
    "brightness_cycle" exists today; deliberately pluggable rather than
    hardcoded to one behaviour (see wake-interaction.md) — an unrecognised
    SECONDARY_ACTION is a silent no-op, matching this codebase's
    getattr-default tolerance elsewhere (e.g. _render_dispatch's hasattr
    guard for render_dual)."""
    if SECONDARY_ACTION == "brightness_cycle":
        _cycle_brightness()


