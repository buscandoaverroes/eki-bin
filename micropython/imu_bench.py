# micropython/imu_bench.py — eki-bin
#
# WHERE DO THE MISSING SAMPLES GO? A diagnostic, not a recorder.
#
# imu_stream.py asks for 240 Hz and gets 80-120. Two stalls were found and
# fixed (per-batch imports, ~82 ms; then tried sleep -> spin), but on
# 2026-10-04 ~30 % of intervals INSIDE a batch were still ~26 ms, where no
# print happens. Rather than guess again, this runs the same poll loop for
# 8 s at a time under five conditions and prints ONE summary line per phase:
#
#   1 baseline      poll + unpack + keep rows, no output at all
#   2 gc off        same, garbage collector disabled for the phase
#   3 no alloc      poll only, nothing kept (allocation-free)
#   4 print b64     baseline + print a compact batch every 20 (what the stream does)
#   5 print text    baseline + print a text batch every 20
#
# Each line: achieved Hz, the worst I2C read, the worst time spent OUTSIDE the
# read, and a histogram of sample-to-sample gaps in ms. If phase 1 already
# shows 26 ms gaps, output is not the cause; if phase 2 removes them it is GC;
# if phase 3 removes them it is allocation; if only 4/5 show them it is USB.
#
#   make imu-bench        (mounted from the Mac; nothing written to flash)

import gc
import struct
import time

import gestures
import interlog

_PHASE_S = 8


def _setup():
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU found — check wiring (make imu-test).")
        return None, None
    i2c.writeto_mem(addr, 0x10, bytes([interlog.ODR_CODES[240]]))
    i2c.writeto_mem(addr, 0x11, bytes([interlog.ODR_CODES[240]]))
    i2c.writeto_mem(addr, 0x15, bytes([interlog.GYRO_FS_CODES[1000]]))
    time.sleep_ms(150)
    return i2c, addr


def phase(name, i2c, addr, keep=True, gc_off=False, out=None):
    gc.collect()
    if gc_off:
        gc.disable()
    buf = bytearray(16)
    hist = {}
    rows = []
    n = 0
    read_max = other_max = 0
    last = None
    t_end = time.ticks_add(time.ticks_ms(), _PHASE_S * 1000)
    t_prev_end = time.ticks_us()
    try:
        while time.ticks_diff(t_end, time.ticks_ms()) > 0:
            t0 = time.ticks_us()
            gap_outside = time.ticks_diff(t0, t_prev_end)
            if gap_outside > other_max:
                other_max = gap_outside
            try:
                i2c.readfrom_mem_into(addr, 0x1E, buf)
            except OSError:
                pass
            t1 = time.ticks_us()
            t_prev_end = t1
            rd = time.ticks_diff(t1, t0)
            if rd > read_max:
                read_max = rd
            if not (buf[0] & 1):
                continue
            if last is not None:
                g = time.ticks_diff(t1, last) // 1000
                hist[g] = hist.get(g, 0) + 1
            last = t1
            n += 1
            if keep:
                v = struct.unpack_from("<hhhhhh", buf, 4)
                rows.append((0,) + v + (buf[0],))
                if len(rows) >= 20:
                    if out == "b64":
                        print(interlog.fmt_batch_b64(0, rows))
                    elif out == "text":
                        print(interlog.fmt_batch(0, rows))
                    rows = []
            t_prev_end = time.ticks_us()
    finally:
        if gc_off:
            gc.enable()
    print("  %-11s %5.0f Hz   read_max %5d us   outside_max %6d us   gaps ms %s"
          % (name, n / _PHASE_S, read_max, other_max, sorted(hist.items())))


def main():
    i2c, addr = _setup()
    if addr is None:
        return
    print("  [imu_bench] 5 phases x %d s, 240 Hz requested — keep still or move, either works"
          % _PHASE_S)
    try:
        phase("1 baseline", i2c, addr)
        phase("2 gc off", i2c, addr, gc_off=True)
        phase("3 no alloc", i2c, addr, keep=False)
        phase("4 print b64", i2c, addr, out="b64")
        phase("5 print txt", i2c, addr, out="text")
    finally:
        i2c.writeto_mem(addr, 0x11, bytes([0x00]))
        i2c.writeto_mem(addr, 0x15, bytes([0x00]))
        print("  [imu_bench] done")


main()
