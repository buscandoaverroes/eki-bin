"""Shared test scaffolding.

main.py is device firmware: it imports `machine` / `neopixel` (MicroPython
built-ins) and a project `config` module, and instantiates a NeoPixel at import
time. To exercise the *logic* on a host we install tiny fakes for the device
modules, then import main with a controlled fake config.

The `load_main` fixture returns a factory: call it with config overrides and it
re-imports a fresh `main` whose module-level constants reflect that config.
"""

import ast
import os
import sys
import types

import pytest

MICROPYTHON_DIR = os.path.join(os.path.dirname(__file__), "..", "micropython")


def _install_device_fakes():
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


# A complete, valid baseline config. Tests override only what they care about.
DEFAULT_CONFIG = dict(
    WIFI_SSID="test", WIFI_PASS="test",
    UTC_OFFSET_HOURS=9, LOOP_INTERVAL_SECS=30, SCHEDULE_FILE="schedule.json",
    DISPLAY_DIRECTION="b", WALK_TO_STATION_MINS=2.5,
    LED_PIN=6, NUM_LEDS=8, ARC_ORIGIN="near",
    BRIGHTNESS=0.15, CONTRACT="sandtimer", COLOR_SCHEME="default",
    MINUTES_PER_LED=1, URGENCY_THRESHOLDS=(2, 5),
    QUIET_START_HOUR=23, QUIET_END_HOUR=6,
)


def _firmware_module_names():
    """Module names importable from micropython/ — i.e. the firmware."""
    return [f[:-3] for f in os.listdir(MICROPYTHON_DIR) if f.endswith(".py")]



# Modules the facade may resolve names from. Deliberately NOT every .py in
# micropython/:
#   • `config` is the test stub, not the real file — parsing the real one
#     from disk maps names to a module that doesn't have them at runtime.
#   • Bring-up scripts are standalone, run via `mpremote run`, and define
#     colliding names of their own (led_test.py has its own clear() and
#     BRIGHTNESS). They are never imported by main.py.
_STANDALONE = {"config", "config_friend1", "led_test", "led_sandbox",
               "imu_test", "i2c_scan", "rtc_test", "gesture_sandbox",
               "vibration_sandbox", "handling_test", "orientation_test",
               "low_pwm_test"}


def _importable_firmware():
    return [n for n in _firmware_module_names() if n not in _STANDALONE]


class _Firmware:
    """Attribute access across every firmware module, as one namespace.

    V1.6 split main.py into eleven modules (docs/v1.6-refactor.md). The 278
    tests reach through the module object for 99 names, 97 of which no
    longer live in main.py — so without this every one of them would have
    to name its module, and the extraction could not be verified against an
    unchanged suite.

    Resolution goes to the module that DEFINES a name, not merely one that
    imported it. That distinction is load-bearing: an imported name is a
    COPY taken at import time, so for anything mutable at runtime (notably
    settings.BRIGHTNESS, which _cycle_brightness rebinds) a copy is a stale
    snapshot. Resolving to the owner means a test always sees the live
    value — the bug that cost this branch a debugging session.
    """

    def __init__(self, main):
        self._main = main
        self._owner = {}
        for name in _importable_firmware():
            mod = sys.modules.get(name)
            if mod is None:
                continue
            for attr in _defined_in(name):
                self._owner.setdefault(attr, mod)

    def __getattr__(self, name):
        owner = self._owner.get(name)
        if owner is not None:
            return getattr(owner, name)
        try:
            return getattr(self._main, name)          # main's own + imports
        except AttributeError:
            pass
        for mod_name in _importable_firmware():       # last resort
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(
            "no firmware module defines %r (searched main + %s)"
            % (name, ", ".join(_importable_firmware())))


_DEFINED_CACHE = {}


def _defined_in(module_name):
    """Top-level names a module DEFINES (not ones it imports). Cached —
    load_main runs once per test and re-parsing eleven files each time was
    tripling the suite's runtime."""
    if module_name in _DEFINED_CACHE:
        return _DEFINED_CACHE[module_name]
    path = os.path.join(MICROPYTHON_DIR, module_name + ".py")
    try:
        tree = ast.parse(open(path).read())
    except (OSError, SyntaxError):
        _DEFINED_CACHE[module_name] = set()
        return _DEFINED_CACHE[module_name]
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    _DEFINED_CACHE[module_name] = out
    return out


@pytest.fixture
def load_main():
    def _load(**overrides):
        _install_device_fakes()
        cfg = types.ModuleType("config")
        for key, value in {**DEFAULT_CONFIG, **overrides}.items():
            setattr(cfg, key, value)
        # Drop EVERY firmware module, not just `main`. As V1.6 splits
        # main.py apart (docs/v1.6-refactor.md), a cached `settings` would
        # keep the previous call's config values while `main` re-imported
        # fresh — so overrides would silently have no effect and the test
        # would pass against the wrong numbers. Discovered from the
        # directory so future extractions need no change here.
        for _name in _firmware_module_names():
            sys.modules.pop(_name, None)
        sys.modules["config"] = cfg  # after the purge: config lives there too
        if MICROPYTHON_DIR not in sys.path:
            sys.path.insert(0, MICROPYTHON_DIR)
        import importlib
        main = importlib.import_module("main")
        return _Firmware(main)

    return _load
