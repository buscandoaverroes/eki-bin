# micropython/net.py — eki-bin
# WiFi association and NTP sync. Extracted from main.py by the V1.6 split
# (docs/v1.6-refactor.md).
#
# ⚠ THIS FILE IS NOT UPLOADED TO A RADIO-LESS BOARD, and that is the entire
# point of V1.6. main.py imports it LAZILY, inside the TIME_SOURCE == "wifi"
# branch, so a XIAO RP2350 never loads it and cannot fail on it.
#
# The failure it prevents: `import network` used to sit unconditionally at
# main.py line 17, so on a board with no radio silicon main.py died with
# ImportError BEFORE config was read — meaning TIME_SOURCE="rtc" could not
# rescue it. A hardware fact had become something you must remember to
# declare correctly, every time.
#
# The guarded import below still matters even here, for the ESP32-C3 case:
# a board that HAS a radio but cannot fit esp_wifi alongside an app this
# size (docs/insights.md §11) needs connect_wifi() to explain itself
# through the LEDs rather than die at import.

import gc
import time

from settings import (FRAME_MS, WIFI_PASS, WIFI_SSID)
from status import _draw_startup_circle

try:
    import network
    import ntptime
except ImportError:  # radio-less board — connect_wifi() explains it properly
    network = None
    ntptime = None

# ─────────────────────────────────────────────────────────────
# WiFi + NTP
# [→ Rust] embassy_net + CYW43 driver / replaced entirely by DS3231 in V2
# ─────────────────────────────────────────────────────────────
def connect_wifi():
    """Connect to WiFi, animating the loading-circle spin (see
    _draw_startup_circle) while polling — replaced a blocking `sleep(1)`
    poll loop that drew nothing at all, the main piece of real engineering
    the boot ceremony needed (the animation math itself was nothing new)."""
    # Reclaim before bringing the radio up. esp_wifi allocates real buffers
    # at active(True) and raises `OSError: Wifi Out of Memory` if the heap
    # can't serve them — a failure seen for real on the XIAO ESP32-C3 once
    # main.py passed ~2300 lines. Cheap insurance at a genuine high-water
    # mark; costs nothing on the roomier Pico 2W.
    #
    # ⚠ This does NOT rescue `mpremote run main.py` (i.e. `make run`), which
    # ships the whole ~115KB source over stdin to be held in RAM AND compiled
    # there — that peak happens before this line is ever reached. Run a file
    # this size from flash instead: `make upload`, then `make screen` + Ctrl+D
    # to soft-reset. See docs/provisioning-runbook.md § 6.
    if network is None:
        # No radio on this board AT ALL — `network` failed to import. This
        # is categorically different from "association failed": no
        # credential or signal change can fix it, and retrying is pointless.
        # The only resolution is TIME_SOURCE="rtc" (or a different board).
        print("  ✗ This board has no radio — `network` is unavailable.")
        print("    Set TIME_SOURCE='rtc' in config.py, then `make set-time`.")
        return False
    if not WIFI_SSID:
        # Reachable only with TIME_SOURCE="wifi" and no credentials set —
        # a config mistake, not a runtime failure. Say so plainly rather
        # than handing esp_wifi a None to choke on.
        print("  ✗ TIME_SOURCE='wifi' but WIFI_SSID is unset in config.py.")
        print("    Set credentials, or use TIME_SOURCE='rtc' + `make set-time`.")
        return False
    gc.collect()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("  Connecting to WiFi", end="")
    start = time.ticks_ms()
    dots_printed = 0
    while time.ticks_diff(time.ticks_ms(), start) < 20000:  # same ~20s budget
        if wlan.isconnected():                              # the old 20x sleep(1) had
            break
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        _draw_startup_circle(elapsed)
        whole_seconds = elapsed // 1000
        if whole_seconds > dots_printed:
            dots_printed = whole_seconds
            print(".", end="")
        time.sleep_ms(FRAME_MS)
    print()
    if wlan.isconnected():
        print(f"  ✓ Connected  IP: {wlan.ifconfig()[0]}")
        return True
    print("  ✗ WiFi failed — check config.py")
    return False


def sync_ntp():
    if ntptime is None:
        # Unreachable through run_startup_sequence() (connect_wifi() fails
        # first and never returns), but explicit beats an AttributeError
        # surfacing as a confusing "NTP failed" below.
        print("  ✗ No radio on this board — cannot NTP sync.")
        return False
    try:
        ntptime.settime()
        print("  ✓ NTP sync OK")
        return True
    except Exception as e:
        print(f"  ✗ NTP failed: {e}")
        return False


