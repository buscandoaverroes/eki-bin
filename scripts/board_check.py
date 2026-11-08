#!/usr/bin/env python3
"""scripts/board_check.py — is this board healthy enough to trust?

Run it:  make doctor

═══ WHY ════════════════════════════════════════════════════════════════
2026-08-24 produced three separate littlefs corruptions, each presenting
differently, and one of them (docs/insights.md §13) passed every check we
had: the filesystem mounted, sizes were correct, and a module read back as
the filesystem's own superblock. The failure surfaced as a SyntaxError in
firmware source that was perfectly fine.

So "it booted" is not evidence of a healthy board. This exercises the parts
that actually broke, with disposable data, BEFORE real firmware goes on.

═══ THE DISCRIMINATOR ══════════════════════════════════════════════════
Two write tests that differ in ONE respect:

  LOCAL     the device writes a file itself, then hashes it back.
            Exercises flash + littlefs. No serial transfer involved.

  TRANSFER  the host sends a file via `mpremote cp`, then the device
            hashes it. Exercises flash + littlefs + the serial transport.

    LOCAL ok, TRANSFER fails  → the transport is the problem
    LOCAL fails               → flash or filesystem is the problem
    both ok                   → the board is fine; look elsewhere

That split is the thing we could not make all day, because every failure
was observed through a full firmware upload where both were in play.

Nothing here is left behind: every temp file is deleted, pass or fail.
"""

import hashlib
import os
import subprocess
import sys
import tempfile

MPREMOTE = os.environ.get("MPREMOTE", ".venv/bin/mpremote")
# Sizes chosen to bracket the real firmware: diag.py is ~4KB, settings.py
# ~23KB, gestures.py ~40KB. settings.py is the one that has failed most.
SIZES = [(4 * 1024, "4KB"), (24 * 1024, "24KB"), (40 * 1024, "40KB")]

DIGEST_SNIPPET = """
def _digest(path):
    import os
    n = os.stat(path)[6]
    try:
        import hashlib, binascii
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                b = f.read(1024)
                if not b: break
                h.update(b)
        return '%d:sha256:%s' % (n, binascii.hexlify(h.digest()).decode())
    except (ImportError, AttributeError):
        t = 0
        with open(path, 'rb') as f:
            while True:
                b = f.read(1024)
                if not b: break
                t = (t + sum(b)) & 0xFFFFFFFF
        return '%d:sum:%d' % (n, t)
"""


def run(code, timeout=60):
    try:
        r = subprocess.run([MPREMOTE, "exec", code],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT after %ds" % timeout, 1
    except FileNotFoundError:
        sys.exit("✗ mpremote not found at %s — run `make setup`" % MPREMOTE)


def host_digest(data):
    return "%d:sha256:%s" % (len(data), hashlib.sha256(data).hexdigest())


def host_digest_sum(data):
    t = 0
    for i in range(0, len(data), 1024):
        t = (t + sum(data[i:i + 1024])) & 0xFFFFFFFF
    return "%d:sum:%d" % (len(data), t)


def matches(data, got):
    if ":sha256:" in got:
        return host_digest(data) == got
    if ":sum:" in got:
        return host_digest_sum(data) == got
    return False


def pattern(n):
    """Deterministic, non-repeating-ish bytes. A constant fill would hide
    an aliasing fault that returns the wrong block but the right length —
    which is precisely the corruption seen on 2026-08-24."""
    return bytes(((i * 37 + (i >> 8) * 11 + 13) & 0xFF) for i in range(n))


def main():
    print("\n══ eki-bin board check ═══════════════════════════════════")
    failures = []

    # ── 1. reachable ──────────────────────────────────────────────
    out, err, rc = run("print('alive')", timeout=20)
    if out != "alive":
        print("  ✗ device not answering (%s)" % (err or out or "no output"))
        print("\n  A device node can exist while MicroPython is NOT running —")
        print("  a filesystem too damaged to mount hangs _boot.py before the")
        print("  REPL starts. See docs/insights.md §13; recover with:")
        print("    make flash-micropython BOARD=<board> WIPE=1")
        return 1
    print("  ✓ device answering")

    # ── 2. identity ───────────────────────────────────────────────
    out, _, _ = run("import os; u = os.uname(); print(u.machine); print(u.release)")
    for lineno, label in enumerate(("board  ", "firmware")):
        parts = out.split("\n")
        if lineno < len(parts):
            print("    %s %s" % (label, parts[lineno].strip()))

    # ── 3. filesystem ─────────────────────────────────────────────
    out, _, _ = run("import os; s = os.statvfs('/'); "
                    "print(s[0]*s[2]); print(s[0]*s[3]); print(len(os.listdir()))")
    try:
        total, free, nfiles = (int(x) for x in out.split("\n")[:3])
        print("  ✓ filesystem mounts — %d KB free of %d KB, %d files"
              % (free // 1024, total // 1024, nfiles))
        # A filesystem larger than the physical flash is a KNOWN firmware
        # defect, not a curiosity: the XIAO RP2350 board header declared
        # PICO_FLASH_SIZE_BYTES as 4MB against a 2MB part
        # (raspberrypi/pico-sdk#2834), which propagated into MicroPython's
        # partition sizing (micropython/micropython#18839). Fixed in
        # pico-sdk 2.3.0 plus a follow-up that trims the filesystem to
        # 1408k — after the v1.28.0 (2026-04-06) build. A board reporting
        # 3072 KB is running firmware that predates the fix.
        if total > 2048 * 1024:
            print("    ⚠ %d KB is LARGER THAN THE 2MB FLASH ON THIS BOARD."
                  % (total // 1024))
            print("      Known defect — pico-sdk#2834 / micropython#18839.")
            print("      Fixed after v1.28.0; a corrected build reports ~1408 KB.")
            print("      Flash a newer firmware before trusting this board:")
            print("        make flash-micropython BOARD=xiao-rp2350 WIPE=1")
            failures.append("filesystem larger than physical flash")
    except ValueError:
        print("  ✗ could not read filesystem stats: %r" % out)
        failures.append("filesystem stats")

    # ── 4. memory ─────────────────────────────────────────────────
    out, _, _ = run("import gc; gc.collect(); print(gc.mem_free())")
    try:
        print("  ✓ heap — %d KB free" % (int(out) // 1024))
    except ValueError:
        print("  ⚠ could not read heap: %r" % out)

    # ── 5. LOCAL writes: flash + littlefs, no transfer ────────────
    print("\n  ── local write/read (flash + filesystem only) ──")
    for n, label in SIZES:
        name = "_bc_local.tmp"
        code = DIGEST_SNIPPET + """
n = %d
with open('%s', 'wb') as f:
    i = 0
    while i < n:
        chunk = bytes((((j * 37 + (j >> 8) * 11 + 13) & 0xFF)
                       for j in range(i, min(i + 1024, n))))
        f.write(chunk)
        i += 1024
print(_digest('%s'))
""" % (n, name, name)
        out, err, _ = run(code, timeout=120)
        ok = matches(pattern(n), out.split("\n")[-1] if out else "")
        print("    %-6s %s" % (label, "✓ intact" if ok else "✗ MISMATCH  %s" % (err or out)))
        if not ok:
            failures.append("local write %s" % label)
        run("import os\ntry:\n    os.remove('%s')\nexcept OSError:\n    pass" % name)

    # ── 6. TRANSFER writes: adds the serial path ──────────────────
    print("\n  ── host transfer (adds the serial transport) ──")
    for n, label in SIZES:
        name = "_bc_xfer.tmp"
        data = pattern(n)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            fh.write(data)
            tmp = fh.name
        try:
            r = subprocess.run([MPREMOTE, "cp", tmp, ":" + name],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                print("    %-6s ✗ TRANSFER FAILED  %s"
                      % (label, (r.stderr or "").strip().split("\n")[-1]))
                failures.append("transfer %s" % label)
                continue
            out, err, _ = run(DIGEST_SNIPPET + "print(_digest('%s'))" % name,
                              timeout=120)
            ok = matches(data, out.split("\n")[-1] if out else "")
            print("    %-6s %s" % (label, "✓ intact" if ok
                                   else "✗ MISMATCH — content differs after transfer"))
            if not ok:
                failures.append("transfer %s" % label)
        except subprocess.TimeoutExpired:
            print("    %-6s ✗ TIMEOUT" % label)
            failures.append("transfer %s" % label)
        finally:
            os.unlink(tmp)
            run("import os\ntry:\n    os.remove('%s')\nexcept OSError:\n    pass" % name)

    # ── verdict ───────────────────────────────────────────────────
    print("\n  ─────────────────────────────────────────────────────")
    if not failures:
        print("  ✓ HEALTHY — flash, filesystem and transport all intact.")
        print("    Safe to `make upload`.")
        return 0

    local = [f for f in failures if f.startswith("local")]
    xfer = [f for f in failures if f.startswith("transfer")]
    print("  ✗ %d check(s) failed: %s" % (len(failures), ", ".join(failures)))
    if local:
        print("\n  LOCAL writes failed — the flash or filesystem is the problem,")
        print("  not the serial link. Wipe before trusting this board:")
        print("    make flash-micropython BOARD=<board> WIPE=1")
    elif xfer:
        print("\n  Local writes were fine but transfers were not, so flash and")
        print("  littlefs are healthy and THE TRANSPORT is at fault. Board")
        print("  position, cable and USB port have all been ruled out before")
        print("  (insights.md §13) — capture `mpremote --verbose` output next,")
        print("  rather than swapping hardware again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
