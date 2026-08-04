# micropython/handling_test.py — eki-bin false-positive risk collector
# Tests the gap flagged in docs/insights.md §8's wake-gate discussion:
# vibration_sandbox.py's flick data (91.2% separable from a DELIBERATE soft
# tap) tells us nothing about separability from ACCIDENTAL handling — nobody
# has captured what picking the bottle up, setting it down, carrying it, or
# bumping it actually looks like. That's what this collects.
#
# Deliberately NOT the full position×gesture matrix vibration_sandbox.py
# uses — that question (tap/flick, at known positions) is already answered
# with real data. This is flat: a handful of handling scenarios, plus a
# SMALL same-session tap/flick reference batch (not a full re-collection —
# just enough to catch session-to-session drift, which has repeatedly
# turned out to matter for this project's numbers; see insights.md §8's
# shoulder/base separability swinging 96.7%→71.2%→81.7% across sessions).
#
# Same capture machinery as vibration_sandbox.py (I2C setup, arm/capture
# loop, streaming JSONL, retry-on-I2C-error, gc.collect()) — duplicated
# rather than imported, matching this repo's standalone-bring-up-script
# convention (see imu_test.py's header for why).
#
# ⚠ Same input()/mpremote-run caveat as vibration_sandbox.py — this needs a
# real REPL, not `mpremote run`. See that file's header for the full
# explanation (mpremote run doesn't forward keystrokes to a running script).
#
# Run (same two-step flow as vibration_sandbox.py):
#   make upload-file FILE=micropython/handling_test.py
#   make screen
#   then Ctrl-D inside the REPL to soft-reset and start the script.
#   Afterward: `make upload` to restore the real firmware.

import gc
import json
import math
import os
import select
import sys
import time

from machine import I2C, Pin

# ── Configuration ────────────────────────────────────────────────
SDA_PIN = 0  # SET PER BOARD — see imu_test.py header
SCL_PIN = 1
I2C_ID = 0

WHO_AM_I_REG = 0x0F
WHO_AM_I_EXPECTED = 0x70
CTRL1_REG = 0x10
CTRL1_240HZ_HIGH_PERF = 0x07  # same rate as vibration_sandbox.py — comparable
# numbers only make sense at the same ODR (see that file's header on this).
CTRL1_POWER_DOWN = 0x00
OUTX_L_A = 0x28
CANDIDATE_ADDRS = (0x6A, 0x6B)

SAMPLE_INTERVAL_MS = 4  # ~240Hz
CAPTURE_TIMEOUT_MS = 15000  # much longer than vibration_sandbox.py's 5000 —
# "carry across the room" is a sustained multi-second event, not a discrete
# impulse. Still a bounded safety cap, same purpose as before.

SCENARIOS = (
    "pickup",          # grab and lift off the surface
    "setdown_gentle",  # place back down carefully
    "setdown_firm",    # place back down without being careful about it
    "carry",           # walk across a room while holding it
    "bump",            # something else hits it — the "my vase clipped it" case
    "grab_and_tap",    # grip the bottle firmly, then tap while holding — tests
    # whether holding (which damped rocking back when this was a data-quality
    # PROBLEM, see insights.md §8) could instead be a deliberate reliability
    # feature for a real gesture, not just a collection-methodology footnote.
)
# Distinct names from vibration_sandbox.py's "tap"/"flick" — this is a
# different file/tool, but distinct labels avoid any confusion when eyeballing
# a captures list later. Small batch, not a re-collection (see file header).
REFERENCE = ("tap_reference", "flick_reference")
ALL_SCENARIOS = SCENARIOS + REFERENCE

DEFAULT_REPS_PER_SCENARIO = 10
FASTENINGS = ("blue tack", "double-sided tape")  # + free-text "other" at runtime


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
    data = i2c.readfrom_mem(addr, OUTX_L_A, 6)
    x = int.from_bytes(data[0:2], "little")
    y = int.from_bytes(data[2:4], "little")
    z = int.from_bytes(data[4:6], "little")
    return tuple(v - 65536 if v > 32767 else v for v in (x, y, z))


_SLUG_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def _slugify(text):
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


def _write_record(f, fields, samples):
    """Streams the record directly from the raw (t,x,y,z) tuples — never
    builds a second [[t,x,y,z],...] list first. A prior version did that via
    a list comprehension before json.dump(record, f); on a long capture
    (the "carry" scenario runs several seconds), that intermediate list was
    itself a big-enough allocation to MemoryError after enough heap
    fragmentation from earlier reps. json.dump alone wasn't the whole fix —
    this is."""
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


def _prompt_reps_plan():
    """Same shape as vibration_sandbox.py's plan builder, flattened to one
    axis (scenario) instead of position×gesture — there's no position
    dimension here, handling events aren't localized taps."""
    plan = []
    combo_totals = {}
    print(f"  reps per scenario (Enter for default {DEFAULT_REPS_PER_SCENARIO}, 0 to skip):")
    for scenario in ALL_SCENARIOS:
        raw = input(f"    {scenario} [{DEFAULT_REPS_PER_SCENARIO}]: ").strip()
        n = int(raw) if raw.isdigit() else DEFAULT_REPS_PER_SCENARIO
        if n > 0:
            combo_totals[scenario] = n
            plan.extend([scenario] * n)
    return plan, combo_totals


def _live_peak_mg(samples):
    """Rough live feedback only — NOT the same computation the host's
    extract_features()/engineer_features() use (those use the whole
    capture's median as baseline; this uses just the first sample, cheap
    and good enough to tell you "hit it harder" in real time without
    waiting for the post-hoc host analysis)."""
    baseline = math.sqrt(samples[0][1] ** 2 + samples[0][2] ** 2 + samples[0][3] ** 2) * 0.061
    peak = 0
    for _, x, y, z in samples:
        mag = math.sqrt(x * x + y * y + z * z) * 0.061
        dev = abs(mag - baseline)
        if dev > peak:
            peak = dev
    return peak


def _capture_rep(i2c, addr, poll, scenario):
    input(f"  press Enter, then do: {scenario} ...")
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
            print(f"  (auto-stopped after {CAPTURE_TIMEOUT_MS}ms)")
            break
        time.sleep_ms(SAMPLE_INTERVAL_MS)
    print(f"  captured {len(samples)} samples over {samples[-1][0]}ms")
    print(f"  approx peak: {_live_peak_mg(samples):.0f}mg  (target for flick_reference: 750-800mg+)")
    return samples


def main():
    print("\n══ eki-bin handling / false-positive test ═══════════")
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
        print("\n  nothing planned (all scenarios set to 0) — nothing to do")
        return
    plan_str = ", ".join(f"{s}×{n}" for s, n in combo_totals.items())
    print(f"\n  plan: {plan_str}  =  {len(plan)} reps total")
    print("  Ctrl+C at any point stops early — every finished rep is already saved\n")

    filename = f"handling_{_slugify(bottle)}_{_slugify(fastening)}.jsonl"
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
    scenario_seen = {}
    try:
        for i, scenario in enumerate(plan, 1):
            scenario_seen[scenario] = scenario_seen.get(scenario, 0) + 1
            seen = scenario_seen[scenario]
            total = combo_totals[scenario]
            print(f"\n  ── rep {i}/{len(plan)}  [{scenario} {seen}/{total}] ──")

            samples = None
            while samples is None:
                try:
                    samples = _capture_rep(i2c, addr, poll, scenario)
                except OSError as e:
                    print(f"  ✗ I2C error mid-capture: {e}")
                    print("  check the sensor's wiring")
                    if input("  retry this rep? (y/n): ").strip().lower() != "y":
                        stopped_early = True
                        break
            if stopped_early:
                break

            _write_record(f, [("scenario", scenario)], samples)
            f.flush()
            saved += 1
            samples = None
            gc.collect()
    except KeyboardInterrupt:
        stopped_early = True
    finally:
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


main()
