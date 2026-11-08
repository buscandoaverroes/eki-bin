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


def test_geometry_fits_the_configured_strip(load_main):
    """ANCHOR_INDEX/ARM_*_LEN must fit NUM_LEDS in the REAL config.py.

    `make upload` runs `make test` first, so this stops a broken geometry
    reaching hardware. It exists because the failure is so badly signposted:
    on 2026-08-23 a 21-LED geometry on an 8-LED strip booted cleanly, read
    the right time, printed the right timetable, and only then died with a
    bare `IndexError: list index out of range` three calls deep in the
    render loop. Nothing in that pointed at config.py.

    Only checked for ApproachContract — it is the sole consumer of the
    anchor/arm geometry, so a mismatch is harmless under an arc contract.
    """
    cfg = _real_config()
    m = load_main()
    if getattr(cfg, "CONTRACT", None) != "approach":
        pytest.skip("geometry only applies to ApproachContract")
    n = getattr(cfg, "NUM_LEDS", None)
    if n is None:
        pytest.skip("NUM_LEDS not set in config.py")
    problems = m.geometry_problems(
        num_leds=n,
        anchor=getattr(cfg, "ANCHOR_INDEX", 0),
        arm_a=getattr(cfg, "ARM_A_LEN", n - 1),
        arm_b=getattr(cfg, "ARM_B_LEN", 0),
    )
    assert problems == [], "config.py geometry doesn't fit: " + "; ".join(problems)
