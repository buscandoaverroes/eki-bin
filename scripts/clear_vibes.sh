#!/usr/bin/env bash
# scripts/clear_vibes.sh
# Lists vibration_*.json(l) and handling_*.json(l) files sitting on the
# device's flash and, after confirmation, deletes them all. `mpremote cp`
# only copies data off the device — it never deletes the original — so
# these accumulate across vibration_sandbox.py / handling_test.py sessions
# until flash fills up (this was built after hitting exactly that:
# OSError 28 / ENOSPC mid-session).
# Called by: make clear-vibes
set -e

MPREMOTE="${MPREMOTE:-.venv/bin/mpremote}"

FILES=$("$MPREMOTE" exec "import os; print(' '.join(f for f in os.listdir() if (f.startswith('vibration_') or f.startswith('handling_')) and (f.endswith('.jsonl') or f.endswith('.json'))))" | tr -d '\r')

if [ -z "$FILES" ]; then
    echo "✓ Nothing to clean — no vibration_*/handling_*.json(l) files on-device"
    exit 0
fi

echo "Found on-device:"
for f in $FILES; do
    echo "  $f"
done
echo ""
echo "Make sure these are already pulled off (mpremote cp :<file> ./data/) before deleting!"
read -p "Delete all of the above from the device? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "aborted — nothing deleted"
    exit 0
fi

for f in $FILES; do
    "$MPREMOTE" exec "import os; os.remove('$f')"
    echo "  ✓ deleted $f"
done

echo "✓ done — $(echo "$FILES" | wc -w | tr -d ' ') file(s) removed"
