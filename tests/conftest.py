"""Shared test scaffolding.

main.py is device firmware: it imports `machine` / `neopixel` (MicroPython
built-ins) and a project `config` module, and instantiates a NeoPixel at import
time. To exercise the *logic* on a host we install tiny fakes for the device
modules, then import main with a controlled fake config.

The `load_main` fixture returns a factory: call it with config overrides and it
re-imports a fresh `main` whose module-level constants reflect that config.
"""

import os
import sys
import types

import pytest

MICROPYTHON_DIR = os.path.join(os.path.dirname(__file__), "..", "micropython")


def _install_device_fakes():
    """Stand-ins for the MicroPython-only modules main.py imports."""
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


@pytest.fixture
def load_main():
    def _load(**overrides):
        _install_device_fakes()
        cfg = types.ModuleType("config")
        for key, value in {**DEFAULT_CONFIG, **overrides}.items():
            setattr(cfg, key, value)
        sys.modules["config"] = cfg
        sys.modules.pop("main", None)  # force a fresh import each call
        if MICROPYTHON_DIR not in sys.path:
            sys.path.insert(0, MICROPYTHON_DIR)
        import importlib
        return importlib.import_module("main")

    return _load
