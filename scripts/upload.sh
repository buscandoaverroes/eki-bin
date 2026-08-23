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
# So: retry, and VERIFY BY SIZE after every copy. An unverified success is
# the one outcome that can quietly brick the board.
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

device_size() {
    # os.stat()[6] is st_size. Missing file -> empty, which never matches.
    "$MPREMOTE" exec "import os
try:
    print(os.stat('$1')[6])
except OSError:
    print('missing')" 2>/dev/null | tr -d ' \r\n'
}

cp_verified() {
    src="$1"
    dst="$2"
    want=$(wc -c < "$src" | tr -d ' ')
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
        "$MPREMOTE" rm ":$dst" > /dev/null 2>&1 || true
        if "$MPREMOTE" cp "$src" ":$dst" > /dev/null 2>&1; then
            got=$(device_size "$dst")
            if [ "$want" = "$got" ]; then
                echo "  ✓ $dst  ($want bytes verified)"
                return 0
            fi
            echo "  ⚠ $dst size mismatch — host $want, device $got" >&2
        else
            echo "  ⚠ $dst transfer failed (attempt $attempt/$ATTEMPTS)" >&2
        fi
        attempt=$((attempt + 1))
        [ "$attempt" -le "$ATTEMPTS" ] && sleep 1
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

cp_verified "$SRC_DIR/config.py"        config.py
cp_verified "schedules/$STATION.json"   schedule.json
cp_verified "$SRC_DIR/main.py"          main.py   # LAST — see header

echo "✓ Uploaded and verified: config.py, schedule.json ($STATION), main.py"
