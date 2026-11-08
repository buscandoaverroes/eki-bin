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
    # Drop the stale mount with a soft reset — but a soft reset RE-RUNS
    # main.py from flash, so the board comes back busy in the display loop
    # and the next session cannot get a raw REPL. (That regression was this
    # script's own doing, 2026-08-24.) So: reset, then immediately interrupt
    # whatever auto-started, leaving the device idle at the REPL.
    #
    # Both failures are expected and harmless when the device was already
    # reset or unplugged — never let them mask the run.
    "$MPREMOTE" soft-reset > /dev/null 2>&1 || true
    sleep 0.5
    "$MPREMOTE" exec "pass" > /dev/null 2>&1 || true
    rm -f "$ERR"
}
trap cleanup EXIT
trap 'INTERRUPTED=1' INT

echo "→ Mounting $SRC_DIR/ as the device filesystem (nothing written to flash)" >&2
echo "  Ctrl-C to stop." >&2
"$MPREMOTE" mount "$SRC_DIR" run "$SRC_DIR/main.py" 2> "$ERR"
RC=$?

# "could not enter raw repl" at STARTUP means the device never answered —
# almost always because it is busy running main.py from flash. Say that
# instead of printing mpremote's traceback, which points at the transport.
if grep -q "could not enter raw repl" "$ERR" 2> /dev/null && [ "$INTERRUPTED" != "1" ]; then
    echo "" >&2
    echo "✗ The device did not answer — it is probably BUSY, running main.py" >&2
    echo "  from its own flash. A reset auto-runs it, and a board inside the" >&2
    echo "  display loop cannot be interrupted into a raw REPL." >&2
    echo "" >&2
    echo "  Recover by interrupting it by hand:" >&2
    echo "    make screen     then Ctrl-C to stop it, Ctrl-] to exit" >&2
    echo "  then re-run make dev." >&2
    echo "" >&2
    echo "  To stop this recurring, remove the flashed copy — `make dev`" >&2
    echo "  serves main.py from micropython/ anyway, so the one on flash is" >&2
    echo "  redundant during development:" >&2
    echo "    .venv/bin/mpremote rm :main.py" >&2
    echo "  (make upload puts it back when you want a standalone unit.)" >&2
    exit 1
fi

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
