"""micropython/gesture_sandbox.py's tunable brightness constants —
docs/contracts/gesture-envelope.md §11's "hardware-defined software" tap-
strength mapping (ACK_PEAK_FLOOR/CEIL, SHELF_FLOOR/CEIL).

Real-hardware testing (2026-08-16) found a real bug that these tests exist
to catch mechanically instead of by hand next time: ACK_PEAK_CEIL=10.0
silently clamped every channel to 255 for any strength above ~65%, making
e.g. a strength=0.7 and a strength=1.0 tap render as identical pure white.
Saturation is a pure property of the constants + main.py's configured
BRIGHTNESS/STARTUP_COLOR — fully checkable without real hardware, unlike
whether real taps' `dev` values actually CLUSTER in practice (that depends
on human tap force, not something a unit test can know — left as an
empirical, on-hardware thing per gesture-envelope.md §11, not tested here).

gesture_sandbox.py does `import main` at module scope, so importing it
picks up whatever `main` is already in sys.modules — load_main() (see
conftest.py) installs a fresh one with a controlled config first.
"""

import importlib
import sys


def _load_gesture_sandbox(load_main, **config_overrides):
    load_main(**config_overrides)
    sys.modules.pop("gesture_sandbox", None)  # force a fresh import each call
    return importlib.import_module("gesture_sandbox")


def test_shelf_stays_below_ack_peak_floor(load_main):
    """The shelf (the 'still deciding' cue) must never blur into the ACK
    flash itself — see gesture_sandbox.py's SHELF_CEIL comment. A
    regression here would mean a light tap's shelf could look as bright
    as, or brighter than, a light tap's own ACK peak."""
    gs = _load_gesture_sandbox(load_main)
    assert gs.SHELF_CEIL < gs.ACK_PEAK_FLOOR


def test_ack_peak_ceiling_does_not_saturate(load_main):
    """The real bug: ACK_PEAK_CEIL too high relative to BRIGHTNESS clamps
    a channel to 255 well before strength=1.0, so hard taps of genuinely
    different force render identically. Checked against whatever
    BRIGHTNESS/STARTUP_COLOR main.py is actually configured with, not a
    hardcoded assumption — this is exactly what varied between the bare-
    strip and in-bottle rounds in gesture-envelope.md §11."""
    gs = _load_gesture_sandbox(load_main, BRIGHTNESS=0.15)
    assert not gs._would_saturate(gs.ACK_PEAK_CEIL)


def test_ack_peak_ceiling_saturates_when_pushed_too_far(load_main):
    """Sanity-checks _would_saturate itself against the actual historical
    bug value (10.0 at BRIGHTNESS=0.15 clamps at mult~6.67) — if this
    ever stopped detecting the known-bad case, the test above would be
    trivially passing for the wrong reason."""
    gs = _load_gesture_sandbox(load_main, BRIGHTNESS=0.15)
    assert gs._would_saturate(10.0)


def test_ack_peak_range_has_a_meaningful_spread(load_main):
    """Guards the OTHER direction: the original bug was a 2x linear
    spread (0.5-1.0) that wasn't perceptible at all. Not a precise
    number — perceptibility isn't something a unit test can judge — just
    a sanity floor so a future edit can't silently narrow this back down."""
    gs = _load_gesture_sandbox(load_main)
    assert gs.ACK_PEAK_CEIL / gs.ACK_PEAK_FLOOR >= 3.0


def test_tap_strength_clamps_to_unit_range(load_main):
    gs = _load_gesture_sandbox(load_main)
    assert gs._tap_strength(gs.STRENGTH_MIN_DEV_MG - 100) == 0.0
    assert gs._tap_strength(gs.STRENGTH_MIN_DEV_MG) == 0.0
    assert gs._tap_strength(gs.STRENGTH_MAX_DEV_MG) == 1.0
    assert gs._tap_strength(gs.STRENGTH_MAX_DEV_MG + 1000) == 1.0


def test_tap_strength_is_monotonic(load_main):
    """A harder tap should never read as an equal-or-lower strength than
    a lighter one — the whole premise of the strength-scaled ACK/shelf."""
    gs = _load_gesture_sandbox(load_main)
    devs = [0, 50, 100, 200, 300, 400, 500]
    strengths = [gs._tap_strength(d) for d in devs]
    assert strengths == sorted(strengths)
