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

# Output data rate codes, shared by the accel (CTRL1) and gyro (CTRL2). 0x05 =
# 60 Hz and 0x07 = 240 Hz are confirmed in imu_test.py / gestures.py; the codes
# above 240 continue the datasheet's doubling series and are NOT yet confirmed
# on this silicon — imu_stream.py reports the achieved rate every second, so a
# wrong code shows up as a wrong number rather than as silently wrong data.
ODR_CODES = {60: 0x05, 120: 0x06, 240: 0x07, 480: 0x08, 960: 0x09}

# Gyro full scale -> FS_G code in CTRL6[3:0]. FROM MEMORY OF THE DATASHEET, NOT
# VERIFIED ON THIS SILICON: the first hardware run read CTRL6 = 0 (the default,
# believed to be +/-125 dps) and the gyro CLIPPED at the int16 limit on all
# three axes during ordinary handling, so a wider range is needed. The register
# is read back into the header, so what was actually set is on record.
GYRO_FS_CODES = {125: 0, 250: 1, 500: 2, 1000: 3, 2000: 4}
STREAM_GYRO_FS = 1000
STREAM_ODR = 240            # imu_stream.py; the host overrides it before running

ACTIVE_HZ = 50
IDLE_HZ = 5
HOLD_MS = 2000
ACTIVE_ACCEL_DELTA = 100    # raw LSB change vs the last LOGGED sample (~6 mg)
ACTIVE_GYRO_ABS = 500       # raw LSB (~4 dps at the default range)
_CHUNK_ROWS = 20
RATE_EVERY_MS = 5000


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


def fmt_batch(t0, rows):
    """A burst of raw samples from the dedicated streamer (imu_stream.py).
    rows: (dt_us, gx, gy, gz, ax, ay, az, status). `t0` is the device time of
    the first row, in us since the stream started."""
    body = ",".join("[%d,%d,%d,%d,%d,%d,%d,%d]" % tuple(r) for r in rows)
    return '%s{"k":"b","t0":%d,"d":[%s]}' % (TAG, t0, body)


# Compact batch, base64 of packed rows. Printing text cost ~8.5 ms per batch of
# 10 over the mount — a stall in which the poller misses ~2 samples, ~20 % of
# the stream. Packed rows are 15 bytes (20 base64 characters) against ~35-42
# characters of text. The time stamp is stored as the DELTA from the previous
# row (uint16, so up to 65 ms): the streamer starts a new batch rather than
# send a larger gap. The Mac expands a batch back to the readable form
# (dt from batch start) before writing the file, so nothing downstream ever
# sees base64 or deltas.
_ROW = "<HhhhhhhB"            # dt_us since previous row, gx gy gz ax ay az, status
ROW_BYTES = 15
MAX_DELTA_US = 65535


def pack_rows(rows):
    """rows: (dt_us FROM BATCH START, gx..az, status) -> packed deltas."""
    import struct
    buf = bytearray(ROW_BYTES * len(rows))
    prev = 0
    for i, r in enumerate(rows):
        delta = r[0] - prev
        if delta < 0 or delta > MAX_DELTA_US:
            raise ValueError("row gap %d us does not fit a uint16 delta" % delta)
        struct.pack_into(_ROW, buf, i * ROW_BYTES, delta, *r[1:])
        prev = r[0]
    return buf


def fmt_batch_b64(t0, rows):
    import binascii
    b64 = binascii.b2a_base64(pack_rows(rows)).strip().decode()
    return '%s{"k":"B","t0":%d,"n":%d,"b":"%s"}' % (TAG, t0, len(rows), b64)


def decode_batch_b64(b64, n):
    """Inverse of fmt_batch_b64 — HOST side. Returns the readable row list,
    dt measured from the batch start."""
    import binascii
    import struct
    raw = binascii.a2b_base64(b64)
    if len(raw) != ROW_BYTES * n:
        raise ValueError("batch is %d bytes, expected %d" % (len(raw), ROW_BYTES * n))
    out, t = [], 0
    for i in range(n):
        delta, *rest = struct.unpack_from(_ROW, raw, i * ROW_BYTES)
        t += delta
        out.append([t] + list(rest))
    return out


def fmt_stat(t_us, n, hz, max_gap_us, errors):
    return '%s{"k":"t","t":%d,"n":%d,"hz":%.1f,"max_gap_us":%d,"err":%d}' % (
        TAG, t_us, n, hz, max_gap_us, errors)


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

    def __init__(self, i2c, addr, level="full"):
        # level "rate": the loop-rate meter and events ONLY — no gyro, no
        # per-sample prints, no capture rows. It exists to answer "how much
        # of the slowness is the recorder itself?": compare its rate with
        # "full" (make interaction-log LEVEL=rate).
        self._level = level
        self._i2c = i2c
        self._addr = addr
        self._last_t = None
        self._max_gap = 0
        self._render_n = 0       # render-cost meter: see render_cost()
        self._render_sum = 0
        self._render_max = 0
        self._dec = Decimator()
        self._cap_g = []
        self._tilt_last = None
        self._rate_t = None     # loop-rate meter: see sample()
        self._rate_n = 0
        if level != "rate":
            enable_gyro(i2c, addr)

    def start(self, t, knobs):
        print(fmt_meta(t, knobs))

    def _gyro(self):
        try:
            return read_gyro_raw(self._i2c, self._addr)
        except OSError:
            return None

    def sample(self, t, a):
        # Loop-rate meter. The LOGGED rate is capped by the Decimator, so the
        # gaps between logged samples say nothing about how fast the main
        # loop actually turns — and a slow loop is a candidate cause of missed
        # taps (an impulse a few ms wide can fall between two samples).
        # Emitted every RATE_EVERY_MS as an event so it can be compared with
        # the recognizer's designed 4 ms tick.
        #
        # gap_ms is the longest gap between two calls in the window: a low
        # hz with a huge gap is the loop being BLOCKED (a motion word, a tap
        # capture), while a low hz with a small gap is the loop being SLOW.
        # They have different cures.
        self._rate_n += 1
        if self._last_t is not None and t - self._last_t > self._max_gap:
            self._max_gap = t - self._last_t
        self._last_t = t
        if self._rate_t is None:
            self._rate_t = t
        elif t - self._rate_t >= RATE_EVERY_MS:
            n = self._render_n
            self.event(t, "rate", hz=self._rate_n * 1000.0 / (t - self._rate_t),
                       gap_ms=self._max_gap, level=self._level,
                       render_n=n,
                       render_ms=(self._render_sum / n / 1000.0) if n else None,
                       render_max_ms=self._render_max / 1000.0)
            self._rate_t, self._rate_n, self._max_gap = t, 0, 0
            self._render_n = self._render_sum = self._render_max = 0
        if self._level == "rate":
            return
        g = self._gyro()
        if self._dec.keep(t, a, g):
            print(fmt_sample(t, a, g))

    def render_cost(self, us):
        """Microseconds one render pass took. Reported with the next `rate`
        event. The loop's rate is ~17 ms per iteration while lit and ~7 ms
        dark; if render is the difference, this says so directly rather than
        by inference from two rates."""
        self._render_n += 1
        self._render_sum += us
        if us > self._render_max:
            self._render_max = us

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
