# micropython/imu_test.py — eki-bin hardware bring-up
# Smoke test for the LSM6DSV16X 6-axis IMU (Akizuki AE-LSM6DSV16X breakout —
# see docs/hardware.md for parts/links). Standalone and NOT config-driven:
# edit SDA_PIN/SCL_PIN below by hand to match the board you're testing.
# (One-off bring-up script, deliberately separate from main.py's config
# pipeline and from the wake-interaction layer's _imu_tap_detected() —
# this proves the chip talks over I2C and reports sane values; it doesn't
# do tap classification itself.)
#
# Register facts below are verified against ST's own driver source
# (github.com/STMicroelectronics/lsm6dsv16x-pid/blob/master/lsm6dsv16x_reg.h),
# not guessed — see docs/hardware.md's IMU bring-up entry for the full
# reference list.
#
# Wiring (see docs/hardware.md and pinouts/<board>.md):
#   Pico 2W:  3V3(pin36)→VCC   GND→GND   GP0(pin1)→SDA   GP1(pin2)→SCL
#   XIAO C3:  3V3→VCC          GND→GND   D4→SDA           D5→SCL
#
# Run without flashing:   make imu-test              (runs this file)
#          any file:      make run-file FILE=<path>

import time

from machine import I2C, Pin

# ── Configuration ────────────────────────────────────────────────
SDA_PIN = 6  # I2C data  — SET PER BOARD (Pico 2W=0/GP0, XIAO C3=6/D4); see header
SCL_PIN = 7  # I2C clock — SET PER BOARD (Pico 2W=1/GP1, XIAO C3=7/D5); see header
#              ^^ currently set for the XIAO ESP32-C3. Swap back to 0/1 for the
#              Pico 2W. An empty I2C scan is the symptom of forgetting this —
#              the pins printed at startup are the first thing to check, since
#              the XIAO doesn't even break out GPIO0/GPIO1 (its D0 is GPIO2).
I2C_ID = 0   # hardware I2C peripheral index. Pico 2W: GP0/GP1 IS I2C0 — this
#              pin pair is fixed by the RP2350's silicon, not arbitrary.
#              XIAO C3 (ESP32): I2C pins are software-mapped, so ID 0 works
#              with any GPIO pair — only SDA_PIN/SCL_PIN need to change.

# ── LSM6DSV16X register map (only what this script needs) ─────────
WHO_AM_I_REG = 0x0F
WHO_AM_I_EXPECTED = 0x70
CTRL1_REG = 0x10             # accelerometer ODR (bits 0-3) + operating mode (bits 4-6)
CTRL1_60HZ_HIGH_PERF = 0x05  # ODR_AT_60Hz (0x5) | HIGH_PERFORMANCE_MD (0x0 << 4)
CTRL1_POWER_DOWN = 0x00      # ODR_OFF
OUTX_L_A = 0x28              # 6 consecutive bytes from here: X,Y,Z, low+high each

# The breakout brings SA0 (address-select) out as a solder pad — Akizuki's
# product page doesn't state its default strap, so this SCANS rather than
# assumes. Both are valid factory addresses for this chip:
#   0x6A — SA0/SDO tied low      0x6B — SA0/SDO tied high
CANDIDATE_ADDRS = (0x6A, 0x6B)

# Sensitivity at the power-on-default full-scale (±2g): 0.061 mg/LSB —
# standard across the whole ST LSM6DS family. APPROXIMATE: this script never
# writes FS_XL, it trusts the power-on default — good enough to watch taps
# and orientation move the numbers, not a calibrated reading.
MG_PER_LSB_AT_2G = 0.061


def _find_device(i2c):
    """Scan the bus, then confirm WHO_AM_I against whichever candidate
    address responds. Returns the confirmed 7-bit address, or None."""
    found = i2c.scan()
    print("  I2C scan:", [hex(a) for a in found])
    for addr in CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, WHO_AM_I_REG, 1)[0]
        print(f"  {hex(addr)}: WHO_AM_I = {hex(who)}  (expect {hex(WHO_AM_I_EXPECTED)})")
        if who == WHO_AM_I_EXPECTED:
            return addr
    return None


def _read_accel_mg(i2c, addr):
    """One burst read of all 6 accelerometer output bytes, converted to
    signed milli-g (approximate — see MG_PER_LSB_AT_2G's caveat above)."""
    data = i2c.readfrom_mem(addr, OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    # Two's-complement sign-extend by hand — not every MicroPython port's
    # int.from_bytes takes a signed= kwarg, so don't rely on one.
    x, y, z = (v - 65536 if v > 32767 else v for v in (x, y, z))
    return tuple(round(v * MG_PER_LSB_AT_2G) for v in (x, y, z))


def main():
    print("\n══ eki-bin IMU test (LSM6DSV16X) ════════════════")
    # Echo the bus config before using it. This script is deliberately not
    # config-driven (per-board constants, edited by hand), which means a
    # board swap CAN silently leave the wrong pins in place — and the
    # symptom, an empty scan, looks exactly like a wiring fault. Printing
    # them makes the two cases distinguishable at a glance. Same footgun
    # led_test.py's DATA_PIN hit during the v1.2 board-portability pass.
    print(f"  bus: I2C{I2C_ID}  SDA=GPIO{SDA_PIN}  SCL=GPIO{SCL_PIN}  freq=400kHz")
    i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)

    addr = _find_device(i2c)
    if addr is None:
        print("  ✗ No LSM6DSV16X found.")
        print(f"    1. Are SDA=GPIO{SDA_PIN}/SCL=GPIO{SCL_PIN} right for THIS board?")
        print("       Pico 2W = 0/1, XIAO ESP32-C3 = 6/7 (see pinouts/<board>.md).")
        print("       An EMPTY scan above usually means wrong pins, not bad solder —")
        print("       the XIAO doesn't even expose GPIO0/GPIO1.")
        print("    2. If the scan listed addresses but none matched, it's on the bus")
        print("       at an unexpected address — check the SA0 pad.")
        print("    3. Only then suspect wiring: 3V3 (NOT 5V — this chip isn't")
        print("       5V-tolerant), GND, SDA, SCL.")
        return
    print(f"  ✓ LSM6DSV16X confirmed at {hex(addr)}")

    i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_60HZ_HIGH_PERF]))
    print("  ✓ Accelerometer enabled — 60Hz, high-performance mode")
    print("  Move/tap the sensor — Ctrl+C to stop\n")

    try:
        while True:
            x, y, z = _read_accel_mg(i2c, addr)
            print(f"  X={x:6d}mg  Y={y:6d}mg  Z={z:6d}mg")
            time.sleep_ms(200)
    except KeyboardInterrupt:
        pass
    finally:
        i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_POWER_DOWN]))
        print("\n  powered down — bye")


main()
