#!/usr/bin/env bash
# scripts/upload.sh — copy firmware to the board, then PROVE it arrived intact.
# Called by: make upload
#
# ══ WHY THIS ISN'T JUST `mpremote cp` ═══════════════════════════════════
# `mpremote cp` can fail PARTWAY THROUGH and leave a truncated file on the
# device. That is far more dangerous than it sounds: on 2026-08-23 a
# truncated write corrupted the littlefs filesystem, MicroPython then hung
# in _boot.py mounting it BEFORE bringing up USB CDC, and the board looked
# like dead hardware for a morning — surviving every reflash, because
# firmware and filesystem are separate flash regions. Full account:
# docs/insights.md §13.
#
# The failures are intermittent and physical, not deterministic: observed
# failure points were 47%, 24%, 3%, 47% — random, which is what an
# interrupted-but-working transfer looks like, not a size or protocol bug.
# Suspects are USB-C connector strain (the board is held rigid in a
# breadboard while the cable hangs off it) and breadboard power contacts.
#
# So: retry, and VERIFY THE CONTENT after every copy — by hash, not by
# size. A same-length corruption passes a size check and then fails to
# compile on the device, which reads as a code bug rather than a bad
# transfer. An unverified success is the one outcome that can quietly
# brick the board.
#
# ══ ORDER MATTERS ═══════════════════════════════════════════════════════
# main.py goes LAST. It's the boot script — once on the device it auto-runs
# and competes with mpremote for the serial link, which showed up as
# `could not complete raw paste: b'\x01'` partway through a later copy.
# Passive data files first; the only self-starting file lands when nothing
# else needs the link.
#
# bash 3.2 compatible (macOS ships 3.2), same constraint as detect_port.sh.

set -e

MPREMOTE="${MPREMOTE:-.venv/bin/mpremote}"
ATTEMPTS="${ATTEMPTS:-3}"

device_digest() {
    # CONTENT hash, not just size. Size alone cannot detect a transfer that
    # corrupts bytes without changing length — and on 2026-08-24 a diag.py
    # that verified at the right size read back as littlefs's own superblock
    # (docs/insights.md §13).
    #
    # sha256 where the port has it (C speed); otherwise a chunked byte sum,
    # which is weaker but uses only builtins and stays O(n) at C speed via
    # sum(). Prefixed with the length either way, so truncation is caught
    # even by the fallback. Prints "missing" when the file is absent — with
    # no exception and no SystemExit, so the device is left in a clean state
    # for the copy that follows.
    "$MPREMOTE" exec "import os
def _digest(path):
    try:
        n = os.stat(path)[6]
    except OSError:
        return 'missing'
    try:
        import binascii, hashlib
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                b = f.read(1024)
                if not b:
                    break
                h.update(b)
        return '%d:sha256:%s' % (n, binascii.hexlify(h.digest()).decode())
    except (ImportError, AttributeError):
        t = 0
        with open(path, 'rb') as f:
            while True:
                b = f.read(1024)
                if not b:
                    break
                t = (t + sum(b)) & 0xFFFFFFFF
        return '%d:sum:%d' % (n, t)
print(_digest('$1'))" 2>/dev/null | tr -d ' \r\n'
}

host_digest() {
    python3 - "$1" << 'HOSTPY'
import hashlib, sys
data = open(sys.argv[1], "rb").read()
print("%d:sha256:%s" % (len(data), hashlib.sha256(data).hexdigest()))
HOSTPY
}

host_digest_sum() {
    python3 - "$1" << 'HOSTPY'
import sys
data = open(sys.argv[1], "rb").read()
t = 0
for i in range(0, len(data), 1024):
    t = (t + sum(data[i:i+1024])) & 0xFFFFFFFF
print("%d:sum:%d" % (len(data), t))
HOSTPY
}

# True when the device already holds byte-identical content. Read-only —
# costs no flash write, which is the entire point.
digest_matches() {
    _got=$(device_digest "$2")
    case "$_got" in
        *:sha256:*) _want=$(host_digest "$1") ;;
        *:sum:*)    _want=$(host_digest_sum "$1") ;;
        *)          return 1 ;;
    esac
    [ "$_want" = "$_got" ]
}

cp_verified() {
    src="$1"
    dst="$2"

    # SKIP WHAT IS ALREADY CORRECT. This matters more than it looks: the
    # V1.6 split took this upload from 3 files to 13, quadrupling the flash
    # operations per session — and flash writes are the operation least
    # tolerant of a power glitch. Three littlefs corruptions in one day
    # followed that increase (docs/insights.md §13). A typical upload
    # changes one or two modules; rewriting the other eleven is pure risk
    # for no benefit. Only possible because verification is by CONTENT now.
    if digest_matches "$src" "$dst"; then
        echo "  = $dst  (unchanged, not rewritten)"
        return 0
    fi
    attempt=1
    while [ "$attempt" -le "$ATTEMPTS" ]; do
        # Remove before writing. Two reasons, one certain and one a
        # hypothesis:
        #  • Certain: a failed cp over an EXISTING file can leave a
        #    truncated mix of old and new. Removing first means a failure
        #    leaves the file ABSENT, which fails loudly at import instead
        #    of running as subtly-wrong code.
        #  • Hypothesised: uploads succeed reliably straight after a WIPE
        #    and then start failing, which points at littlefs having to
        #    erase/garbage-collect blocks to overwrite. Freeing them first
        #    may avoid a stall long enough to break mpremote's raw paste.
        #    NOT confirmed — see the note in insights.md §13.
        # Only remove a file that actually EXISTS. On a freshly wiped
        # board every rm fails, which is a wasted round trip immediately
        # before the copy — and the first copy after a wipe is exactly
        # where uploads have been dying. $_got is left by digest_matches
        # above and reads "missing" when there is nothing to remove.
        if [ "$_got" != "missing" ]; then
            "$MPREMOTE" rm ":$dst" > /dev/null 2>&1 || true
        fi
        if "$MPREMOTE" cp "$src" ":$dst" > /dev/null 2>&1; then
            got=$(device_digest "$dst")
            case "$got" in
                *:sha256:*) want=$(host_digest "$src") ;;
                *:sum:*)    want=$(host_digest_sum "$src") ;;
                *)          want="(unreadable)" ;;
            esac
            if [ "$want" = "$got" ]; then
                echo "  ✓ $dst  (${want%%:*} bytes, content verified)"
                return 0
            fi
            echo "  ⚠ $dst CONTENT mismatch" >&2
            echo "      host   $want" >&2
            echo "      device $got" >&2
        else
            echo "  ⚠ $dst transfer failed (attempt $attempt/$ATTEMPTS)" >&2
        fi
        attempt=$((attempt + 1))
        [ "$attempt" -le "$ATTEMPTS" ] && sleep 1
        # Let the device finish any flash housekeeping before we ask again.
        sleep 0.3
    done

    echo "" >&2
    echo "✗ Could not put an intact $dst on the device after $ATTEMPTS tries." >&2
    echo "  A TRUNCATED FILE MAY BE ON THE BOARD — do not power-cycle and" >&2
    echo "  hope. Re-run this; if it keeps failing, see docs/insights.md §13" >&2
    echo "  and recover with:  make flash-micropython BOARD=<board> WIPE=1" >&2
    echo "" >&2
    echo "  These failures are physical and intermittent. Worth trying:" >&2
    echo "    • take the board OFF the breadboard (uploads that fail seated" >&2
    echo "      have succeeded on the bench — connector strain is a suspect)" >&2
    echo "    • support the USB cable so it isn't torquing the connector" >&2
    echo "    • a different cable and port" >&2
    return 1
}

STATION="${STATION:-testbench}"
SRC_DIR="${SRC_DIR:-micropython}"

# Firmware modules, extracted from main.py by V1.6 (docs/v1.6-refactor.md).
# main.py imports these, so a missing one is an ImportError at boot. Add a
# line here in the SAME commit that creates the module — the host tests
# cannot catch this, since they import from the source tree.
# Order is irrelevant at upload time (every file lands before main.py
# runs) — this simply lists what the board needs.
FIRMWARE_MODULES="settings diag primitives signals leds contracts schedule clock status gestures"

# net.py is uploaded ONLY for a WiFi unit. main.py imports it lazily, inside
# the TIME_SOURCE == "wifi" branch, so a radio-less board never reaches that
# line and does not need the file. Include it with:  make upload WIFI=1
[ "${WIFI:-0}" = "1" ] && FIRMWARE_MODULES="$FIRMWARE_MODULES net"

cp_verified "$SRC_DIR/config.py"        config.py
cp_verified "schedules/$STATION.json"   schedule.json
for _mod in $FIRMWARE_MODULES; do
    cp_verified "$SRC_DIR/$_mod.py" "$_mod.py"
    sleep 0.2   # brief settle between flash writes — see the header
done
cp_verified "$SRC_DIR/main.py"          main.py   # LAST — see header

echo "✓ Uploaded and verified: config.py, schedule.json ($STATION), $FIRMWARE_MODULES, main.py"
