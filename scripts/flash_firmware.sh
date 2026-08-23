#!/usr/bin/env bash
# scripts/flash_firmware.sh
# Flashes MicroPython to whichever supported board you name — or asks, if you
# don't. Called by: make flash-micropython [BOARD=...]
#
# Replaces three near-duplicate Makefile targets (flash-micropython,
# flash-esp32-c3, flash-xiao2350) that had drifted apart: the last one
# validated the *Pico's* firmware variable while flashing the *XIAO's*, so a
# missing XIAO .uf2 passed the guard and then ran `picotool load` with an empty
# path. One table + one code path can't drift that way.
#
# Two flashing protocols, which is why this can't be one command:
#   • RP2350 boards (Pico 2W, XIAO RP2350) — USB mass-storage bootloader,
#     driven by picotool. Board must be in BOOTSEL.
#   • ESP32 boards (XIAO ESP32-C3) — serial bootloader, driven by esptool
#     over a /dev/cu.* port (hence detect_port.sh).
# Deliberately NOT auto-detected: which board is in your hand is something you
# already know, and guessing it from bootloader state before any firmware is
# running is more fragile than naming it (the reasoning the Makefile has
# carried since the two-target split).
#
# Note: bash 3.2 compatible (macOS ships 3.2 — no associative arrays, no
# mapfile), same constraint detect_port.sh documents.

set -e

FIRMWARE_DIR="${FIRMWARE_DIR:-firmware}"
ESPTOOL="${ESPTOOL:-.venv/bin/esptool}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Board table ───────────────────────────────────────────────────
# One row per board: key|label|method|firmware glob
# Adding a board = adding a line here, nothing else.
BOARD_KEYS="pico2w esp32c3 xiao-rp2350"

board_label() {
    case "$1" in
        pico2w)      echo "Raspberry Pi Pico 2W        (RP2350, picotool/.uf2)" ;;
        esp32c3)     echo "Seeed XIAO ESP32-C3         (esptool/.bin)" ;;
        xiao-rp2350) echo "Seeed XIAO RP2350           (RP2350, picotool/.uf2)" ;;
    esac
}

board_method() {
    case "$1" in
        pico2w|xiao-rp2350) echo "picotool" ;;
        esp32c3)            echo "esptool" ;;
    esac
}

board_glob() {
    case "$1" in
        pico2w)      echo "$FIRMWARE_DIR/RPI_PICO2_W-"*.uf2 ;;
        esp32c3)     echo "$FIRMWARE_DIR/SEEED_XIAO_ESP32C3-"*.bin ;;
        xiao-rp2350) echo "$FIRMWARE_DIR/SEEED_XIAO_RP2350-"*.uf2 ;;
    esac
}

board_download_url() {
    case "$1" in
        pico2w)      echo "https://micropython.org/download/RPI_PICO2_W/" ;;
        esp32c3)     echo "https://micropython.org/download/SEEED_XIAO_ESP32C3/" ;;
        xiao-rp2350) echo "https://micropython.org/download/SEEED_XIAO_RP2350/" ;;
    esac
}

is_valid_board() {
    for k in $BOARD_KEYS; do
        [ "$k" = "$1" ] && return 0
    done
    return 1
}

# ── Pick a board ──────────────────────────────────────────────────
BOARD="$1"

if [ -n "$BOARD" ]; then
    if ! is_valid_board "$BOARD"; then
        echo "✗ Unknown board: '$BOARD'" >&2
        echo "  Valid: $BOARD_KEYS" >&2
        exit 1
    fi
else
    echo "Which board are you flashing?" >&2
    PS3="Select board [1-3]: "
    select CHOICE in $BOARD_KEYS; do
        if [ -n "$CHOICE" ]; then
            BOARD="$CHOICE"
            break
        fi
        echo "  Invalid — enter a number" >&2
    done
fi

echo "→ Board: $(board_label "$BOARD")" >&2

# ── Locate the firmware ───────────────────────────────────────────
# Unquoted on purpose: this is where the glob expands. Guard against bash's
# no-match behaviour (leaves the literal pattern) by testing the result is a
# real file — the same [[ -e ]] guard detect_port.sh uses for its globs.
FIRMWARE=""
for f in $(board_glob "$BOARD"); do
    if [ -e "$f" ]; then
        FIRMWARE="$f"
        break
    fi
done

if [ -z "$FIRMWARE" ]; then
    echo "✗ No firmware for '$BOARD' in $FIRMWARE_DIR/" >&2
    echo "  Expected: $(board_glob "$BOARD")" >&2
    echo "  Download: $(board_download_url "$BOARD")" >&2
    exit 1
fi
echo "→ Firmware: $FIRMWARE" >&2

# ── Flash ─────────────────────────────────────────────────────────
case "$(board_method "$BOARD")" in
picotool)
    command -v picotool > /dev/null 2>&1 \
        || { echo "✗ picotool not found — run: brew install picotool" >&2; exit 1; }
    echo "→ Board must be in BOOTSEL mode (hold BOOT while connecting USB)." >&2
    picotool load "$FIRMWARE" --force
    picotool reboot
    ;;
esptool)
    [ -f "$ESPTOOL" ] \
        || { echo "✗ esptool not found in .venv — run: make setup" >&2; exit 1; }
    PORT="$("$SCRIPT_DIR/detect_port.sh")"
    # Erase first — standard MicroPython advice; avoids stale partition/NVS
    # state from a previous firmware. Only applies to the ESP32 path.
    echo "→ Erasing flash on $PORT…" >&2
    "$ESPTOOL" --port "$PORT" --chip esp32c3 erase-flash
    "$ESPTOOL" --port "$PORT" --chip esp32c3 write-flash 0x0 "$FIRMWARE"
    ;;
esac

echo "✓ Done — $BOARD rebooting into MicroPython" >&2
