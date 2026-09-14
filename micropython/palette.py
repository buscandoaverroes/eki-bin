# micropython/palette.py — eki-bin
#
# Does this config actually render correctly, at every brightness the unit
# can reach? Proposal B of docs/palette-model.md.
#
# ⚠ WHAT THIS IS FOR. Four palette bugs have shipped, and not one of them
# raised an exception — they produced a wrong-looking jar:
#
#   MARKER_BRIGHTNESS 0.15 x BRIGHTNESS 0.15 x 80  = raw 1  → ticks read RED
#   MARKER_BRIGHTNESS = 0                          → set to hide the above
#   ANCHOR_BRIGHTNESS 1.6 x BRIGHTNESS 0.85        → (255,255,163), not
#                                                     (255,200,120): the
#                                                     channels clip at
#                                                     DIFFERENT points, so
#                                                     the HUE shifts
#   "# = raw 3" comments                           → true once, then not
#
# Every one is a product of numbers set in different places, and the
# product appears nowhere. This is `geometry_problems()` applied to colour:
# same shape of bug (silent, surfacing nowhere near config.py), same shape
# of fix (a pure function returning reasons, checked at boot).
#
# ⚠ ALL THE CONTRACTS PAINT THESE ROLES ON THE **STATIC** PATH
# (`(color, mult, "static")`), which is `BRIGHTNESS * mult` with NO gamma.
# If a role ever moves to the animated path the arithmetic here changes —
# gamma(mult) for mult > 1 grows FASTER than mult, so an anchor would clip
# far earlier than these numbers say. Checked at the time of writing:
# contracts.py paints train, marker and anchor all static.

from settings import (ANCHOR_BRIGHTNESS, ANCHOR_COLOR, BACKGROUND_BRIGHTNESS,
    BRIGHTNESS, CONTRACT_NAME, DAY_BRIGHTNESS, DAY_NIGHT_ENABLED, LINE_COLOR,
    LOW_PWM_FLOOR, MARKER_BRIGHTNESS, MARKER_COLOR, NIGHT_BRIGHTNESS,
    N_TRAINS, SHELF_FLOOR, STARTUP_COLOR, TILT_ENABLED,
    TILT_MAX_BRIGHT, TILT_MIN_BRIGHT, WAKE_INTERACTION_ENABLED)
from primitives import gamma

_CH = ("R", "G", "B")


def roles():
    """(name, color, mult) for every role that composes multiplicatively.

    ⚠ ROLES ARE PER-CONTRACT, and getting this wrong makes the checker
    confidently wrong rather than silent — which is worse than not having
    it. The first version reported a `train #2` dimmed by
    BACKGROUND_BRIGHTNESS for every contract, and under `approach` that
    role does not exist: `_paint_layers`/`_layer_mult` back the ARC
    contracts, while ApproachContract paints every train at mult 1.0
    (contracts.py `_render_train`). The effect was a usable-window floor
    of 0.25 for a config whose real floor is 0.15.

    Not the status messages either: those render at mult 1.0 in a fixed
    colour, so they cannot drift the way a product of three config values
    can.

    ⚠ The ACK SHELF is included and had to be, because it is the one role
    that is BOTH a product of config values AND rendered on the animated
    path — so its output is BRIGHTNESS x mult**GAMMA, not BRIGHTNESS x
    mult. At the old SHELF_FLOOR of 0.08 that put it at raw 0.49, below a
    single output code, where it either vanished or sparkled depending on
    DITHER. It went undetected for months because nothing checked it."""
    if CONTRACT_NAME == "approach":
        # Anchor and markers exist ONLY here; every train renders at 1.0.
        out = [("train", LINE_COLOR, 1.0),
               ("anchor", ANCHOR_COLOR, ANCHOR_BRIGHTNESS)]
        if MARKER_BRIGHTNESS > 0:
            out.append(("marker", MARKER_COLOR, MARKER_BRIGHTNESS))
        if WAKE_INTERACTION_ENABLED:
            # ⚠ GAMMA'd, unlike every other role here — the ACK renders on
            # the ANIMATED path. Pre-applying it lets the same floor and
            # clipping checks below work unchanged.
            out.append(("ACK shelf", STARTUP_COLOR, gamma(SHELF_FLOOR)))
        return out
    # Arc-based contracts: geometric falloff per layer, no anchor, no
    # markers. Only the DIMMEST layer can hit the floor, so checking that
    # one covers the rest.
    out = [("train", LINE_COLOR, 1.0)]
    if N_TRAINS > 1:
        out.append(("train #%d" % N_TRAINS, LINE_COLOR,
                    BACKGROUND_BRIGHTNESS ** (N_TRAINS - 1)))
    return out


def reachable_levels():
    """Every BRIGHTNESS this unit can actually be at.

    **This is the check a human cannot do by inspection**, and the reason
    the anchor bug survived review: a config can be perfectly valid at
    NIGHT_BRIGHTNESS and broken at DAY_BRIGHTNESS, and nobody reads a
    config at two brightnesses at once."""
    out = [("BRIGHTNESS", BRIGHTNESS)]
    if DAY_NIGHT_ENABLED:
        out.append(("DAY_BRIGHTNESS", DAY_BRIGHTNESS))
        out.append(("NIGHT_BRIGHTNESS", NIGHT_BRIGHTNESS))
    if TILT_ENABLED:
        out.append(("TILT_MAX_BRIGHT", TILT_MAX_BRIGHT))
        out.append(("TILT_MIN_BRIGHT", TILT_MIN_BRIGHT))
    seen = []
    for name, v in out:          # de-dupe, keeping the first name for each
        if not any(abs(v - s[1]) < 1e-9 for s in seen):
            seen.append((name, v))
    return seen


def render_raw(color, mult, brightness):
    """What the driver will actually latch: BRIGHTNESS * mult, per channel,
    unclamped — the clamping is what we are here to detect."""
    level = brightness * mult
    return tuple(c * level for c in color)


def palette_problems(floor=None):
    """Reasons the palette can't render correctly; [] means it can.

    Parameterised on `floor` so a per-strip measurement can be swept in
    tests, the same reason geometry_problems() takes its dimensions."""
    floor = LOW_PWM_FLOOR if floor is None else floor
    out = []
    for level_name, brightness in reachable_levels():
        for role_name, color, mult in roles():
            raw = render_raw(color, mult, brightness)

            # ── below the low-PWM floor ──────────────────────────
            # Only channels that are SUPPOSED to be lit: a colour with a
            # deliberately dark channel (MARKER_COLOR has none, LINE_COLOR
            # does) is not broken for having one.
            low = [_CH[i] for i, v in enumerate(raw)
                   if 0 < color[i] and 0 < v < floor]
            if low:
                out.append(
                    "%s at %s=%.2f: %s below the low-PWM floor of %d "
                    "(raw %s) — channels stop matching down there, so "
                    "'neutral' reads as an unpredictable hue. Raise "
                    "%s, or re-measure the floor with `make low-pwm-test`."
                    % (role_name, level_name, brightness, "/".join(low),
                       floor, ",".join("%.1f" % v for v in raw),
                       "BRIGHTNESS" if mult == 1.0 else "its multiplier"))

            # ── clipping, reported as the hue shift it causes ─────
            high = [_CH[i] for i, v in enumerate(raw) if v > 255.0]
            if high:
                got = tuple(min(255, int(round(v))) for v in raw)
                if len(high) < 3:
                    out.append(
                        "%s at %s=%.2f: %s clip while the others don't, so "
                        "the HUE shifts — %s renders as %s. Lower the "
                        "multiplier (%.2f) or the brightness."
                        % (role_name, level_name, brightness,
                           "/".join(high), color, got, mult))
                else:
                    out.append(
                        "%s at %s=%.2f: every channel clips — %s renders as "
                        "white (%s) and stops being distinguishable by "
                        "colour at all."
                        % (role_name, level_name, brightness, color, got))
    return out


def safe_range(floor=None):
    """The BRIGHTNESS window in which every role renders correctly, and the
    role binding each end: (lo, lo_reason, hi, hi_reason).

    **This is the number nobody can compute by hand**, and the reason the
    tilt rails were set wrong: TILT_MIN_BRIGHT and TILT_MAX_BRIGHT were
    chosen as "never fully off" and "not blinding" without reference to
    the palette at all, so they sit outside a window neither of them knew
    existed.

    It is also the bridge to proposal A in docs/palette-model.md — once
    this window is computable, "rescale to fit it" is a small step from
    "report that you don't".
    """
    floor = LOW_PWM_FLOOR if floor is None else floor
    lo, lo_why = 0.0, "nothing"
    hi, hi_why = 1e9, "nothing"
    for role_name, color, mult in roles():
        if mult <= 0:
            continue
        for i, c in enumerate(color):
            if c <= 0:          # a deliberately dark channel binds nothing
                continue
            need = floor / (c * mult)          # to clear the floor
            if need > lo:
                lo, lo_why = need, "%s %s" % (role_name, _CH[i])
            cap = 255.0 / (c * mult)           # before this channel clips
            if cap < hi:
                hi, hi_why = cap, "%s %s" % (role_name, _CH[i])
    return lo, lo_why, hi, hi_why


def describe(floor=None):
    """The resolved palette, as lines to print at boot.

    Palette is the one subsystem whose derived values are invisible, which
    is precisely why its bugs were. Everything else here announces itself
    — the memory table, the geometry check, `[DAY] brightness → 0.62`."""
    floor = LOW_PWM_FLOOR if floor is None else floor
    lo, lo_why, hi, hi_why = safe_range(floor)
    lines = ["  palette (floor %d, static path — no gamma):" % floor]
    if MARKER_BRIGHTNESS <= 0:
        lines.append("    markers OFF (MARKER_BRIGHTNESS = 0) — deliberate, "
                     "not a fault")
    if lo <= hi:
        lines.append("    usable BRIGHTNESS %.2f-%.2f  (%s sets the floor, "
                     "%s clips first)" % (lo, hi, lo_why, hi_why))
    else:
        lines.append("    ⚠ NO usable BRIGHTNESS: %s needs ≥%.2f but %s "
                     "clips above %.2f — the roles cannot coexist at any "
                     "brightness." % (lo_why, lo, hi_why, hi))
    for level_name, brightness in reachable_levels():
        parts = []
        for role_name, color, mult in roles():
            raw = render_raw(color, mult, brightness)
            parts.append("%s %s" % (
                role_name,
                ",".join("%d" % min(255, int(round(v))) for v in raw)))
        lines.append("    %-17s %.2f   %s"
                     % (level_name, brightness, "   ".join(parts)))
    return lines
