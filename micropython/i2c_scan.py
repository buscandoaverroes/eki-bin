# micropython/i2c_scan.py — eki-bin hardware bring-up
# "What is actually on my I2C bus, and which pins/ID do I need to reach it?"
#
# Unlike imu_test.py / rtc_test.py, this is NOT device-specific and — on RP2
# boards — needs NO per-board constants. It finds the answer instead of being
# told it. That's the whole reason it exists: three separate bring-up sessions
# on this project were lost to a pin/ID mismatch (a stale SDA/SCL pair twice, an
# I2C_ID left at 0 while the pins were on I2C1 once), each presenting as an
# empty scan or a bare `ValueError: bad SCL pin` with no hint which knob was
# wrong. This turns that into one command.
#
# Run:  make i2c-scan
#
# ══ WHAT IT CAN AND CANNOT TELL YOU ═════════════════════════════════════
# An I2C scan yields ADDRESSES ONLY. Everything past that is inference:
#   • Addresses are ambiguous. 0x68 is the DS3231 *and* the MPU6050 (an early
#     placeholder in this project's own pinout history) — so the address alone
#     is a CANDIDATE list, never an identification.
#   • Where a chip has an ID register, this probes it and can then claim a real
#     match (the LSM6DSV16X's WHO_AM_I=0x70). The DS3231 has no such register,
#     which is exactly why rtc_test.py's header calls its 0x68 confirmation
#     weaker than imu_test.py's.
# So: "✓ confirmed" means an ID register agreed. "?" means the address is
# consistent with a part but nothing has proven it.
#
# ══ WHY RP2 IS AUTO AND ESP32 IS NOT ════════════════════════════════════
# On RP2040/RP2350 each I2C peripheral is hard-wired to a fixed, small set of
# pins, so the legal search space is finite and enumerable: 12 ordinary
# adjacent SDA/SCL pairings, plus 60 legal-but-unusual crossed ones tried
# only as a fallback. Fast, safe, and needs no input.
# On ESP32 the I2C controller maps to ANY GPIO in software. The search space is
# every pin pair, and blindly driving arbitrary GPIOs on a board that also has
# an LED strip and power rails attached is a genuinely bad idea. So ESP32 gets
# a curated candidate list (the XIAO's labeled D4/D5) plus manual override, and
# says so rather than pretending the two platforms behave alike.
#
# This does NOT replace imu_test.py / rtc_test.py. A scanner proves a chip
# ACKs its address; those prove it actually works (registers read sanely,
# values move, time advances).

import sys

from machine import I2C, Pin

# ── Optional manual override ─────────────────────────────────────
# Leave as None for auto/curated behaviour. Set to force one combination —
# useful on ESP32, or to reproduce a specific failing config.
FORCE_I2C_ID = None
FORCE_SDA = None
FORCE_SCL = None

I2C_FREQ = 400000

# ── RP2040/RP2350 fixed I2C pin table (datasheet "GPIO functions") ──
# Same table imu_test.py/rtc_test.py use to explain construction failures;
# here it's the search space itself.
_RP2_I2C_SDA = {0: (0, 4, 8, 12, 16, 20), 1: (2, 6, 10, 14, 18, 26)}
_RP2_I2C_SCL = {0: (1, 5, 9, 13, 17, 21), 1: (3, 7, 11, 15, 19, 27)}

# ESP32 pins are software-mapped, so there's no table to enumerate. These are
# the pairs THIS PROJECT actually uses, not an exhaustive probe — see the
# header for why exhaustive would be reckless here.
_ESP32_CANDIDATES = (
    (0, 6, 7),   # XIAO ESP32-C3 D4/D5 — pinouts/xiao_esp32c3.md
    (0, 8, 9),   # common ESP32 devkit default
    (0, 21, 22),  # classic ESP32 default
)

# ── Known addresses ──────────────────────────────────────────────
# (candidates, id_register, expected_value) — id_register None = no way to
# confirm from the bus alone.
_KNOWN = {
    0x68: (("DS3231 RTC", "MPU6050 IMU"), None, None),
    0x6A: (("LSM6DSV16X IMU (SA0 low)",), 0x0F, 0x70),
    0x6B: (("LSM6DSV16X IMU (SA0 high)",), 0x0F, 0x70),
    0x57: (("AT24C32 EEPROM (often on DS3231 modules)",), None, None),
    0x3C: (("SSD1306 OLED",), None, None),
    0x76: (("BME280 / BMP280",), 0xD0, None),
    0x77: (("BME280 / BMP280 (alt)",), 0xD0, None),
}


def _candidate_buses():
    """Yield (i2c_id, sda, scl, tier) to try, per platform. `tier` lets the
    caller stop early — see main()."""
    if FORCE_I2C_ID is not None and FORCE_SDA is not None and FORCE_SCL is not None:
        yield (FORCE_I2C_ID, FORCE_SDA, FORCE_SCL, 1)
        return

    platform = sys.platform
    if platform == "rp2":
        # TWO TIERS, because "every legal pairing" is 72 combinations, not the
        # dozen it looks like: the pins may legally be CROSSED (SDA=GP0 with
        # SCL=GP5 is valid), and 72 full bus scans is several seconds.
        #
        # Tier 1 — the 12 ADJACENT pairs (SCL = SDA+1). Every real-world
        # wiring uses these; they're what every board silkscreen labels as a
        # SDA/SCL pair. Covers the realistic space in well under a second.
        # Tier 2 — the crossed remainder, only reached if tier 1 found
        # nothing, so an exotic-but-legal wiring is still discoverable rather
        # than silently unsupported.
        for i2c_id in (0, 1):
            for sda in _RP2_I2C_SDA[i2c_id]:
                if sda + 1 in _RP2_I2C_SCL[i2c_id]:
                    yield (i2c_id, sda, sda + 1, 1)
        for i2c_id in (0, 1):
            for sda in _RP2_I2C_SDA[i2c_id]:
                for scl in _RP2_I2C_SCL[i2c_id]:
                    if scl != sda + 1:
                        yield (i2c_id, sda, scl, 2)
    else:
        for i2c_id, sda, scl in _ESP32_CANDIDATES:
            yield (i2c_id, sda, scl, 1)


def _describe(i2c, addr):
    """Best-effort identification. Returns a string. Deliberately reports
    ambiguity as ambiguity rather than guessing the likeliest part."""
    if addr not in _KNOWN:
        return "unknown device"
    names, id_reg, expected = _KNOWN[addr]
    if id_reg is not None:
        try:
            got = i2c.readfrom_mem(addr, id_reg, 1)[0]
        except OSError:
            return "%s?  (ID register unreadable)" % " / ".join(names)
        if expected is not None and got == expected:
            return "%s  ✓ confirmed (ID reg 0x%02X = 0x%02X)" % (names[0], id_reg, got)
        return "%s?  (ID reg 0x%02X = 0x%02X)" % (" / ".join(names), id_reg, got)
    if len(names) > 1:
        return "%s  — AMBIGUOUS, no ID register to confirm" % " / ".join(names)
    return "%s?  (no ID register to confirm)" % names[0]


def main():
    print("\n══ eki-bin I2C scan ══════════════════════════════")
    platform = sys.platform
    print("  platform: %s" % platform)

    if FORCE_I2C_ID is not None:
        print("  mode: FORCED — I2C%d SDA=GP%s SCL=GP%s"
              % (FORCE_I2C_ID, FORCE_SDA, FORCE_SCL))
    elif platform == "rp2":
        print("  mode: AUTO — trying every legal pin/ID combination")
    else:
        print("  mode: GUIDED — this platform maps I2C to any pins, so the")
        print("        search space isn't safely enumerable. Trying known")
        print("        project defaults; set FORCE_* at the top to override.")
    print()

    found_any = False
    tried = 0
    for i2c_id, sda, scl, tier in _candidate_buses():
        # Stop before the crossed-pin fallback if the ordinary adjacent
        # pairings already answered — otherwise every successful scan would
        # still pay for 60 more bus probes it doesn't need.
        if tier == 2 and found_any:
            break
        if tier == 2 and tried and not found_any:
            print("  (nothing on the 12 adjacent pairs — trying crossed pin")
            print("   combinations, which are legal but unusual…)\n")
            tried = 0  # only print that notice once
        try:
            i2c = I2C(i2c_id, scl=Pin(scl), sda=Pin(sda), freq=I2C_FREQ)
        except (ValueError, OSError):
            # Illegal combination for this chip, or pins unavailable. Expected
            # constantly in AUTO mode — not worth reporting each one.
            continue
        tried += 1
        try:
            addrs = i2c.scan()
        except OSError:
            continue
        if not addrs:
            continue

        found_any = True
        print("  I2C%d  SDA=GP%-2d  SCL=GP%-2d" % (i2c_id, sda, scl))
        for addr in addrs:
            print("    0x%02X  %s" % (addr, _describe(i2c, addr)))
        print("    → config: I2C_ID = %d, SDA_PIN = %d, SCL_PIN = %d"
              % (i2c_id, sda, scl))
        print()

    if not found_any:
        print("  ✗ No devices found on any of the %d working bus configs tried." % tried)
        print()
        print("    This rules OUT a pin/ID mismatch — every legal combination")
        print("    was tested. So the fault is electrical, not configuration:")
        print("      1. Power. Is VIN/VCC actually reaching the device?")
        print("         ⚠ A DS3231 with a battery will keep perfect time while")
        print("           staying INVISIBLE on I2C if VCC sags — its interface")
        print("           is disabled on battery. Pull the cell to check.")
        print("           (docs/hardware.md § Bring-up log — DS3231)")
        print("      2. GND. Shared between board and device?")
        print("      3. Contact. Unsoldered headers and alligator clips fail")
        print("         silently — any intermittency here is contact, not a")
        print("         flaky chip.")
    else:
        print("  Note: an address match alone is NOT an identification —")
        print("  0x68 is the DS3231 AND the MPU6050. Only '✓ confirmed'")
        print("  entries had an ID register agree. See this file's header.")


main()
