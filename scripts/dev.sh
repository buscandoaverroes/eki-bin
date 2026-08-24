#!/usr/bin/env bash
# scripts/dev.sh — run the firmware from the HOST filesystem. No flash writes.
# Called by: make dev
#
# `mpremote mount` serves micropython/ over the serial link as the device's
# filesystem, so main.py and every module are read from your working copy.
# Nothing is written to flash — which sidesteps the write-count stall that
# makes `make upload` unreliable on this platform (docs/insights.md §13).
#
# ══ WHY THIS ISN'T JUST THE ONE-LINER ═══════════════════════════════════
# Ctrl-C during a mounted session leaves two messes:
#
#   1. A 30-line Python traceback ending in
#      `TransportError: could not enter raw repl`. That is mpremote failing
#      to unmount an interrupted session, not a device fault — but it reads
#      exactly like one, and this project has already lost hours to errors
#      that pointed at the wrong layer.
#   2. The device may still believe /remote is mounted. Every subsequent
#      import then resolves against a filesystem whose host side is gone.
#
# So: swallow the interrupt traceback (and only that one), then soft-reset
# the device to drop the stale mount. Real errors still print.
#
# bash 3.2 compatible (macOS ships 3.2).

set -u

MPREMOTE="${MPREMOTE:-.venv/bin/mpremote}"
SRC_DIR="${SRC_DIR:-micropython}"

ERR="$(mktemp -t ekibin-dev)"
INTERRUPTED=0

cleanup() {
    # Drop the stale mount. Failure here is expected and harmless when the
    # device was already reset or unplugged — never let it mask the run.
    "$MPREMOTE" soft-reset > /dev/null 2>&1 || true
    rm -f "$ERR"
}
trap cleanup EXIT
trap 'INTERRUPTED=1' INT

echo "→ Mounting $SRC_DIR/ as the device filesystem (nothing written to flash)" >&2
echo "  Ctrl-C to stop." >&2
"$MPREMOTE" mount "$SRC_DIR" run "$SRC_DIR/main.py" 2> "$ERR"
RC=$?

if [ "$INTERRUPTED" = "1" ] || grep -q "KeyboardInterrupt" "$ERR" 2> /dev/null; then
    echo "" >&2
    echo "→ Stopped. Device reset; flash untouched." >&2
    exit 0
fi

# Not an interrupt — show whatever actually went wrong.
if [ -s "$ERR" ]; then
    cat "$ERR" >&2
fi
exit "$RC"
