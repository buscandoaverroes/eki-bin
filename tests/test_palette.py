"""palette_problems() — docs/palette-model.md proposal B.

Every case here is a bug that actually shipped, or one the same
arithmetic makes possible. None of them ever raised an exception; they
produced a wrong-looking jar, which is why a checker exists at all.
"""

import importlib
import sys


def _load(load_main, **overrides):
    load_main(**overrides)
    sys.modules.pop("palette", None)
    return importlib.import_module("palette")


def _names(problems):
    return " | ".join(problems)


# ── the floor ────────────────────────────────────────────────────


def test_the_original_marker_bug_is_caught(load_main):
    """MARKER_COLOR 80 × BRIGHTNESS 0.15 × MARKER_BRIGHTNESS 0.15 = raw 1,
    which is exactly where WS2812B channel matching collapses and neutral
    reads RED. It took weeks to diagnose on hardware (insights §12)."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.15, MARKER_BRIGHTNESS=0.15,
              DAY_NIGHT_ENABLED=False, TILT_ENABLED=False)
    probs = p.palette_problems()
    assert any("marker" in x and "floor" in x for x in probs), _names(probs)


def test_the_shipping_default_is_clean(load_main):
    """0.25 was chosen to give raw 3 at BRIGHTNESS 0.15 — the measured
    floor. If this ever fails, either the default moved or the floor did."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.15, MARKER_BRIGHTNESS=0.25,
              DAY_NIGHT_ENABLED=False, TILT_ENABLED=False)
    assert p.palette_problems() == []


def test_a_deliberately_dark_channel_is_not_a_problem(load_main):
    """LINE_COLOR (34,139,34) has no dark channel, but a pure-red line
    would — and a channel that is SUPPOSED to be off is not broken for
    being off. Without this the checker would cry wolf on every saturated
    colour anyone picks."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.5, LINE_COLOR=(255, 0, 0),
              MARKER_BRIGHTNESS=0.25, DAY_NIGHT_ENABLED=False,
              TILT_ENABLED=False, N_TRAINS=1)
    assert not any("train" in x and "floor" in x for x in p.palette_problems())


# ── clipping, and the hue shift it causes ────────────────────────


def test_the_anchor_clip_is_caught_and_named_as_a_hue_shift(load_main):
    """ANCHOR_BRIGHTNESS 1.6 × 0.85 clips R and G but not B, so the anchor
    does not merely stop getting brighter — it turns pale. Reporting it as
    "clipping" would understate what actually goes wrong."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.85, DAY_NIGHT_ENABLED=False,
              TILT_ENABLED=False)
    probs = p.palette_problems()
    assert any("anchor" in x and "HUE shifts" in x for x in probs), _names(probs)


def test_total_clipping_is_reported_differently(load_main):
    """All three channels clipping is a different failure from some of
    them: the role stops being distinguishable by colour at all, rather
    than shifting to a different one."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=1.0, ANCHOR_COLOR=(255, 255, 255),
              ANCHOR_BRIGHTNESS=2.0, DAY_NIGHT_ENABLED=False,
              TILT_ENABLED=False)
    assert any("white" in x for x in p.palette_problems())


# ── the check a human cannot do by inspection ────────────────────


def test_every_reachable_brightness_is_swept(load_main):
    """THE point of the module. A config can be perfectly valid at
    NIGHT_BRIGHTNESS and broken at DAY_BRIGHTNESS, and nobody reads a
    config at two brightnesses at once — which is how the anchor bug
    survived being looked at."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.45, DAY_NIGHT_ENABLED=True,
              DAY_BRIGHTNESS=0.90, NIGHT_BRIGHTNESS=0.45, TILT_ENABLED=False)
    probs = p.palette_problems()
    assert any("DAY_BRIGHTNESS" in x for x in probs), _names(probs)
    assert not any("NIGHT_BRIGHTNESS" in x for x in probs), _names(probs)


def test_the_tilt_rails_are_swept_too(load_main):
    """Found live on bottle-01: TILT_MIN/MAX were chosen as "never fully
    off" and "not blinding", with no reference to the palette — so tilt
    could drive BRIGHTNESS to 0.90 (anchor pale) or 0.05 (markers at raw
    1, the original bug) even after DAY_BRIGHTNESS had been fixed."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.5,
              DAY_NIGHT_ENABLED=False, TILT_ENABLED=True,
              TILT_MIN_BRIGHT=0.05, TILT_MAX_BRIGHT=0.90)
    probs = p.palette_problems()
    assert any("TILT_MAX_BRIGHT" in x for x in probs), _names(probs)
    assert any("TILT_MIN_BRIGHT" in x for x in probs), _names(probs)


# ── safe_range ───────────────────────────────────────────────────


def test_safe_range_names_what_binds_each_end(load_main):
    """A window alone is not actionable — you need to know which role to
    change. bottle-01's is 0.15-0.62, floored by the marker and capped by
    the anchor."""
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.5, N_TRAINS=2,
              MARKER_BRIGHTNESS=0.25)
    lo, lo_why, hi, hi_why = p.safe_range()
    assert 0.14 < lo < 0.16 and "marker" in lo_why
    assert 0.62 < hi < 0.63 and "anchor" in hi_why


def test_roles_are_per_contract(load_main):
    """ApproachContract paints every train at 1.0 and owns the anchor and
    markers; the arc contracts dim each layer by BACKGROUND_BRIGHTNESS and
    have neither. Reporting arc roles under approach gave a usable-window
    floor of 0.25 for a config whose real floor is 0.15 — a checker being
    confidently wrong, which is worse than not having one."""
    ap = _load(load_main, CONTRACT="approach", N_TRAINS=2)
    names = [r[0] for r in ap.roles()]
    assert "anchor" in names and "marker" in names
    assert not any("#" in n for n in names), names

    arc = _load(load_main, CONTRACT="sandtimer", N_TRAINS=2)
    names = [r[0] for r in arc.roles()]
    assert "anchor" not in names and "marker" not in names
    assert any("#" in n for n in names), names


def test_a_config_inside_its_own_safe_range_is_clean(load_main):
    p = _load(load_main, CONTRACT="approach", BRIGHTNESS=0.45, DAY_NIGHT_ENABLED=True,
              DAY_BRIGHTNESS=0.60, NIGHT_BRIGHTNESS=0.30,
              TILT_ENABLED=True, TILT_MIN_BRIGHT=0.30, TILT_MAX_BRIGHT=0.60)
    assert p.palette_problems() == []


def test_an_impossible_palette_is_reported_as_impossible(load_main):
    """If the floor needs more brightness than the ceiling allows, no
    value works and saying "out of range" would send someone tuning
    forever."""
    p = _load(load_main, CONTRACT="sandtimer", N_TRAINS=4,
              BACKGROUND_BRIGHTNESS=0.001, LINE_COLOR=(34, 139, 34))
    lo, _lw, hi, _hw = p.safe_range()
    assert lo > hi
    assert any("NO usable BRIGHTNESS" in line for line in p.describe())


def test_the_ack_shelf_is_checked_and_is_gamma_corrected(load_main):
    """The role that hid for months. The ACK shelf is the one entry that
    is BOTH a product of config values AND rendered on the animated path,
    so its output is BRIGHTNESS × mult**GAMMA rather than BRIGHTNESS ×
    mult. At the old SHELF_FLOOR of 0.08 and BRIGHTNESS 0.50 that is raw
    0.49 — below a single output code, so it either vanished (DITHER off)
    or sparkled across the whole strip for the 1.2s capture window
    (DITHER on). Nothing checked it, so nobody knew."""
    p = _load(load_main, CONTRACT="approach", GESTURE_ENABLED=True,
              BRIGHTNESS=0.50, SHELF_FLOOR=0.08,
              DAY_NIGHT_ENABLED=False, TILT_ENABLED=False)
    probs = p.palette_problems()
    assert any("ACK shelf" in x and "floor" in x for x in probs), probs


def test_the_raised_shelf_clears_the_floor(load_main):
    p = _load(load_main, CONTRACT="approach", GESTURE_ENABLED=True,
              BRIGHTNESS=0.50, SHELF_FLOOR=0.20,
              DAY_NIGHT_ENABLED=False, TILT_ENABLED=False)
    assert not any("ACK shelf" in x for x in p.palette_problems())


def test_no_ack_role_when_gestures_are_off(load_main):
    p = _load(load_main, CONTRACT="approach", GESTURE_ENABLED=False)
    assert not any("ACK" in r[0] for r in p.roles())
