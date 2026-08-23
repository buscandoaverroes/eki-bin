#!/usr/bin/env python3
"""scripts/rtc_drift.py — measure DS3231 drift against this Mac's clock.

Run it:  make rtc-drift            (see Makefile; --help for options)

═══ WHY THIS EXISTS ════════════════════════════════════════════════════
The DS3231 is bought for +/-2 ppm. Eyeballing `rtc_test.py` output next to
a host clock can't confirm that. Comparing two sequentially-run programs
is good to maybe +/-1-2s, and 2 ppm is 0.173 s/day, so you would need
roughly a WEEK of accumulated error before the drift exceeded the noise
of the measurement. That's not a patience problem, it's a precision one.

═══ THE TRICK: MEASURE THE EDGE, NOT THE READING ═══════════════════════
Reading the seconds register tells you the time to the nearest second.
Watching for the register to CHANGE tells you a hardware-timed 1 Hz
boundary to within one poll interval. At the instant the register flips
to S, the DS3231's true time is exactly S.000 -- no fractional unknown.

That converts a +/-1s reading into a +/-(poll + USB latency) reading,
plausibly tens of ms. 2 ppm then becomes visible in about three hours
instead of a week. This script does NOT assume that number: it takes
several edges per run and reports the observed spread, so the precision
is measured rather than claimed. (Being wrong about an assumed constant
is how three separate bring-up sessions got lost on this project.)

═══ WHY CONSTANT LATENCY DOESN'T MATTER ════════════════════════════════
There IS a systematic bias here: the delay between the device printing
and this script timestamping the line. It is NOT calibrated out, and the
absolute offset is therefore only good to that bias.

Drift doesn't care. Drift is the CHANGE in offset over time, so any bias
that is the same at both ends subtracts away. This is also why the script
never needs to know the timezone: if the DS3231 holds UTC and the host is
JST, the offset is a constant -9h and the drift is unaffected. The
integration branch is about to switch the chip to UTC -- deliberately,
this tool doesn't care when that happens.

═══ DECODE LIVES HERE, NOT ON THE DEVICE ═══════════════════════════════
The device-side snippet below does the least it possibly can: detect the
edge, dump 7 raw register bytes as hex, repeat. All BCD decoding happens
in this file, on the host, where pytest can reach it (tests/test_rtc_drift.py).
rtc_test.py has its own on-device decoder and that duplication is
intentional -- it must run standalone with no host. Keeping THIS decoder
testable is worth more than sharing one untestable copy.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_PATH = REPO / "data" / "rtc-drift.jsonl"
MPREMOTE = REPO / ".venv" / "bin" / "mpremote"

# Board defaults: XIAO RP2350. Same per-board values rtc_test.py documents --
# on RP2350 the I2C ID is NOT a free choice, it is fixed by the pin table.
#   Pico 2W       : sda 0, scl 1, id 0
#   XIAO ESP32-C3 : sda 6, scl 7, id 0   (ESP32 maps I2C in software)
#   XIAO RP2350   : sda 6, scl 7, id 1   (labeled D4/D5 = GP6/GP7 = I2C1)
DEFAULT_SDA, DEFAULT_SCL, DEFAULT_ID = 6, 7, 1

# Runs on the device. Tiny on purpose -- every line here is a line that
# can't be unit-tested. It detects seconds-register edges and dumps raw
# bytes; interpretation is this file's job.
DEVICE_SNIPPET = """
from machine import I2C, Pin
i2c = I2C({i2c_id}, scl=Pin({scl}), sda=Pin({sda}), freq=400000)
b = bytearray(7)
i2c.readfrom_mem_into(0x68, 0, b)
prev = b[0]
n = 0
while n < {samples}:
    i2c.readfrom_mem_into(0x68, 0, b)
    if b[0] != prev:
        print("EDGE", "".join("%02x" % x for x in b))
        prev = b[0]
        n += 1
"""


def _bcd(byte):
    return (byte >> 4) * 10 + (byte & 0x0F)


def decode_registers(raw):
    """7 DS3231 time registers -> naive datetime.

    Mirrors rtc_test.py's reader, including the 12-hour branch: this script
    never writes the chip, so it can be handed one that was set by other
    means and left in 12-hour mode.
    """
    if len(raw) != 7:
        raise ValueError("expected 7 registers, got %d" % len(raw))
    second = _bcd(raw[0] & 0x7F)
    minute = _bcd(raw[1] & 0x7F)
    hour_reg = raw[2]
    if hour_reg & 0x40:  # 12-hour mode: bit5 is AM/PM, not part of the value
        hour = _bcd(hour_reg & 0x1F)
        if hour_reg & 0x20 and hour != 12:
            hour += 12
        elif not hour_reg & 0x20 and hour == 12:
            hour = 0
    else:
        hour = _bcd(hour_reg & 0x3F)
    date = _bcd(raw[4] & 0x3F)
    month = _bcd(raw[5] & 0x1F)
    # Century bit (month reg bit7) rolls the two-digit year into 2100+.
    # A working unit keeps it clear for all of 2000-2099; it's decoded
    # anyway so a set bit reads as a wrong DATE rather than a silent
    # hundred-year error hiding inside a plausible-looking year.
    century = 2100 if raw[5] & 0x80 else 2000
    return datetime(century + _bcd(raw[6]), month, date, hour, minute, second)


def fit_line(samples):
    """Least-squares (slope, intercept) over (t, offset), t rebased to the
    first sample to avoid catastrophic cancellation on epoch-sized floats.
    Returns None if the fit is undefined."""
    if len(samples) < 2:
        return None
    n = len(samples)
    t0 = samples[0][0]
    xs = [t - t0 for t, _ in samples]
    ys = [o for _, o in samples]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return slope, mean_y - slope * mean_x


def fit_rms_residual(samples):
    """RMS distance of the samples from their own fitted line, in SECONDS.

    This is the honesty check. If drift were constant, every sample would
    sit on one line and the only scatter would be measurement jitter (~4ms,
    reported per run). Scatter far larger than that means the data is not
    describable by a constant drift at all — and the usual reason is that
    the REFERENCE moved: macOS disciplines its clock against NTP and can
    step tens of ms.

    Without this, a long elapsed time alone was enough for the tool to call
    a figure "meaningful", which it did on 2026-08-23 over samples whose
    segments disagreed by 17.5 ppm."""
    fit = fit_line(samples)
    if fit is None:
        return None
    slope, intercept = fit
    t0 = samples[0][0]
    residuals = [o - (slope * (t - t0) + intercept) for t, o in samples]
    return (sum(r * r for r in residuals) / len(residuals)) ** 0.5


def drift_ppm_fit(samples):
    """Least-squares slope through (t, offset) samples → ppm.

    Preferred over differencing the first and last sample once there are
    three or more, because the host clock is not a fixed reference: macOS
    disciplines it against NTP and can slew by tens of ms. A two-point
    measurement folds any such step straight into the answer, while a fit
    over many samples averages it out and lets an outlier show itself.

    Returns None for fewer than 2 samples or a zero time span."""
    fit = fit_line(samples)
    return None if fit is None else fit[0] * 1e6


def drift_ppm(offset_a, t_a, offset_b, t_b):
    """Parts-per-million between two (offset, timestamp) samples.

    Positive = the DS3231 is running FAST relative to the host. Returns None
    for a baseline too short to divide by, rather than a huge meaningless
    number -- an early sample should read as "not yet known", not as a
    catastrophic drift figure.
    """
    elapsed = t_b - t_a
    if elapsed <= 0:
        return None
    return (offset_b - offset_a) / elapsed * 1e6


def collect(sda, scl, i2c_id, samples, mpremote=None):
    """Run the edge detector on-device, timestamping each line on arrival.

    Returns [(rtc_datetime, host_epoch_at_arrival), ...].
    """
    mpremote = str(mpremote or MPREMOTE)
    code = DEVICE_SNIPPET.format(sda=sda, scl=scl, i2c_id=i2c_id, samples=samples)
    proc = subprocess.Popen(
        [mpremote, "exec", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    out = []
    for line in proc.stdout:
        # Timestamp FIRST, parse after -- parsing before stamping would fold
        # this process's own work into the measurement.
        arrived = time.time()
        line = line.strip()
        if not line.startswith("EDGE "):
            continue
        raw = bytes.fromhex(line.split(None, 1)[1])
        out.append((decode_registers(raw), arrived))
    proc.wait()
    if proc.returncode != 0 and not out:
        sys.exit("mpremote failed:\n" + (proc.stderr.read() or "(no output)"))
    return out


def load_log(path):
    if not path.exists():
        return []
    with path.open() as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def append_log(path, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def current_epoch(entries):
    """Seeding the chip destroys the drift baseline, so samples are grouped
    into epochs and a seed starts a new one."""
    return max((e.get("epoch", 0) for e in entries), default=0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sda", type=int, default=DEFAULT_SDA)
    ap.add_argument("--scl", type=int, default=DEFAULT_SCL)
    ap.add_argument("--i2c-id", type=int, default=DEFAULT_ID)
    ap.add_argument("--samples", type=int, default=10,
                    help="seconds-edges to catch (1/sec). More = better "
                         "precision estimate, longer run. Default 10.")
    ap.add_argument("--mark-seed", action="store_true",
                    help="record that you just re-set the chip. Starts a new "
                         "epoch; earlier samples stop counting toward drift.")
    ap.add_argument("--log", type=Path, default=LOG_PATH)
    args = ap.parse_args(argv)

    entries = load_log(args.log)
    epoch = current_epoch(entries)

    if args.mark_seed:
        epoch += 1
        append_log(args.log, {"ts": time.time(), "event": "seed", "epoch": epoch,
                              "iso_host": datetime.now().isoformat(timespec="seconds")})
        print("Recorded a seed. New epoch %d -- drift now measures from the "
              "next sample onward." % epoch)
        return 0

    print("Catching %d seconds-edges on I2C%d (SDA=GP%d SCL=GP%d)..."
          % (args.samples, args.i2c_id, args.sda, args.scl))
    edges = collect(args.sda, args.scl, args.i2c_id, args.samples)
    if not edges:
        sys.exit("No edges seen. Is the DS3231 wired and powered? Try: make rtc-test")

    # datetime.timestamp() interprets the naive value in the HOST's local
    # zone. If the chip holds UTC that makes the offset a constant ~-9h,
    # which is fine -- see the header on why drift ignores constant bias.
    offsets = [dt.timestamp() - arrived for dt, arrived in edges]
    offset = statistics.median(offsets)
    jitter_ms = (statistics.stdev(offsets) * 1000) if len(offsets) > 1 else float("nan")
    now = time.time()

    entry = {"ts": now, "event": "sample", "epoch": epoch,
             "iso_host": datetime.now().isoformat(timespec="seconds"),
             "iso_rtc": edges[-1][0].isoformat(),
             "offset_s": round(offset, 4),
             "jitter_ms": round(jitter_ms, 1) if jitter_ms == jitter_ms else None,
             "samples": len(offsets)}
    append_log(args.log, entry)

    print("\n  DS3231 : %s" % edges[-1][0].isoformat())
    print("  host   : %s" % datetime.now().isoformat(timespec="seconds"))
    print("  offset : %+.3f s   (DS3231 minus host)" % offset)
    if jitter_ms == jitter_ms:
        print("  measurement precision: +/-%.0f ms  (spread over %d edges)"
              % (jitter_ms, len(offsets)))
    if abs(offset) > 1800:
        print("  note: that's near a whole number of hours -- the chip is "
              "probably\n        holding a different timezone than the host. "
              "Drift is unaffected.")

    prior = [e for e in entries if e.get("event") == "sample" and e.get("epoch") == epoch]
    if not prior:
        print("\n  Baseline recorded. Re-run in a few hours for a drift figure.")
        return 0

    base = prior[0]
    hours = (now - base["ts"]) / 3600
    series = [(e["ts"], e["offset_s"]) for e in prior] + [(now, offset)]
    ppm = drift_ppm_fit(series)
    print("\n  ── drift, over %.1f h since this epoch's baseline ──" % hours)
    if ppm is None:
        print("  baseline too recent to divide by.")
        return 0
    if len(series) >= 3:
        print("  %+.2f ppm   (%+.3f s/day)   [least-squares fit, %d samples]"
              % (ppm, ppm * 86400 / 1e6, len(series)))
    else:
        print("  %+.2f ppm   (%+.3f s/day)   [2 samples — a single host-clock"
              % (ppm, ppm * 86400 / 1e6))
        print("   adjustment would land entirely in this number. Sample again"
              "\n   for a fit that can average one out.]")

    # Don't let a short baseline masquerade as a measurement: at the observed
    # jitter, resolving 2 ppm needs enough elapsed time for real drift to
    # exceed the noise. Say so rather than printing a confident wrong number.
    rms = fit_rms_residual(series)
    if rms is not None and len(series) >= 3:
        print("  scatter about the fit: %.0f ms RMS  (jitter is ~%.0f ms)"
              % (rms * 1000, jitter_ms if jitter_ms == jitter_ms else 0))
        if jitter_ms == jitter_ms and rms * 1000 > 5 * jitter_ms:
            # Not describable by a constant drift. Say so instead of
            # printing a slope with a straight face.
            print("  ⚠ THAT SCATTER IS TOO LARGE TO BE THIS CHIP.")
            print("    Constant drift would put every sample on one line,")
            print("    scattered only by measurement jitter. %.0fx that means"
                  % (rms * 1000 / jitter_ms))
            print("    something else moved — almost certainly the HOST clock,")
            print("    which macOS steps against NTP. The slope above is not")
            print("    a property of the DS3231 yet.")
            need_h = (rms / 2e-6) / 3600
            print("    Fix is a LONGER span, not more samples: drift has to")
            print("    outgrow ~%.0f ms of reference noise. Resolving 2 ppm"
                  % (rms * 1000,))
            print("    needs ~%.0f h; five-to-one confidence, ~%.0f h."
                  % (need_h, 5 * need_h))
            return 0

    if jitter_ms == jitter_ms and jitter_ms > 0:
        need_h = (jitter_ms / 1000) / 2e-6 / 3600
        if hours < need_h:
            print("  ⚠ baseline too short to trust at the +/-2 ppm level --")
            print("    need roughly %.1f h at this precision, have %.1f h."
                  % (need_h, hours))
        else:
            aging = int(round(ppm / 0.1))
            print("  Baseline is long enough to be meaningful at 2 ppm.")
            if aging:
                print("  To trim: the aging register (0x10, signed, ~0.1 ppm/LSB)")
                print("  would want about %+d. Positive slows the oscillator --" % aging)
                print("  confirm the sign against the datasheet before writing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
