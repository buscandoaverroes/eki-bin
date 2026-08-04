# micropython/orientation_test.py — eki-bin flip/orientation bring-up
# Live orientation monitor for the LSM6DSV16X — a DIFFERENT sensing problem
# from vibration_sandbox.py / imu_test.py's tap work: orientation is a
# steady-state gravity-vector reading (which axis points "down" right now),
# not a transient impact to capture and classify. No batch collection, no
# JSON, no classifier — this should be visually obvious in real time, not
# something to statistically analyze. Physically flip the bottle while this
# runs and watch the dominant axis / sign flip.
#
# Wired-power only (USB) — flipping a Qi-mounted jar breaks the inductive
# coupling and cuts power, so this gesture doesn't apply to a Qi build.
#
# Wiring/register facts: same as imu_test.py — see that file's header.
#
# Run:  make run-file FILE=micropython/orientation_test.py
#       (standalone bring-up script, not a Makefile target of its own —
#       same reasoning as vibration_sandbox.py: one-off investigation, not
#       a repeatable smoke test. Unlike vibration_sandbox.py it has no
#       input() calls, so plain `mpremote run` works fine here — Ctrl+C to
#       stop, exactly like led_test.py/imu_test.py.)

import time

from machine import I2C, Pin

# ── Configuration ────────────────────────────────────────────────
SDA_PIN = 0  # SET PER BOARD — see imu_test.py header
SCL_PIN = 1
I2C_ID = 0

WHO_AM_I_REG = 0x0F
WHO_AM_I_EXPECTED = 0x70
CTRL1_REG = 0x10
CTRL1_60HZ_HIGH_PERF = 0x05  # steady-state reading — 60Hz plenty, no need
# for vibration_sandbox.py's 240Hz (that was about resolving fast transients)
CTRL1_POWER_DOWN = 0x00
OUTX_L_A = 0x28
CANDIDATE_ADDRS = (0x6A, 0x6B)

SAMPLE_INTERVAL_MS = 300  # slow — this is "watch it settle," not "catch a spike"
STABLE_READING_MG = 700  # a resting axis should read close to ±1000mg (1g);
# below this, the bottle's mid-flip / on its side — print "unclear" rather
# than guess.


def _find_device(i2c):
    found = i2c.scan()
    for addr in CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, WHO_AM_I_REG, 1)[0]
        if who == WHO_AM_I_EXPECTED:
            return addr
    return None


def _read_accel_mg(i2c, addr):
    data = i2c.readfrom_mem(addr, OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    x, y, z = (v - 65536 if v > 32767 else v for v in (x, y, z))
    # 0.061 mg/LSB at power-on-default ±2g — same approximation as
    # imu_test.py, good enough to watch a sign flip, not calibrated.
    return tuple(round(v * 0.061) for v in (x, y, z))


def _classify(x, y, z):
    axis, value = max((("x", x), ("y", y), ("z", z)), key=lambda t: abs(t[1]))
    if abs(value) < STABLE_READING_MG:
        return "unclear (mid-motion / on its side)"
    sign = "+" if value > 0 else "-"
    return f"axis {axis}{sign}  (dominant, {value:+d}mg)"


def main():
    print("\n══ eki-bin orientation test (LSM6DSV16X) ════════════")
    i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
    addr = _find_device(i2c)
    if addr is None:
        print("  ✗ No LSM6DSV16X found — run imu_test.py first to debug wiring")
        return
    i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_60HZ_HIGH_PERF]))
    print(f"  ✓ LSM6DSV16X at {hex(addr)}")
    print("  Sitting still, note the reading — then flip the bottle and watch")
    print("  which axis/sign changes. That's your orientation-detection axis.")
    print("  Ctrl+C to stop\n")

    try:
        while True:
            x, y, z = _read_accel_mg(i2c, addr)
            print(f"  X={x:6d}mg  Y={y:6d}mg  Z={z:6d}mg   →  {_classify(x, y, z)}")
            time.sleep_ms(SAMPLE_INTERVAL_MS)
    except KeyboardInterrupt:
        pass
    finally:
        i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_POWER_DOWN]))
        print("\n  powered down — bye")


main()
