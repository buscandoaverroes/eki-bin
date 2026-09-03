# micropython/rtc_seed.py — eki-bin provisioning
# WRITES the DS3231. The only script in this project that does.
#
# Run:  make rtc-seed        (full procedure: docs/provisioning-runbook.md §5b)
#
# ══ WHY THIS IS ITS OWN SCRIPT ══════════════════════════════════════════
# Seeding, verifying and measuring are three different intents, and they
# used to share two scripts and a hand-edited flag: rtc_test.py carried
# SYNC_DS3231_FROM_BOARD_RTC, which you set True, ran, and had to remember
# to set back. Forgetting meant every later run silently overwrote the
# chip's kept time — destroying precisely what the DS3231 exists to provide,
# and invalidating any drift measurement in progress.
#
# So the split is now by intent, and the destructive one is the only one
# that has to be asked for by name:
#
#     make rtc-seed     WRITES the chip          (this file)
#     make rtc-test     reads it, never writes
#     make rtc-drift    measures it, never writes; refuses an unseeded chip
#
# ══ ⚠ THE HOST CLOCK IS COPIED STRAIGHT THROUGH ═════════════════════════
#     host clock → `mpremote rtc --set` → board RTC → HERE → DS3231
# Nothing in that chain checks against real time. A Mac measured +4.140 s
# off on 2026-08-24 would have made this unit 4 s wrong permanently — no
# amount of DS3231 precision recovers it. `make rtc-drift`'s first line
# reports the host's NTP offset; check it BEFORE seeding.
#
# This script guards the step it CAN see: it refuses to copy a board RTC
# that is obviously unset. It cannot tell a plausible-but-wrong clock from
# a correct one, which is why step 0 of the runbook is yours to do.

from machine import I2C, Pin, RTC

SDA_PIN = 6  # ⚠ SET PER BOARD — XIAO RP2350. Pico 2W: 0/1, ID 0.
SCL_PIN = 7
I2C_ID = 1   # ⚠ NOT 0 on this board — GP6/GP7 are I2C1 (pinouts/xiao_rp2350.md)

DS3231_ADDR = 0x68
REG_SECONDS = 0x00
REG_STATUS = 0x0F
OSF_BIT = 0x80

MIN_PLAUSIBLE_YEAR = 2024  # a board RTC below this was never set


def _dec_to_bcd(d):
    return ((d // 10) << 4) | (d % 10)


def _bcd_to_dec(b):
    return (b >> 4) * 10 + (b & 0x0F)


def _board_rtc():
    """The board's own volatile RTC, reshaped into this file's field order.

    ⚠ machine.RTC's order is NOT the obvious one — it puts WEEKDAY fourth,
    between the date and the time:

        (year, month, day, WEEKDAY, hours, minutes, seconds, subseconds)

    Unpacking it as y/mo/d/h/mi/s/wd silently shifts every time field by one
    position and writes a date that is wrong but entirely plausible-looking.
    That is not hypothetical: it happened on 2026-09-03 while this
    conversion was being inlined at the call site, writing 03:19 for 19:45.
    An earlier version of rtc_test.py centralized it here *with a comment
    saying exactly this*, and the mistake was made while deleting that
    comment. It is centralized again, for the same reason.
    """
    year, month, day, weekday, hour, minute, second, _sub = RTC().datetime()
    return (year, month, day, hour, minute, second, weekday)


def _implausible(y, mo, d, h, mi, s, wd):
    """A field-range check, whose real job is catching a MIS-ORDERED tuple.

    Any single shift of machine.RTC's fields puts a value somewhere it
    cannot belong — the 2026-09-03 bug put second=50 into weekday, and
    weekday only goes to 6. Ranges are cheap; a corrupt date that reads
    plausibly is not."""
    for name, val, lo, hi in (("month", mo, 1, 12), ("day", d, 1, 31),
                              ("hour", h, 0, 23), ("minute", mi, 0, 59),
                              ("second", s, 0, 59), ("weekday", wd, 0, 6)):
        if not lo <= val <= hi:
            return ("%s = %d is outside %d..%d — the machine.RTC tuple is "
                    "probably being unpacked in the wrong order" % (name, val, lo, hi))
    return None


def _read_back(i2c):
    d = i2c.readfrom_mem(DS3231_ADDR, REG_SECONDS, 7)
    return (2000 + _bcd_to_dec(d[6]), _bcd_to_dec(d[5] & 0x1F),
            _bcd_to_dec(d[4] & 0x3F), _bcd_to_dec(d[2] & 0x3F),
            _bcd_to_dec(d[1] & 0x7F), _bcd_to_dec(d[0] & 0x7F))


def main():
    print("\n══ eki-bin RTC seed (DS3231) ═════════════════════")
    print("  ⚠ THIS WRITES THE CHIP. Read runbook §5b first.\n")
    print("  bus: I2C%d  SDA=GPIO%d  SCL=GPIO%d" % (I2C_ID, SDA_PIN, SCL_PIN))

    try:
        i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
    except ValueError as e:
        print("  ✗ %s" % e)
        print("    I2C_ID=%d with SDA=%d/SCL=%d is not a legal combination on"
              % (I2C_ID, SDA_PIN, SCL_PIN))
        print("    this chip — rejected at construction, so rewiring won't help.")
        print("    Run `make i2c-scan` for the values to paste.")
        return

    if DS3231_ADDR not in i2c.scan():
        print("  ✗ nothing at 0x68. Run `make i2c-scan`.")
        print("    ⚠ A FITTED BATTERY HIDES A POWER FAULT: the DS3231 disables")
        print("      its I2C on VBAT, so a sagging VIN looks like an absent")
        print("      chip. If pulling the cell makes it appear, VIN is low.")
        return

    y, mo, d, h, mi, s, wd = _board_rtc()
    print("  board RTC reads: %04d-%02d-%02d %02d:%02d:%02d" % (y, mo, d, h, mi, s))

    bad = _implausible(y, mo, d, h, mi, s, wd)
    if bad:
        print("\n  ✗ REFUSING TO SEED — %s" % bad)
        print("    Writing this would produce a corrupt but plausible-LOOKING")
        print("    date on the chip, which is the hardest kind to notice.")
        return

    if y < MIN_PLAUSIBLE_YEAR:
        print("\n  ✗ REFUSING TO SEED — the board's own RTC was never set.")
        print("    Copying it would write year %d into the chip, which is" % y)
        print("    exactly the state you are trying to fix.")
        print("    Run `make set-time` first, then this again.")
        return

    i2c.writeto_mem(DS3231_ADDR, REG_SECONDS, bytes([
        _dec_to_bcd(s), _dec_to_bcd(mi),
        _dec_to_bcd(h),          # bit6 clear = 24-hour mode
        _dec_to_bcd(wd + 1),     # 1-7; we compute weekday from the DATE at
        #                          runtime, so this is written for tidiness
        #                          only — clock.py never reads it.
        _dec_to_bcd(d),
        _dec_to_bcd(mo),         # bit7 clear = century 20xx
        _dec_to_bcd(y % 100),
    ]))

    status = i2c.readfrom_mem(DS3231_ADDR, REG_STATUS, 1)[0]
    i2c.writeto_mem(DS3231_ADDR, REG_STATUS, bytes([status & ~OSF_BIT]))
    print("  ✓ written; oscillator-stop flag cleared")

    back = _read_back(i2c)
    print("  reads back:      %04d-%02d-%02d %02d:%02d:%02d" % back)
    still_set = i2c.readfrom_mem(DS3231_ADDR, REG_STATUS, 1)[0] & OSF_BIT
    if still_set:
        print("\n  ✗ OSF came straight back — the oscillator is not running.")
        print("    Check the CR1220 is seated and the right way up.")
        return

    print("\n  ── NEXT, and the write above proves NONE of it ──")
    print("  1. PHYSICALLY unplug the board. Wait. Plug it back in.")
    print("     (Ctrl-D is a soft reset — it doesn't drop power, proves nothing.)")
    print("  2. make rtc-test      → OSF still clear + correct time = battery OK")
    print("  3. ⚠ set SYNC back?  Nothing to unset — this script is the only")
    print("     writer, and it only runs when you ask for it by name.")
    print("  4. make rtc-drift ARGS=\"--mark-seed\"   (seeding voided any baseline)")
    print("     make rtc-drift                        (first sample of the new epoch)\n")


main()
