# micropython/vibration_sandbox.py — eki-bin tap/location tuning tool
# Interactive data-collection sandbox for the wake-interaction layer's tap
# classifier. NOT a smoke test (see imu_test.py for that) and NOT
# config-driven — a hands-on tool you run once per bottle/mount to build a
# labeled dataset, then hand off to scripts/analyze_taps.py on the host.
#
# Flow: names the bottle + fastening method once, then asks how many reps you
# want per position×tap-count combo (6 combos: neck/body × 1/2/3 taps) and
# runs the whole plan sequentially, grouped by combo — so you settle into a
# tapping rhythm per combo instead of re-selecting position/tap-count every
# single rep. Each rep is still REPL-driven: press Enter to arm, tap the
# bottle, press Enter again to stop. Each rep is streamed to a .jsonl file on
# flash immediately after capture (NOT held in RAM for the whole session —
# see main()'s comment for why that mattered), which you pull off with
# `mpremote cp` and hand to the host analysis script.
#
# ⚠ `input()` needs a REAL interactive REPL connection — `mpremote run` only
# streams stdout back and forwards Ctrl-C, it does NOT forward typed keystrokes
# to a running script's input() calls (confirmed: this hangs forever, not a
# script bug — see github.com/orgs/micropython/discussions/17118). Every other
# bring-up script in this repo only uses blocking loops + Ctrl+C, so this is
# the first script here that actually needs stdin.
#
# Wiring/register facts: same as imu_test.py — see that file's header.
#
# Run (two steps, both existing Makefile targets — NOT `make run-file`):
#   make upload-file FILE=micropython/vibration_sandbox.py   # → device :main.py
#   make screen                                               # real REPL
#   then press Ctrl-D inside the REPL to soft-reset and start the script.
#   Afterward: `make upload` to restore the real firmware as main.py.

import gc
import json
import os
import select
import sys
import time

from machine import I2C, Pin

# ── Configuration ────────────────────────────────────────────────
SDA_PIN = 6  # SET PER BOARD (Pico 2W=0/1, XIAO C3=6/7) — see imu_test.py header
SCL_PIN = 7  # currently: XIAO ESP32-C3. Echoed at startup so a stale value
#              shows up as a wrong number, not as a mystery empty scan.
I2C_ID = 0

WHO_AM_I_REG = 0x0F
WHO_AM_I_EXPECTED = 0x70
CTRL1_REG = 0x10
# 240Hz, not imu_test.py's 60Hz — real data showed fast consecutive taps
# blurring into one continuous excursion at 60Hz's 16.7ms/sample resolution.
# LSM6DSV16X_ODR_AT_240Hz = 0x7, HIGH_PERFORMANCE_MD = 0x0<<4 — verified
# against ST's own driver source (lsm6dsv16x-pid/lsm6dsv16x_reg.h), not guessed.
CTRL1_240HZ_HIGH_PERF = 0x07
CTRL1_POWER_DOWN = 0x00
OUTX_L_A = 0x28
CANDIDATE_ADDRS = (0x6A, 0x6B)

SAMPLE_INTERVAL_MS = 4  # ~240Hz, matching CTRL1's configured ODR
CAPTURE_TIMEOUT_MS = 5000  # safety cap per rep, in case the stop keypress is missed

POSITIONS = ("neck", "shoulder", "body", "base")
# shoulder: the sloped transition between neck and body — tap vector angles
# inward rather than straight down, hypothesized to excite less rocking than
# a neck tap. base: grounded contact point, for tall/rocking-prone bottles.
# Skip any of these with 0 reps on bottles where they're redundant (e.g.
# shoulder barely exists on a squat jar). neck stays in despite being the
# most rocking-prone — real data (docs/insights.md §8) shows it's also the
# BEST-separated position (97% vs base, 90% vs body), so it's a strong
# position signal even though it's a weak tap-count signal — dropping it
# would fix the wrong research question.
GESTURES = ("tap", "flick", "grab_and_tap")
# Tap-count (1 vs. 2) is a settled question as of insights.md §8 — 1-tap
# works, 2-tap and 3-tap don't hold up on any bottle/position tested, and
# we're not pursuing multi-tap counting further. This replaces that axis:
# flick = a deliberately hard/sharp impact, distinct from a normal tap by
# amplitude alone (should be easy — it's a designed gap, not a subtle
# bottle-physics one, unlike the position-separability problems above).
# grab_and_tap = grip the bottle firmly, then tap while holding — added
# after handling_test.py's body-only pilot showed holding jumping detection
# reliability from 51% to 90% (suppresses the same rocking that made free
# taps unreliable in the first place). Testing across all 4 positions here,
# not just body — neck is the most interesting case, since it was the
# WORST-affected by rocking un-held and so has the most to gain from it
# being suppressed.
# Every rep is still one physical event (taps_intended stays 1 for all
# three gesture types) — this tests "how" a tap is delivered, not "how many."
DEFAULT_REPS_PER_COMBO = 3
FASTENINGS = ("blue tack", "double-sided tape")  # + free-text "other" at runtime

# Raw int16 LSB counts are stored as-is — no mg conversion on-device. The host
# analysis script applies MG_PER_LSB_AT_2G itself, so the sensitivity constant
# lives in exactly one place. See imu_test.py's header for why it's approximate.


def _find_device(i2c):
    found = i2c.scan()
    for addr in CANDIDATE_ADDRS:
        if addr not in found:
            continue
        who = i2c.readfrom_mem(addr, WHO_AM_I_REG, 1)[0]
        if who == WHO_AM_I_EXPECTED:
            return addr
    return None


def _read_accel_raw(i2c, addr):
    """One burst read, signed LSB counts (no unit conversion — see header)."""
    data = i2c.readfrom_mem(addr, OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    return tuple(v - 65536 if v > 32767 else v for v in (x, y, z))


def _write_record(f, fields, samples):
    """Streams the record directly from the raw (t,x,y,z) tuples — never
    builds a second [[t,x,y,z],...] list first. A prior version did that via
    a list comprehension before json.dump(record, f); on a long enough
    capture and enough heap fragmentation from earlier reps, that
    intermediate list is itself a big-enough allocation to MemoryError
    (confirmed on handling_test.py's "carry" scenario — same bug, this file
    just hadn't hit a capture long enough to trigger it yet). json.dump
    alone wasn't the whole fix — this is."""
    f.write("{")
    for i, (key, value) in enumerate(fields):
        if i > 0:
            f.write(", ")
        f.write(json.dumps(key) + ": " + json.dumps(value))
    f.write(', "samples": [')
    for i, (t, x, y, z) in enumerate(samples):
        if i > 0:
            f.write(",")
        f.write(f"[{t},{x},{y},{z}]")
    f.write("]}\n")


_SLUG_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def _slugify(text):
    # Not .isalnum() — MicroPython's built-in str doesn't implement it on
    # this port (confirmed by a live AttributeError, not assumed).
    out = "".join(ch if ch in _SLUG_CHARS else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "unnamed"


def _prompt_choice(label, options):
    print(f"  {label}:")
    for i, opt in enumerate(options, 1):
        print(f"    {i}) {opt}")
    other_idx = len(options) + 1
    print(f"    {other_idx}) other (type it)")
    while True:
        raw = input("  > ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            if idx == other_idx:
                return input("  type it: ").strip()
        print("  ✗ enter a number from the list")


def _prompt_reps_plan():
    """Ask once per combo how many reps to run (Enter = default, 0 = skip),
    then expand into a flat, sequential, grouped-by-combo rep list — e.g.
    [(neck,tap), (neck,tap), (neck,tap), (neck,flick), ..., (base,flick)].
    Grouping by combo (rather than interleaving/shuffling) means you only
    reposition your tapping hand once per combo, not every single rep."""
    plan = []
    combo_totals = {}
    print(f"  reps per combo (Enter for default {DEFAULT_REPS_PER_COMBO}, 0 to skip):")
    for position in POSITIONS:
        for gesture in GESTURES:
            raw = input(f"    {position}-{gesture} [{DEFAULT_REPS_PER_COMBO}]: ").strip()
            n = int(raw) if raw.isdigit() else DEFAULT_REPS_PER_COMBO
            if n > 0:
                combo_totals[(position, gesture)] = n
                plan.extend([(position, gesture)] * n)
    return plan, combo_totals


GESTURE_INSTRUCTIONS = {
    "tap": "tap",
    "flick": "flick",
    "grab_and_tap": "grip firmly, then tap while holding",
}


def _capture_rep(i2c, addr, poll, gesture):
    instruction = GESTURE_INSTRUCTIONS.get(gesture, gesture)
    input(f"  press Enter, then {instruction} the bottle...")
    print("  recording — press Enter to stop")
    samples = []
    start = time.ticks_ms()
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        x, y, z = _read_accel_raw(i2c, addr)
        samples.append((elapsed, x, y, z))
        if poll.poll(0):
            sys.stdin.readline()  # consume the Enter that stopped us
            break
        if elapsed >= CAPTURE_TIMEOUT_MS:
            print(f"  (auto-stopped after {CAPTURE_TIMEOUT_MS}ms — forgot to press Enter?)")
            break
        time.sleep_ms(SAMPLE_INTERVAL_MS)
    print(f"  captured {len(samples)} samples over {samples[-1][0]}ms")
    return samples


def main():
    print("\n══ eki-bin vibration sandbox ═════════════════════")
    print(f"  bus: I2C{I2C_ID}  SDA=GPIO{SDA_PIN}  SCL=GPIO{SCL_PIN}  freq=400kHz")
    i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
    addr = _find_device(i2c)
    if addr is None:
        print("  ✗ No LSM6DSV16X found — run imu_test.py first to debug wiring")
        return
    i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_240HZ_HIGH_PERF]))
    print(f"  ✓ LSM6DSV16X at {hex(addr)}, 240Hz\n")

    bottle = input("  bottle name: ").strip() or "unnamed_bottle"
    fastening = _prompt_choice("IMU fastening method", list(FASTENINGS))

    plan, combo_totals = _prompt_reps_plan()
    if not plan:
        print("\n  nothing planned (all combos set to 0) — nothing to do")
        return
    plan_str = ", ".join(f"{pos}-{gesture}×{n}" for (pos, gesture), n in combo_totals.items())
    print(f"\n  plan: {plan_str}  =  {len(plan)} reps total")
    print("  Ctrl+C at any point stops early — every finished rep is already saved\n")

    # Stream each rep to flash as one JSON line, immediately after capture —
    # NOT accumulated in RAM for the whole session. A prior version built one
    # big captures list + per-sample dicts (expensive: dict overhead per
    # sample, nothing freed until the final write) and hit MemoryError on
    # rep 2 of a 60-rep/240Hz plan. Samples are now compact [t,x,y,z] lists,
    # not {"t_ms":t,...} dicts — analyze_taps.py converts them back on the
    # host, which has RAM to spare.
    filename = f"vibration_{_slugify(bottle)}_{_slugify(fastening)}.jsonl"
    try:
        os.stat(filename)
        exists = True
    except OSError:
        exists = False
    if exists:
        if input(f"  ✗ {filename} already exists on-device — overwrite? (y/n): ").strip().lower() != "y":
            print("  aborted — nothing overwritten")
            return
    f = open(filename, "w")
    f.write(json.dumps({"bottle": bottle, "fastening": fastening}) + "\n")

    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    saved = 0
    stopped_early = False
    combo_seen = {}
    try:
        for i, (position, gesture) in enumerate(plan, 1):
            combo_seen[(position, gesture)] = combo_seen.get((position, gesture), 0) + 1
            seen = combo_seen[(position, gesture)]
            total = combo_totals[(position, gesture)]
            print(f"\n  ── rep {i}/{len(plan)}  [{position}-{gesture} {seen}/{total}] ──")

            # A single bad I2C transaction (e.g. a jumper wire loosened by all
            # this tapping) used to kill the entire remaining batch. Now it
            # only costs this one rep — retry in place, or bail and keep
            # everything already saved.
            samples = None
            while samples is None:
                try:
                    samples = _capture_rep(i2c, addr, poll, gesture)
                except OSError as e:
                    print(f"  ✗ I2C error mid-capture: {e}")
                    print("  check the sensor's wiring — likely a connection shaken loose by tapping")
                    if input("  retry this rep? (y/n): ").strip().lower() != "y":
                        stopped_early = True
                        break
            if stopped_early:
                break

            _write_record(
                f,
                [("position", position), ("gesture", gesture), ("taps_intended", 1)],
                samples,
            )
            f.flush()
            saved += 1
            samples = None
            gc.collect()  # reclaim this rep's buffer before the next capture starts
    except KeyboardInterrupt:
        stopped_early = True
    finally:
        # Two independent cleanup steps — one failing (e.g. the same I2C bus
        # issue that just interrupted a capture) must not stop the other from
        # running, and must not mask whatever exception is already
        # propagating. A prior version had these unguarded, and a failed
        # power-down write here silently replaced the real error from inside
        # the try block — MicroPython doesn't chain exceptions like CPython
        # does, so that message was gone, not just hidden.
        try:
            i2c.writeto_mem(addr, CTRL1_REG, bytes([CTRL1_POWER_DOWN]))
        except OSError as e:
            print(f"  (couldn't power down IMU cleanly: {e})")
        f.close()

    if stopped_early:
        print("\n  stopped early")

    if saved == 0:
        print("\n  no captures recorded — nothing to save")
        return

    print(f"\n  ✓ saved {saved} rep(s) → {filename}")
    print(f"  pull it off with:   mpremote cp :{filename} ./data/")
    print(f"  then clean up the device (accumulates otherwise):  make clear-vibes")
    print(f"  then analyze with:  python scripts/analyze_taps.py data/{filename}")


main()
