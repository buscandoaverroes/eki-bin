#!/usr/bin/env bash
# scripts/detect_port.sh
# Finds the connected board's USB serial port on macOS; echoes the device path
# to stdout (informational messages go to stderr, so `PORT=$(detect_port.sh)`
# captures only the path). Auto-selects if one device; shows a numbered menu
# if multiple. Shared by `make screen` (mpremote) and `make flash-esp32-c3`
# (esptool) — both need "which /dev/cu.* is the board" and shouldn't each
# reimplement it (that's exactly the kind of fact that drifts otherwise).
#
# macOS exposes serial devices as /dev/cu.*
# cu = "call-out" — correct side for initiating a connection.
# Globs multiple known prefixes: the Pico's native USB (usbmodem*) and common
# ESP32 USB-serial bridge chips (wchusbserial*, SLAB_USBtoUART*, usbserial*) —
# which one an ESP32-family board uses depends on whether it has native USB or
# an external UART bridge, so we can't assume just one.
# Note: mapfile requires bash 4+; macOS ships bash 3.2, so we use a for loop.
# The [[ -e ]] check guards against bash 3.2 expanding an unmatched glob to the
# literal pattern string instead of an empty array.

set -e

DEVICES=()
for pattern in /dev/cu.usbmodem* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART* /dev/cu.usbserial*; do
    for d in $pattern; do
        [[ -e "$d" ]] && DEVICES+=("$d")
    done
done

if [ ${#DEVICES[@]} -eq 0 ]; then
    echo "✗ No USB devices found." >&2
    echo "  → Is the board plugged in?" >&2
    echo "  → Try unplugging and replugging." >&2
    exit 1
fi

if [ ${#DEVICES[@]} -eq 1 ]; then
    PORT="${DEVICES[0]}"
    echo "→ Auto-selected: $PORT" >&2
else
    echo "Multiple USB devices found:" >&2
    PS3="Select device [1-${#DEVICES[@]}]: "
    select PORT in "${DEVICES[@]}"; do
        [ -n "$PORT" ] && break
        echo "  Invalid — enter a number" >&2
    done
fi

echo "$PORT"
