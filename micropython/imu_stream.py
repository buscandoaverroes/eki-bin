# micropython/imu_stream.py — eki-bin
#
# A SENSOR SANDBOX: stream the IMU's raw accel + gyro to the Mac as fast as it
# will go, and run NOTHING else. No tap recogniser, no tilt controller, no
# render loop, no motion words.
#
# WHY THIS EXISTS. The production loop turns at 4-139 Hz, goes blind for ~2.7 s
# after every tap, and its decisions are the thing being debugged. Recording
# through it records its failures along with the truth. This records the
# SENSOR, at the sensor's rate, and everything the firmware would have decided
# can be reproduced afterwards on the Mac by replaying the stream through the
# real tap/tilt code at any simulated loop rate — including the rate we wish
# it ran at. The labels pressed while recording (scripts/imu_record.py) are
# then about what the HUMAN did, not about what the bottle answered.
#
# Run it (from the Mac, nothing written to flash):
#     make imu-record UNIT=bottle-01
#
# ⚠ Registers read back in the header, not assumed. The data-ready STATUS
# byte (0x1E) and the burst layout are from the LSM6DSV16X register map and
# are consistent with the gyro/accel values already seen on this unit; the
# header carries CTRL1..CTRL10 as read so full-scale settings can be decoded
# against the datasheet on the host rather than trusted here.
#
# Burst read from 0x1E, 16 bytes:
#   [0] STATUS_REG (bit0 XLDA accel ready, bit1 GDA gyro ready)  [1] reserved
#   [2:4] temperature   [4:10] gyro X,Y,Z   [10:16] accel X,Y,Z   (int16 LE)

import struct
import time

import gestures
import interlog

_CTRL1 = 0x10          # accel ODR / mode   (0 = high-performance in bits 6:4)
_CTRL2 = 0x11          # gyro  ODR / mode
_CTRL6 = 0x15          # gyro full scale FS_G[3:0] (+ LPF1 bandwidth in 7:4)
_STATUS = 0x1E
_BATCH = 20            # samples per printed line: ~83 ms at 240 Hz


def run(odr_hz=240):
    if odr_hz not in interlog.ODR_CODES:
        print("  ✗ odr_hz must be one of %s" % sorted(interlog.ODR_CODES))
        return
    i2c, addr = gestures._get_imu()
    if addr is None:
        print("  ✗ No IMU found — check wiring (make imu-test).")
        return

    code = interlog.ODR_CODES[odr_hz]
    i2c.writeto_mem(addr, _CTRL1, bytes([code]))
    i2c.writeto_mem(addr, _CTRL2, bytes([code]))
    fs = getattr(interlog, "STREAM_GYRO_FS", 1000)
    i2c.writeto_mem(addr, _CTRL6, bytes([interlog.GYRO_FS_CODES[fs]]))
    regs = i2c.readfrom_mem(addr, _CTRL1, 10)          # CTRL1..CTRL10, as read
    knobs = {"kind": "imu_stream", "odr_hz": odr_hz, "addr": addr,
             "gyro_fs_requested": fs}
    for i in range(10):
        knobs["CTRL%d" % (i + 1)] = regs[i]
    print(interlog.fmt_meta(0, knobs))
    print("  [imu_stream] %d Hz requested — streaming, Ctrl-C to stop" % odr_hz)

    time.sleep_ms(120)                                  # first samples after an ODR change are junk
    buf = bytearray(16)
    rows = []
    t_acc = 0                                           # us since start, wrap-safe
    t_last = time.ticks_us()
    t_batch0 = 0
    n = n_win = errors = 0
    max_gap = 0
    win_start = t_acc
    last_sample = None

    # After a good sample, leave the bus alone for 60 % of the sample period.
    # Hammering the status register in a tight loop produced ~140 failed reads
    # a second in the first hardware run (err in the `stat` record) and
    # nothing is gained: the next sample cannot exist yet.
    settle_us = int(1_000_000 / odr_hz * 0.6)

    while True:
        try:
            i2c.readfrom_mem_into(addr, _STATUS, buf)
        except OSError:
            errors += 1
            continue
        now = time.ticks_us()
        t_acc += time.ticks_diff(now, t_last)
        t_last = now
        st = buf[0]
        if not (st & 1):
            continue
        gx, gy, gz, ax, ay, az = struct.unpack_from("<hhhhhh", buf, 4)
        if rows and t_acc - (t_batch0 + rows[-1][0]) > interlog.MAX_DELTA_US:
            # A stall longer than the packed time stamp can express (65 ms):
            # close this batch and start another, so the gap is carried by the
            # new batch's own absolute start rather than being squeezed.
            print(interlog.fmt_batch_b64(t_batch0, rows))
            rows = []
        if not rows:
            t_batch0 = t_acc
        rows.append((t_acc - t_batch0, gx, gy, gz, ax, ay, az, st))
        n += 1
        n_win += 1
        if last_sample is not None and t_acc - last_sample > max_gap:
            max_gap = t_acc - last_sample
        last_sample = t_acc
        if t_acc - win_start >= 1_000_000:
            print(interlog.fmt_stat(t_acc, n, n_win * 1e6 / (t_acc - win_start),
                                    max_gap, errors))
            win_start, n_win, max_gap = t_acc, 0, 0
        if len(rows) >= _BATCH:
            print(interlog.fmt_batch_b64(t_batch0, rows))
            rows = []
        else:
            # SPIN, don't sleep. time.sleep_us() lets the port service USB and
            # the mount protocol, and on 2026-10-04 ~20 % of sample intervals
            # came back as ~26 ms instead of ~4 ms — spread evenly across the
            # batch, so not the print. A spin costs only CPU, which nothing
            # else here wants, and keeps the bus quiet just the same.
            deadline = time.ticks_add(time.ticks_us(), settle_us)
            while time.ticks_diff(deadline, time.ticks_us()) > 0:
                pass


def main():
    try:
        run(getattr(interlog, "STREAM_ODR", 240))
    except KeyboardInterrupt:
        pass
    finally:
        # Leave the sensor as the firmware expects to find it.
        try:
            i2c, addr = gestures._get_imu()
            if addr is not None:
                i2c.writeto_mem(addr, _CTRL1, bytes([0x07]))
                i2c.writeto_mem(addr, _CTRL2, bytes([0x00]))   # gyro off again
                i2c.writeto_mem(addr, _CTRL6, bytes([0x00]))   # default range again
        except Exception:
            pass
        print("  [imu_stream] stopped")


main()
