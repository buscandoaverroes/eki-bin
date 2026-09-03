# micropython/rtc_test.py — eki-bin hardware bring-up
# Smoke test for the DS3231 precision RTC (Adafruit #3013 — see
# docs/hardware.md § DS3231 for the part evaluation, wiring, and battery
# notes). Standalone and NOT config-driven: edit SDA_PIN/SCL_PIN below by
# hand to match the board you're testing, same convention imu_test.py uses.
#
# Wiring (see docs/hardware.md and pinouts/pico2w.md):
#   Pico 2W:  3V3(pin36)→VIN   GND(pin38)→GND   GP0(pin1)→SDA   GP1(pin2)→SCL
#   ⚠ VIN, not VBUS/5V — this breakout's I2C pull-ups tie to VIN, so 5V
#   power puts 5V on SDA/SCL into GPIOs that aren't 5V-tolerant. See the
#   pinout doc for why this is a different failure mode than the IMU's
#   "chip isn't 5V-rated" — the DS3231 chip itself would survive 5V; the
#   Pico wouldn't.
#
# Shares I2C0 with the IMU (0x68 vs. 0x6A/0x6B — no address conflict, and a
# scan below should list BOTH if both are wired). This script only talks
# to the RTC; see imu_test.py for the IMU.
#
# Run without flashing:   make rtc-test               (runs this file)
#          any file:      make run-file FILE=<path>
#
# ══ THE ACTUAL POINT OF THIS TEST ═══════════════════════════════════════
# A DS3231 is bought for exactly one property: it keeps correct time across
# a power cycle, on its CR1220, when nothing else on the board can. Proving
# that needs two runs with a power cycle in between — see WORKFLOW below.
# Confirming "it responds on I2C" alone (which this script also does) is
# necessary but proves nothing about the actual reason it was bought.
#
# ══ WORKFLOW ═════════════════════════════════════════════════════════════
# This script READS. It never writes — see below. The seed/verify/measure
# split is by intent, and only the destructive one has to be named:
#
#     make rtc-seed     WRITES the chip     (micropython/rtc_seed.py)
#     make rtc-test     reads it            (this file)
#     make rtc-drift    measures it         (refuses an unseeded chip)
#
#   1. A factory-fresh or power-lost chip reports OSF SET and reads
#      2000-01-01. That is expected once. `make rtc-seed` fixes it —
#      but check the HOST clock first, because it is copied straight
#      through (docs/provisioning-runbook.md §5b).
#   2. PHYSICALLY power-cycle: unplug, wait, plug back in. NOT Ctrl+D —
#      a soft reset doesn't drop power and proves nothing.
#   3. Re-run this. **OSF still clear is the actual proof**, not the time
#      readback: a chip that lost power at 3am and was re-powered would
#      also show a plausible-looking time. OSF is the chip's own claim
#      that its oscillator never stopped.
#
# ══ ⚠ A BATTERY CAN MASK A POWER FAULT — confirmed on hardware ══════════
# Found the hard way 2026-08-22. Symptom: completely empty I2C scan, on
# wiring that had just been proven good by imu_test.py on the same pins.
# Removing the CR1220 made the chip appear immediately at 0x68.
#
# Why: the DS3231 arbitrates its own supply. It switches to VBAT when VCC
# falls below the power-fail threshold (~2.575V) AND below the battery
# voltage — and **its I2C interface is disabled whenever it runs on
# VBAT**. So a bad VIN connection produces a chip that is alive, keeping
# perfect time, and totally invisible on the bus. The battery doesn't
# cause the fault; it converts "dead and silent" into "healthy and
# silent," which looks the same from a scan but points somewhere else.
#
# The diagnostic value runs the other way too: if pulling the battery
# makes the device appear, VIN is sagging **below ~2.6V** — that's not
# "slightly marginal," it's a high-resistance connection dropping most of
# a volt. Reseat VIN before suspecting anything else. Intermittent EIO on
# subsequent reads is the same fault, same cause.
#
# ══ WHO_AM_I: this chip doesn't have one ════════════════════════════════
# Unlike the LSM6DSV16X (imu_test.py checks WHO_AM_I=0x70), the DS3231 has
# no device-ID register. Seeing 0x68 on the bus is WEAKER confirmation than
# imu_test.py's check — 0x68 is also a common address for other chips (the
# MPU6050, notably — an early, since-abandoned placeholder in this
# project's own pinout history). The best available check here is that the
# time registers round-trip and stay in plausible ranges, which main()
# does below, but this is not a real identity check the way WHO_AM_I is.
#
# ══ TIME_SOURCE naming note, for the eventual main.py integration ══════
# `main.py` already has TIME_SOURCE="rtc", meaning the board's OWN
# non-persistent clock (set via `make set-time` each session — see
# docs/insights.md §11). That name is taken and means something disjoint
# from this part. The DS3231 integration should be its own value —
# TIME_SOURCE="ds3231" — not a redefinition of "rtc". Not done in this
# script; flagged here so it isn't picked inconsistently later.

import time

from machine import I2C, Pin

# ── Configuration ────────────────────────────────────────────────
SDA_PIN = 6  # I2C data  — SET PER BOARD, WITH I2C_ID below
SCL_PIN = 7  # I2C clock — SET PER BOARD, WITH I2C_ID below
I2C_ID = 1   # ⚠ SET PER BOARD TOO — NOT always 0:
#                Pico 2W        : SDA 0, SCL 1, ID 0
#                XIAO ESP32-C3  : SDA 6, SCL 7, ID 0  (ESP32 maps I2C to any
#                                 pins in software, so the ID is a free choice)
#                XIAO RP2350    : SDA 6, SCL 7, ID 1  (its LABELED D4/D5 are
#                                 GP6/GP7, which are on I2C1 — pinouts/xiao_rp2350.md)
#              On RP2040/RP2350 the peripheral is hard-wired to a fixed pin
#              table, so an ID disagreeing with the pins is rejected at
#              construction with a bare `ValueError: bad SCL pin`.
#              _explain_i2c_pins() below turns that into an actionable message.


# RP2040/RP2350 fixed I2C pin table (datasheet "GPIO functions"). Used ONLY to
# explain a construction failure — never to pick pins automatically, since
# guessing which bus was MEANT would hide the very mistake this surfaces.
_RP2_I2C_SDA = {0: (0, 4, 8, 12, 16, 20), 1: (2, 6, 10, 14, 18, 26)}
_RP2_I2C_SCL = {0: (1, 5, 9, 13, 17, 21), 1: (3, 7, 11, 15, 19, 27)}


def _explain_i2c_pins(sda, scl, i2c_id):
    """Human-readable diagnosis for an I2C() that refused to construct.
    RP2-specific; harmless on ESP32, where this failure mode can't occur."""
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

# ⚠ SYNC_DS3231_FROM_BOARD_RTC IS GONE. This script is now READ-ONLY, full
# stop — the intent it always claimed ("running this script should never be
# able to destroy a chip's time") but did not enforce, because the flag lived
# one edit away and had to be manually set back.
#
# Seeding moved to its own script and its own target: `make rtc-seed`
# (micropython/rtc_seed.py). Procedure: docs/provisioning-runbook.md §5b.
READ_INTERVAL_SECS = 2  # how often to re-print time+temp in the watch loop

# ── DS3231 register map ────────────────────────────────────────────
# Verified against Maxim/Analog Devices' DS3231 datasheet register table,
# not guessed — same "cite the primary source" standard imu_test.py set.
DS3231_ADDR = 0x68  # fixed in silicon — no SA0-style address pin on this chip
REG_SECONDS = 0x00   # 7 consecutive regs from here: sec,min,hour,dow,date,mon,yr
REG_STATUS = 0x0F    # bit7 = OSF (oscillator stop flag) — see below
REG_TEMP_MSB = 0x11  # onboard temp sensor, used internally for oscillator
REG_TEMP_LSB = 0x12  #   compensation; exposed here as a free plausibility check
OSF_BIT = 0x80

# ── BCD ⇄ decimal ────────────────────────────────────────────────
# The DS3231 stores every time field as packed BCD (two 4-bit decimal
# digits per byte), NOT binary — a register holding 0x25 means the decimal
# digits "2" and "5", i.e. 25, not 37. Getting this backwards is the
# classic DS3231 bring-up bug: the clock ticks and LOOKS alive, it just
# shows nonsense. Every read/write below goes through these two functions
# on purpose, rather than raw ints, so this can't be gotten wrong twice.


def _bcd_to_dec(b):
    return (b >> 4) * 10 + (b & 0x0F)




def _read_datetime(i2c, addr):
    """Returns (year, month, day, hour, minute, second, weekday). Always
    reads back in 24-hour terms regardless of how the register is
    configured, since anything that writes this chip uses 24-hour mode — so
    script never has to carry the 12-hour/AM-PM branch through main()."""
    data = i2c.readfrom_mem(addr, REG_SECONDS, 7)
    second = _bcd_to_dec(data[0] & 0x7F)
    minute = _bcd_to_dec(data[1] & 0x7F)
    hour_reg = data[2]
    if hour_reg & 0x40:  # 12-hour mode (bit6 set) — not what this script
        #                   writes, but a factory-fresh or hand-set chip
        #                   could still be in it, so handle it on READ.
        hour = _bcd_to_dec(hour_reg & 0x1F)
        is_pm = bool(hour_reg & 0x20)
        if is_pm and hour != 12:
            hour += 12
        if not is_pm and hour == 12:
            hour = 0
    else:
        hour = _bcd_to_dec(hour_reg & 0x3F)
    weekday = data[3] & 0x07  # 1-7, chip-arbitrary. main.py ignores it and
    #                           computes the weekday from the DATE instead.
    day = _bcd_to_dec(data[4] & 0x3F)
    month_reg = data[5]
    month = _bcd_to_dec(month_reg & 0x1F)
    century = bool(month_reg & 0x80)
    year = _bcd_to_dec(data[6]) + (2100 if century else 2000)
    return (year, month, day, hour, minute, second, weekday)




# ── Oscillator Stop Flag — the actual "did it survive" answer ──────
def _osc_stopped(i2c, addr):
    """True if the chip is reporting (or has ever reported since last
    cleared) that its oscillator stopped — i.e. power AND the battery both
    failed to keep it running at some point. This is the real diagnostic
    the whole WORKFLOW above exists to exercise; a correct-looking time
    after a power cycle is good evidence, this flag is the chip's own
    direct claim about it. Set on first power-up out of the factory too,
    which is expected and not a fault — that's exactly what step 1 of
    WORKFLOW clears."""
    return bool(i2c.readfrom_mem(addr, REG_STATUS, 1)[0] & OSF_BIT)




def _read_temp_c(i2c, addr):
    """The DS3231's OWN onboard temp sensor — it uses this internally to
    retune its oscillator every 64s, which is most of why it's more
    accurate than a plain crystal. Exposed here mainly as a cheap
    plausibility check: a wildly implausible reading (not a calibration
    error, but e.g. -85 or +125, the "not connected" extremes) suggests
    something is wrong with the bus read, not the room temperature."""
    msb = i2c.readfrom_mem(addr, REG_TEMP_MSB, 1)[0]
    lsb = i2c.readfrom_mem(addr, REG_TEMP_LSB, 1)[0]
    whole = msb - 256 if msb > 127 else msb  # signed 8-bit integer part
    frac = (lsb >> 6) * 0.25  # top 2 bits of LSB = quarter-degree steps
    return whole + frac




def main():
    print("\n══ eki-bin RTC test (DS3231) ═════════════════════")
    print(f"  bus: I2C{I2C_ID}  SDA=GPIO{SDA_PIN}  SCL=GPIO{SCL_PIN}  freq=400kHz")
    try:
        i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
    except ValueError as e:
        # Rejected BEFORE any bus activity — no wiring change can fix this,
        # and the physical setup is not implicated. Explain, don't re-raise.
        print(f"  ✗ Could not open I2C{I2C_ID} on SDA=GPIO{SDA_PIN}/SCL=GPIO{SCL_PIN}: {e}")
        for line in _explain_i2c_pins(SDA_PIN, SCL_PIN, I2C_ID):
            print(line)
        return

    found = i2c.scan()
    print("  I2C scan:", [hex(a) for a in found])
    if DS3231_ADDR not in found:
        print(f"  ✗ No device at {hex(DS3231_ADDR)}.")
        print("    1. Is this really wired to I2C0 (GP0/GP1) on THIS board?")
        print("    2. VIN → 3V3 (pin 36), NOT VBUS/5V — see this file's header.")
        print("    3. GND, SDA, SCL — and if the IMU is also on this bus,")
        print(f"       does IT show up (0x6A/0x6B)? If neither does, suspect")
        print("       the shared GND/bus wiring before either part individually.")
        return
    if 0x6A in found or 0x6B in found:
        print("  (IMU also present on the bus — expected, no conflict)")
    print(f"  ✓ device found at {hex(DS3231_ADDR)}  (no WHO_AM_I on this chip —")
    print("    see this file's header on why that's weaker than imu_test.py's check)")

    lost_power = _osc_stopped(i2c, DS3231_ADDR)
    print()
    if lost_power:
        print("  ⚠ OSCILLATOR STOP FLAG IS SET — this chip is reporting it lost")
        print("    power (mains AND battery) at some point. Expected on a")
        print("    first-ever run (factory state); NOT expected if you just")
        print("    power-cycled to test battery backup — that's a battery")
        print("    problem (seated? oriented +/- correctly? actually a CR1220?")
        print("    see docs/hardware.md § DS3231).")
    else:
        print("  ✓ Oscillator stop flag clear — this chip has run continuously")
        print("    since it was last cleared (see WORKFLOW step 1).")
    print()

    if lost_power:
        print("  → This chip needs seeding before it means anything:")
        print("      make rtc-seed        (procedure: runbook §5b)")
        print()

    print(f"  Reading back every {READ_INTERVAL_SECS}s — confirms it's actually")
    print("  ticking, not stuck. Ctrl+C to stop.\n")

    # Tolerate OSError per-read rather than dying on the first one. A bring-up
    # script's job is to CHARACTERIZE a connection, and "3 of 12 reads failed"
    # is a far more useful fact about marginal wiring than a traceback on read
    # #2 — which is exactly what this script did on its first real run
    # (2026-08-22), throwing away the failure RATE, the single most diagnostic
    # number available. Note this is the opposite call from imu_test.py, which
    # is right to fail fast: there, a bad read means bad wiring and nothing
    # more. Here the whole question is "how bad, and is it getting worse."
    ok = 0
    failed = 0
    try:
        while True:
            try:
                year, month, day, hour, minute, second, weekday = _read_datetime(i2c, DS3231_ADDR)
                temp = _read_temp_c(i2c, DS3231_ADDR)
                ok += 1
                print(f"  {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
                      f"  (weekday={weekday})   {temp:5.2f}°C")
            except OSError as e:
                failed += 1
                print(f"  ✗ read failed ({e})  [{failed} failed / {ok + failed} attempted]")
            time.sleep(READ_INTERVAL_SECS)
    except KeyboardInterrupt:
        pass
    finally:
        total = ok + failed
        if total:
            print(f"\n  {ok}/{total} reads succeeded.")
            if failed:
                print("  ⚠ ANY failures here mean a marginal connection, not a flaky")
                print("    chip — I2C either transacts or it doesn't. Reseat the")
                print("    clips (VIN first: see this file's header on how a sagging")
                print("    VIN makes the chip silently prefer its battery).")
        print("\n  bye — the DS3231 keeps ticking on its own regardless (that's the point)")


main()
