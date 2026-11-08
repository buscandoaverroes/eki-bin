"""scripts/host_fakes.py — run firmware modules on the Mac.

The firmware imports MicroPython-only modules (`machine`, `neopixel`,
`network`, `ntptime`, gc.mem_free) and builds a NeoPixel at import time. To
exercise its LOGIC on a host we install tiny stand-ins first. Shared by the
test suite (tests/conftest.py) and the replay harness (scripts/replay.py) so
the two can never disagree about what "the firmware on a host" means.
"""

import sys
import types


def install_device_fakes():
    """Stand-ins for the MicroPython-only modules main.py imports."""
    # gc.mem_free/mem_alloc are MicroPython-only additions to the stdlib gc
    # module — CPython has neither. main.py's memory instrumentation
    # (docs/insights.md §11) calls them, so add them here rather than making
    # production code defend against being run on a host it never runs on.
    # Fixed values: these exist so the plumbing is exercisable, not to
    # simulate real allocation — tests that care about deltas inject their
    # own marks.
    import gc as _gc
    if not hasattr(_gc, "mem_free"):
        _gc.mem_free = lambda: 400_000
        _gc.mem_alloc = lambda: 100_000
    for name in ("network", "ntptime"):
        sys.modules[name] = types.ModuleType(name)

    machine = types.ModuleType("machine")

    class Pin:
        OUT = 0
        IN = 1

        def __init__(self, *a, **k):
            pass

        def value(self, *a):
            return 0

    machine.Pin = Pin

    class I2C:
        """Stand-in for the IMU HAL (docs/contracts/gesture-envelope.md §2).
        Only main.py's import-time `I2C(...)` construction needs to succeed
        for tests — the HAL functions that actually call scan()/
        readfrom_mem() are real hardware I/O, not host-tested, same
        limitation _imu_tap_detected() already has. Safe no-op defaults
        (empty scan, zeroed reads) so nothing errors if a test happens to
        exercise this path indirectly."""

        def __init__(self, *a, **k):
            pass

        def scan(self):
            return []

        def readfrom_mem(self, addr, reg, nbytes):
            return bytes(nbytes)

        def writeto_mem(self, addr, reg, data):
            pass

    machine.I2C = I2C
    sys.modules["machine"] = machine

    neopixel = types.ModuleType("neopixel")

    class NeoPixel:
        """Records writes into a list so tests can assert on the framebuffer."""

        def __init__(self, pin, n):
            self.n = n
            self.buf = [(0, 0, 0)] * n

        def __setitem__(self, i, v):
            self.buf[i] = v

        def __getitem__(self, i):
            return self.buf[i]

        def write(self):
            pass

    neopixel.NeoPixel = NeoPixel
    sys.modules["neopixel"] = neopixel
