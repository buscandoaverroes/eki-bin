"""Sanity-check the *actual* micropython/config.py (if present).

Catches the kind of typo that silently falls back to a default — e.g.
CONTRACT="breathng" → SandTimer with no warning. Validates selector strings
against main.py's real registries so this can't drift out of sync.

Only display fields are inspected; WiFi credentials are never read or asserted on.
Skips if config.py doesn't exist (it's gitignored).
"""

import importlib.util
import os

import pytest

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "micropython", "config.py"
)


def _real_config():
    if not os.path.exists(CONFIG_PATH):
        pytest.skip("micropython/config.py not present (gitignored)")
    spec = importlib.util.spec_from_file_location("real_config", CONFIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selectors_are_known(load_main):
    cfg = _real_config()
    m = load_main()  # source of truth for the registries
    if hasattr(cfg, "CONTRACT"):
        assert cfg.CONTRACT in m.CONTRACTS, f"unknown CONTRACT {cfg.CONTRACT!r}"
    if hasattr(cfg, "COLOR_SCHEME"):
        assert cfg.COLOR_SCHEME in m.SCHEMES, f"unknown COLOR_SCHEME {cfg.COLOR_SCHEME!r}"
    if hasattr(cfg, "ARC_ORIGIN"):
        assert cfg.ARC_ORIGIN in {"near", "far"}, f"bad ARC_ORIGIN {cfg.ARC_ORIGIN!r}"


def test_heartbeat_pin_not_a_null_like_string():
    # Real bug this caught: HEARTBEAT_PIN = "none" is a truthy STRING, not
    # Python's None, and would try Pin("none", Pin.OUT) on the device instead
    # of disabling the heartbeat. Easy typo — many config formats spell their
    # null literal as a bare word, unlike Python.
    cfg = _real_config()
    if hasattr(cfg, "HEARTBEAT_PIN") and isinstance(cfg.HEARTBEAT_PIN, str):
        assert cfg.HEARTBEAT_PIN.lower() not in ("none", "null", ""), (
            f"HEARTBEAT_PIN = {cfg.HEARTBEAT_PIN!r} looks like an attempt to "
            "write Python's None as a string — use bare None (no quotes) to "
            "disable the heartbeat, or a real pin name/GPIO number."
        )


def test_numeric_ranges_sane():
    cfg = _real_config()
    if hasattr(cfg, "BRIGHTNESS"):
        assert 0.0 <= cfg.BRIGHTNESS <= 1.0
    if hasattr(cfg, "URGENCY_THRESHOLDS"):
        t = cfg.URGENCY_THRESHOLDS
        assert len(t) == 2 and t[0] < t[1], f"thresholds not ascending: {t}"
    for attr in ("QUIET_START_HOUR", "QUIET_END_HOUR"):
        if hasattr(cfg, attr):
            assert 0 <= getattr(cfg, attr) <= 24
