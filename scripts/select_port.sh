#!/usr/bin/env bash
# scripts/select_port.sh
# Opens the MicroPython REPL on the connected board's USB serial port.
# Port detection lives in scripts/detect_port.sh (shared with `make
# flash-esp32-c3`, which needs the same "which /dev/cu.* is the board" logic).
# Called by: make screen

set -e

MPREMOTE="${MPREMOTE:-.venv/bin/mpremote}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="$("$SCRIPT_DIR/detect_port.sh")"

echo "→ Opening REPL on $PORT  (Ctrl+] to exit)" >&2
echo "" >&2

exec "$MPREMOTE" connect "$PORT" repl
