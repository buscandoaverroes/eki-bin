# micropython/imu_bench.py — eki-bin
#
# WHERE DO THE MISSING SAMPLES GO? A diagnostic, not a recorder.
#
# Round 1 (2026-10-04) ruled out the obvious: with NO output at all the loop
# still got ~23 Hz, gaps clustered at 38-46 ms, garbage collection off changed
# nothing, and printing (b64 or text) changed nothing either. Each read took
# <0.7 ms and the loop spent <0.07 ms outside it — so the poller was spinning
# at ~1.5 kHz and the sensor's data-ready flag simply was not being SEEN set.
#
# Leading hypothesis: polling itself interferes. Every poll was a 16-byte
# burst that reads the OUTPUT registers too, and with block-data-update on
# (CTRL3 = 0x44) the sensor may defer or skip updating registers that are
# being read — so the harder we poll, the fewer samples land. Round 1's tight
# loop (23 Hz) vs. the throttled stream (~100-165 Hz) fits.
#
# Round 2, four phases:
#   1 burst tight    16-byte burst every poll, no pacing      (round 1's loop)
#   2 burst paced    burst, but quiet for 85 % of a period after each sample
#   3 status tight   read ONLY the 1-byte STATUS until ready, then the data
#   4 status paced   status-only, and quiet for 85 % of a period after each sample
#
#   make imu-bench        (mounted from the Mac; nothing written to flash)

import gc
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


def _spin_us(us):
    deadline = time.ticks_add(time.ticks_us(), us)
    while time.ticks_diff(deadline, time.ticks_us()) > 0:
        pass


def phase(name, i2c, addr, status_only=False, paced=False, odr=240):
    gc.collect()
    burst = bytearray(16)
    sbuf = bytearray(1)
    dbuf = bytearray(12)
    quiet_us = int(1_000_000 / odr * 0.85)
    hist = {}
    n = polls = 0
    last = None
    t_end = time.ticks_add(time.ticks_ms(), _PHASE_S * 1000)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        polls += 1
        try:
            if status_only:
                i2c.readfrom_mem_into(addr, 0x1E, sbuf)
                ready = sbuf[0] & 1
                if ready:
                    i2c.readfrom_mem_into(addr, 0x22, dbuf)
            else:
                i2c.readfrom_mem_into(addr, 0x1E, burst)
                ready = burst[0] & 1
        except OSError:
            continue
        if not ready:
            if paced:
                _spin_us(150)
            continue
        t = time.ticks_us()
        if last is not None:
            g = time.ticks_diff(t, last) // 1000
            hist[g] = hist.get(g, 0) + 1
        last = t
        n += 1
        if paced:
            _spin_us(quiet_us)
    print("  %-14s %5.0f Hz   %6.0f polls/s   gaps ms %s"
          % (name, n / _PHASE_S, polls / _PHASE_S, sorted(hist.items())))


def main():
    i2c, addr = _setup()
    if addr is None:
        return
    print("  [imu_bench] 4 phases x %d s, 240 Hz requested — keep still or move, either works"
          % _PHASE_S)
    try:
        phase("1 burst tight", i2c, addr)
        phase("2 burst paced", i2c, addr, paced=True)
        phase("3 status tight", i2c, addr, status_only=True)
        phase("4 status paced", i2c, addr, status_only=True, paced=True)
    finally:
        i2c.writeto_mem(addr, 0x11, bytes([0x00]))
        i2c.writeto_mem(addr, 0x15, bytes([0x00]))
        print("  [imu_bench] done")


main()
