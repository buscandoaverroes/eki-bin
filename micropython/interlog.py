# micropython/interlog.py — eki-bin
#
# Phase 0 of docs/imu-interaction-plan.md: record the raw truth, unfiltered,
# with the gyro on, alongside what the CURRENT tap/tilt pipeline decided. No
# behaviour change — this observes the recogniser, it does not steer it.
#
# ⚠ STREAMED, NOT STORED. Everything goes out as text lines on the USB
# console and is captured on the Mac (scripts/interaction_log.py). Nothing
# is written to the board's flash: an interrupted flash write corrupted the
# filesystem once already (insights.md §13), and a day of 50 Hz samples would
# be a great many writes.
#
# Every record line starts with the TAG below; anything else on the console is
# ordinary print() noise and the host ignores it.
#
#   {"k":"m", ...}                       meta: settings snapshot, once
#   {"k":"s","t":ms,"a":[x,y,z],"g":[x,y,z]}   one sample (raw int16 LSB)
#   {"k":"e","t":ms,"e":"name", ...}     an event: what the pipeline decided
#   {"k":"c","t0":ms,"i":n,"rows":[[dt,ax,ay,az,gx,gy,gz],...]}
#                                         the tap CAPTURE window, in chunks
#
# ⚠ WHY THE CAPTURE WINDOW IS RECORDED SEPARATELY. _handle_tap blocks ~1.2 s
# reading accel at 240 Hz. That window is exactly where a tap's signature —
# and a grab's, which continues to rotate after the impact — lives, and the
# main loop is not sampling during it. Without its gyro rows there would be a
# 1.2 s hole at every trigger, in the one place the plan needs data.
#
# ⚠ ADAPTIVE RATE. A bottle on a shelf is still almost all of the time. Logging
# it at 50 Hz for a day is ~1 GB of nothing. Idle is logged at IDLE_HZ, and
# any sign of motion switches to ACTIVE_HZ and holds there for HOLD_MS so the
# lead-in to an event is never thinned.
#
# The formatters and the Decimator are pure and host-tested. The I2C reads
# are not — same split gestures.py draws.

import time

TAG = "~L "

# LSM6DSV16X gyro. Same ODR/mode encoding as the accel's CTRL1 (0x07 = 240 Hz
# high-performance), which gestures.py already uses. ⚠ Verify on the bench
# that the gyro reads ~0 at rest and a known 90 degree turn integrates to
# about 90 before trusting units; the raw LSB are logged so the conversion
# lives on the host and can be corrected without re-recording.
_CTRL2_REG = 0x11
_GYRO_240HZ_HIGH_PERF = 0x07
_OUTX_L_G = 0x22

ACTIVE_HZ = 50
IDLE_HZ = 5
HOLD_MS = 2000
ACTIVE_ACCEL_DELTA = 100    # raw LSB change vs the last LOGGED sample (~6 mg)
ACTIVE_GYRO_ABS = 500       # raw LSB (~4 dps at the default range)
_CHUNK_ROWS = 20


# ── pure: formatting ─────────────────────────────────────────────────────
def _val(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, float):
        return "%.3f" % v
    return "%d" % v


def fmt_sample(t, a, g):
    gs = "null" if g is None else "[%d,%d,%d]" % (g[0], g[1], g[2])
    return '%s{"k":"s","t":%d,"a":[%d,%d,%d],"g":%s}' % (
        TAG, t, a[0], a[1], a[2], gs)


def fmt_event(t, name, **fields):
    parts = ['"k":"e"', '"t":%d' % t, '"e":%s' % _val(name)]
    for key in sorted(fields):
        parts.append('%s:%s' % (_val(key), _val(fields[key])))
    return TAG + "{" + ",".join(parts) + "}"


def fmt_meta(t, knobs):
    parts = ['"k":"m"', '"t":%d' % t]
    for key in sorted(knobs):
        parts.append('%s:%s' % (_val(key), _val(knobs[key])))
    return TAG + "{" + ",".join(parts) + "}"


def fmt_capture_chunks(t0, rows):
    """Yield one line per _CHUNK_ROWS rows. rows: (dt, ax,ay,az, gx,gy,gz)."""
    out = []
    n = len(rows)
    i = 0
    while i < n:
        chunk = rows[i:i + _CHUNK_ROWS]
        body = ",".join("[%d,%d,%d,%d,%d,%d,%d]" % tuple(r) for r in chunk)
        out.append('%s{"k":"c","t0":%d,"i":%d,"rows":[%s]}' % (TAG, t0, i, body))
        i += _CHUNK_ROWS
    return out


def snapshot(mod, names=None):
    """The knobs a recording depends on, so a file says what produced it."""
    if names is None:
        names = ("TAP_TRIGGER_THRESHOLD_MG", "TAP_ENERGY_THRESHOLD",
                 "GESTURE_BOOT_IGNORE_MS", "TILT_ENABLED", "TILT_EXPO",
                 "TILT_DEADZONE_DEG", "TILT_FULL_DEG", "TILT_ENGAGE_SAMPLES",
                 "TILT_STILL_MS", "TILT_G_TOLERANCE", "TILT_BASELINE_ALPHA",
                 "TILT_SMOOTH_ALPHA", "MOTION_ENABLED")
    out = {}
    for n in names:
        v = getattr(mod, n, None)
        if v is not None:
            out[n] = v
    return out


# ── pure: rate decision ──────────────────────────────────────────────────
class Decimator:
    """Decides which samples get logged: ACTIVE_HZ while anything is moving
    (and for HOLD_MS afterwards), IDLE_HZ otherwise. Compares against the last
    LOGGED sample, so slow drift still trips it rather than being averaged
    away sample by sample."""

    def __init__(self):
        self._last_t = None
        self._last_a = None
        self._active_until = 0

    def keep(self, t, a, g):
        if self._last_t is None:
            self._last_t, self._last_a = t, a
            return True
        moving = (abs(a[0] - self._last_a[0]) > ACTIVE_ACCEL_DELTA
                  or abs(a[1] - self._last_a[1]) > ACTIVE_ACCEL_DELTA
                  or abs(a[2] - self._last_a[2]) > ACTIVE_ACCEL_DELTA)
        if g is not None and not moving:
            moving = (abs(g[0]) > ACTIVE_GYRO_ABS or abs(g[1]) > ACTIVE_GYRO_ABS
                      or abs(g[2]) > ACTIVE_GYRO_ABS)
        if moving:
            self._active_until = t + HOLD_MS
        hz = ACTIVE_HZ if t < self._active_until else IDLE_HZ
        if t - self._last_t >= 1000 // hz:
            self._last_t, self._last_a = t, a
            return True
        return False


# ── hardware ─────────────────────────────────────────────────────────────
def enable_gyro(i2c, addr):
    i2c.writeto_mem(addr, _CTRL2_REG, bytes([_GYRO_240HZ_HIGH_PERF]))


def read_gyro_raw(i2c, addr):
    d = i2c.readfrom_mem(addr, _OUTX_L_G, 6)
    out = []
    for i in (0, 2, 4):
        v = d[i] | (d[i + 1] << 8)
        out.append(v - 65536 if v > 32767 else v)
    return (out[0], out[1], out[2])


class Stream:
    """The one object main.py and gestures.py talk to. Nothing else in the
    firmware knows a recording exists, and with INTERACTION_LOG off none of it
    is constructed."""

    def __init__(self, i2c, addr):
        self._i2c = i2c
        self._addr = addr
        self._dec = Decimator()
        self._cap_g = []
        self._tilt_last = None
        enable_gyro(i2c, addr)

    def start(self, t, knobs):
        print(fmt_meta(t, knobs))

    def _gyro(self):
        try:
            return read_gyro_raw(self._i2c, self._addr)
        except OSError:
            return None

    def sample(self, t, a):
        g = self._gyro()
        if self._dec.keep(t, a, g):
            print(fmt_sample(t, a, g))

    def event(self, t, name, **fields):
        print(fmt_event(t, name, **fields))

    def tilt(self, t, state, ctl):
        """Only on CHANGE — the controller reports "idle" 40 times a second."""
        key = (state, ctl.engaged)
        if key == self._tilt_last:
            return
        self._tilt_last = key
        self.event(t, "tilt", state=state, engaged=ctl.engaged,
                   deg=round(ctl.deg, 1), rejected=ctl.rejected)

    # The capture-window observer protocol — see gestures._capture_with_ack.
    def cap_sample(self, i2c, addr, elapsed):
        g = self._gyro()
        self._cap_g.append(g if g is not None else (0, 0, 0))

    def cap_done(self, start_ms, samples, features, valid):
        g = self._cap_g
        self._cap_g = []
        rows = []
        for i in range(len(samples)):
            s = samples[i]
            gg = g[i] if i < len(g) else (0, 0, 0)
            rows.append((s[0], s[1], s[2], s[3], gg[0], gg[1], gg[2]))
        for line in fmt_capture_chunks(start_ms, rows):
            print(line)
        self.event(time.ticks_ms(), "capture_end",
                   energy=features.get("energy"), valid=bool(valid),
                   rows=len(rows))
