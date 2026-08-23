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
SDA_PIN = 6  # I2C data  — SET PER BOARD, WITH I2C_ID BELOW; see that table
SCL_PIN = 7  # I2C clock — SET PER BOARD, WITH I2C_ID BELOW; see that table
#              ^^ currently: XIAO RP2350 (D4/D5). Pico 2W = 0/1 (+ ID 0),
#              XIAO ESP32-C3 = 6/7 (+ ID 0).
#
#              Two DIFFERENT failure modes, both seen on hardware — worth
#              telling apart, because only one implicates your wiring:
#                • Pico2W pins on a XIAO C3 → constructs fine, scan comes back
#                  EMPTY (ESP32 maps I2C to any pins in software; GP0/GP1 just
#                  aren't broken out). Looks exactly like a wiring fault.
#                • Wrong pin/ID pair on any RP2 board → `ValueError: bad SCL
#                  pin` at construction, BEFORE any bus activity. No wiring
#                  change can fix it; it never reaches the pins. This bit
#                  twice (2026-08-22 Pico 2W, 2026-08-22 XIAO RP2350) —
#                  hence _explain_i2c_pins() below.
I2C_ID = 1   # ⚠ SET PER BOARD TOO — this is NOT always 0, and forgetting it
#              is the single most repeated bring-up failure on this project.
#                Pico 2W        : 0   (GP0/GP1 is I2C0)
#                XIAO ESP32-C3  : 0   (ESP32 maps I2C to ANY pins in software,
#                                      so the ID genuinely doesn't matter)
#                XIAO RP2350    : 1   (its LABELED D4/SDA=GP6, D5/SCL=GP7 are
#                                      on I2C1 — see the table in
#                                      pinouts/xiao_rp2350.md)
#              On RP2040/RP2350 the peripheral is wired to a FIXED pin table
#              in silicon, so an ID that disagrees with the pins is rejected
#              outright at construction. _explain_i2c_pins() below turns that
#              rejection into an actionable message instead of a bare
#              `ValueError: bad SCL pin`.


# RP2040/RP2350 fixed I2C pin table (datasheet "GPIO functions"). Used ONLY to
# explain a construction failure — never to pick pins automatically, since
# guessing which bus the user MEANT would hide exactly the wiring mistake this
# is here to surface.
_RP2_I2C_SDA = {0: (0, 4, 8, 12, 16, 20), 1: (2, 6, 10, 14, 18, 26)}
_RP2_I2C_SCL = {0: (1, 5, 9, 13, 17, 21), 1: (3, 7, 11, 15, 19, 27)}


def _explain_i2c_pins(sda, scl, i2c_id):
    """Human-readable diagnosis for an I2C() that refused to construct.
    Returns a list of lines. RP2-specific; harmless on ESP32 (where this
    failure mode doesn't occur, because pins are software-mapped)."""
    sda_bus = next((b for b, pins in _RP2_I2C_SDA.items() if sda in pins), None)
    scl_bus = next((b for b, pins in _RP2_I2C_SCL.items() if scl in pins), None)
    out = [
        "    On RP2040/RP2350 each I2C peripheral is hard-wired to a fixed",
        "    set of pins — the ID and the pins must agree:",
        "      I2C0  SDA: GP0/4/8/12/16/20   SCL: GP1/5/9/13/17/21",
        "      I2C1  SDA: GP2/6/10/14/18/26  SCL: GP3/7/11/15/19/27",
    ]
    if sda_bus is None:
        out.append(f"    ✗ GP{sda} is not a valid I2C SDA pin on this chip at all.")
    if scl_bus is None:
        out.append(f"    ✗ GP{scl} is not a valid I2C SCL pin on this chip at all.")
    if sda_bus is not None and scl_bus is not None:
        if sda_bus != scl_bus:
            out.append(f"    ✗ GP{sda} is an I2C{sda_bus} SDA pin but GP{scl} is an")
            out.append(f"      I2C{scl_bus} SCL pin — they're on DIFFERENT buses.")
            out.append("      Pick a pair from one row of the table above.")
        elif sda_bus != i2c_id:
            out.append(f"    → GP{sda}/GP{scl} are a valid I2C{sda_bus} pair, but")
            out.append(f"      I2C_ID is set to {i2c_id}. Set I2C_ID = {sda_bus}.")
    return out

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


# Addresses this project uses that are NOT the IMU. Finding one of these
# means "a different device answered", which is a completely different
# situation from "nothing answered" — and steering someone toward the IMU's
# SA0 strap when what they actually have connected is an RTC wastes a
# debugging cycle (observed 2026-08-22).
_NOT_THE_IMU = {
    0x68: "DS3231 RTC (or an MPU6050) — see micropython/rtc_test.py",
    0x57: "AT24C32 EEPROM, commonly on DS3231 breakout modules",
}


def _find_device(i2c):
    """Scan the bus, then confirm WHO_AM_I against whichever candidate
    address responds. Returns (confirmed_addr_or_None, scanned_addrs)."""
    found = i2c.scan()
    print("  I2C scan:", [hex(a) for a in found])
    for addr in CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, WHO_AM_I_REG, 1)[0]
        print(f"  {hex(addr)}: WHO_AM_I = {hex(who)}  (expect {hex(WHO_AM_I_EXPECTED)})")
        if who == WHO_AM_I_EXPECTED:
            return addr, found
    return None, found


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
    try:
        i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
    except ValueError as e:
        # Construction rejected the pin/ID combination — this happens BEFORE
        # any bus activity, so no wiring change can fix it and the physical
        # setup is not implicated. Explain rather than re-raise.
        print(f"  ✗ Could not open I2C{I2C_ID} on SDA=GPIO{SDA_PIN}/SCL=GPIO{SCL_PIN}: {e}")
        for line in _explain_i2c_pins(SDA_PIN, SCL_PIN, I2C_ID):
            print(line)
        return

    addr, found = _find_device(i2c)
    if addr is None:
        print("  ✗ No LSM6DSV16X found.")
        # Branch on WHAT the scan saw — "nothing answered" and "something
        # else answered" have different causes and different fixes.
        # Order matters: an IMU address that ANSWERED but failed WHO_AM_I is
        # a different fault from "no IMU here", and would otherwise be
        # misreported as the latter. Seen on this hardware — `make i2c-scan`
        # found 0x6B but couldn't read its ID register, which is the
        # signature of marginal contact rather than a wrong/absent chip.
        answered_but_unconfirmed = [a for a in found if a in CANDIDATE_ADDRS]
        recognised = [a for a in found if a in _NOT_THE_IMU]
        if answered_but_unconfirmed:
            print(f"    An IMU address DID answer ({[hex(a) for a in answered_but_unconfirmed]})")
            print("    but WHO_AM_I didn't read back 0x70. The chip is on the bus;")
            print("    something about the transfer is unreliable. In order:")
            print("      1. Contact — I2C either transacts or it doesn't, so an")
            print("         intermittent register read means marginal wiring, not")
            print("         a flaky chip. Reseat, especially unsoldered headers.")
            print("      2. Power — a sagging supply can ACK an address while")
            print("         failing real transfers.")
            print("      3. Only then: is this actually an LSM6DSV16X? Another")
            print("         chip could share the address.")
        elif recognised:
            print("    The bus is HEALTHY — it just isn't the IMU on it:")
            for a in recognised:
                print(f"      {hex(a)} = {_NOT_THE_IMU[a]}")
            print("    So pins, bus ID, power and GND are all fine. Either the")
            print("    IMU simply isn't connected, or it shares this bus and")
            print("    isn't responding — a scan listing BOTH is what you want.")
        elif found:
            print(f"    Something answered ({[hex(a) for a in found]}) but nothing")
            print("    at 0x6A/0x6B. If you expect an IMU here, check its SA0 pad")
            print("    (the address-select strap: low = 0x6A, high = 0x6B).")
        else:
            print("    NOTHING answered at any address.")
            print(f"    1. Are SDA=GPIO{SDA_PIN}/SCL=GPIO{SCL_PIN} + I2C_ID={I2C_ID} right for")
            print("       THIS board? Run `make i2c-scan` — it tries every legal")
            print("       combination and tells you which one works.")
            print("    2. Then suspect wiring: 3V3 (NOT 5V — this chip isn't")
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
