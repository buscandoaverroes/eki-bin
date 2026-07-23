"""ApproachContract — positional/approach paradigm.

See docs/contracts/approach-contract.md for the design. Distinct from every
other contract here: it carries instance state across render() calls (the
crossfade), so several tests render the SAME contract instance multiple times
in sequence, unlike the stateless single-shot renders elsewhere.
"""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


def _anchor_level(m):
    # ANCHOR_BRIGHTNESS scales linearly (STATIC path, no gamma) and clamps to
    # 255 — not the same as raw ANCHOR_COLOR once ANCHOR_BRIGHTNESS != 1.0.
    level = m.BRIGHTNESS * m.ANCHOR_BRIGHTNESS
    return tuple(min(255, int(c * level)) for c in m.ANCHOR_COLOR)


# ── geometry helpers ─────────────────────────────────────────────


def test_position_offset_minimum_one(load_main):
    m = load_main(POSITION_MINUTES_PER_LED=1)
    assert m._position_offset(0) == 1
    assert m._position_offset(0.4) == 1


def test_position_offset_scales_with_minutes_per_led(load_main):
    m = load_main(POSITION_MINUTES_PER_LED=2)
    assert m._position_offset(3) == 2   # ceil(3/2)
    assert m._position_offset(4) == 2
    assert m._position_offset(5) == 3


def test_arm_target_direction_a_walks_outward(load_main):
    m = load_main(ANCHOR_INDEX=0)
    assert m._arm_target(3, arm_len=20, direction="a") == 3
    assert m._arm_target(0, arm_len=20, direction="a") == 1


def test_arm_target_direction_b_walks_inward(load_main):
    m = load_main(ANCHOR_INDEX=10)
    assert m._arm_target(3, arm_len=10, direction="b") == 7


def test_arm_target_dropped_beyond_arm_len(load_main):
    m = load_main(POSITION_MINUTES_PER_LED=1)
    assert m._arm_target(20, arm_len=20, direction="a") == 20
    assert m._arm_target(21, arm_len=20, direction="a") is None


# ── static frame content (progress settled, TRANSITION_MS=0) ────


def test_anchor_always_lit_even_with_no_trains(load_main):
    m = load_main(CONTRACT="approach", ANCHOR_INDEX=0, TRANSITION_MS=0)
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)
    assert m.np.buf[m._physical(0)] != (0, 0, 0)  # anchor lit
    assert m.np.buf[m._physical(0)] == m.np.buf[m._physical(0)]  # sanity


def test_idle_leds_render_floor_not_black(load_main):
    # GAMMA=1.0 (linear): with the default perceptual GAMMA=2.2, a FLOOR_BRIGHTNESS
    # this low legitimately rounds to (0,0,0) without dithering carrying the
    # fractional value across frames — see test_dither_averages_to_target. That's
    # correct, expected low-end behaviour, not what this test is checking.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, FLOOR_BRIGHTNESS=0.05, DITHER=False, BRIGHTNESS=1.0,
        GAMMA=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)
    # every non-anchor LED is on (floor), not dark — this contract never clear()s
    assert _lit(m.np) == list(range(21))


def test_floor_color_is_not_a_dimmed_line_color(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, LINE_COLOR=(34, 139, 34), FLOOR_COLOR=(80, 80, 80),
        DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)
    idle = m.np.buf[m._physical(15)]
    r, g, b = idle
    assert not (g > r and g > b)  # not a dim green — a genuinely different hue


def test_primary_train_lands_at_mapped_position(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0]), 0)
    assert m.np.buf[m._physical(5)] == tuple(
        int(c * m.BRIGHTNESS) for c in m.LINE_COLOR
    )


def test_train_beyond_arm_len_is_dropped_anchor_and_floor_remain(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=5, NUM_LEDS=8,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([20.0]), 0)  # offset 20 > arm_len 5
    assert m.np.buf[m._physical(0)] == _anchor_level(m)  # anchor still lit
    # no LED shows the line colour — the dropped train left no mark
    assert m.LINE_COLOR not in m.np.buf


def test_only_primary_ttl_used_secondary_ignored(load_main):
    # Phase 1 scope: no N_TRAINS nesting for ApproachContract — only ttls[0].
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 12.0]), 0)
    assert m.np.buf[m._physical(5)] == tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(12)] != tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)


def test_hidden_signal_shows_anchor_and_floor_only(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)  # empty ttls → HIDDEN
    assert m.LINE_COLOR not in m.np.buf
    assert m.np.buf[m._physical(0)] == _anchor_level(m)


# ── crossfade ─────────────────────────────────────────────────────


def test_transition_ms_zero_snaps_instantly(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert contract._active_index == 10
    assert m.np.buf[m._physical(10)] == full  # already full — no fade-in frame


def test_crossfade_new_position_ramps_up_over_transition(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, GAMMA=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)          # transition starts at t=0
    early = m.np.buf[m._physical(10)]
    contract.render(m.LeaveSignal([10.0]), 2000)       # halfway
    mid = m.np.buf[m._physical(10)]
    contract.render(m.LeaveSignal([10.0]), 4000)       # settled
    late = m.np.buf[m._physical(10)]
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    # Total brightness (sum of channels), not a single channel: the colour is
    # ALSO lerping FLOOR_COLOR -> LINE_COLOR across the same span, and since
    # FLOOR_COLOR's R/B happen to be brighter than LINE_COLOR's, a single
    # channel isn't guaranteed to rise monotonically even though the pixel as
    # a whole is getting brighter (see MARKER_FADE_FLOOR's doc comment).
    assert sum(early) < sum(mid) < sum(late) == sum(full)


def test_crossfade_old_position_ramps_down_toward_floor(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, GAMMA=1.0, FLOOR_BRIGHTNESS=0.05,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    contract.render(m.LeaveSignal([10.0]), 4000)       # settle at index 10
    # now the train advances closer — position changes 10 → 6, a new transition
    contract.render(m.LeaveSignal([6.0]), 4000)
    old_at_start = m.np.buf[m._physical(10)]
    contract.render(m.LeaveSignal([6.0]), 6000)        # halfway through 2nd transition
    old_mid = m.np.buf[m._physical(10)]
    contract.render(m.LeaveSignal([6.0]), 8000)        # settled
    old_end = m.np.buf[m._physical(10)]
    # Total brightness — see the comment in the ramps-up test above.
    assert sum(old_at_start) > sum(old_mid) > sum(old_end)
    # Once fully settled, index 10 is drawn with NOTHING (fading_index cleared)
    # — it's genuinely idle again, so it falls back to the plain floor baseline
    # (FLOOR_BRIGHTNESS/FLOOR_COLOR), not MARKER_FADE_FLOOR.
    floor_level = tuple(int(c * m.BRIGHTNESS * m.FLOOR_BRIGHTNESS) for c in m.FLOOR_COLOR)
    assert old_end == floor_level


def test_crossfade_progress_uses_absolute_clock_not_relative(load_main):
    # Matches the seamless-breathing pattern: phase_ms is absolute ticks_ms(),
    # so a transition started at t=50_000 must still measure elapsed time from
    # its own start, not from 0.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, GAMMA=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 50_000)
    assert contract._transition_start == 50_000
    contract.render(m.LeaveSignal([10.0]), 52_000)  # +2000ms → halfway
    mid = m.np.buf[m._physical(10)]
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert 0 < sum(mid) < sum(full)  # total brightness — see comment above


def test_repeated_render_same_target_does_not_restart_transition(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, GAMMA=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    contract.render(m.LeaveSignal([10.0]), 4000)  # settled, full brightness
    contract.render(m.LeaveSignal([10.0]), 5000)  # same target again, later tick
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(10)] == full  # still full, no re-fade


def test_anchor_wins_when_train_lands_on_anchor_index(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    # offset is always >=1 (see _position_offset), so a train can never
    # literally target ANCHOR_INDEX itself under default config — confirm that
    # invariant, and that the anchor colour is what's there regardless.
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([0.0]), 0)
    assert m.np.buf[m._physical(0)] == _anchor_level(m)


def test_marker_brightness_independent_of_floor_brightness(load_main):
    # The bug this guards: FLOOR_BRIGHTNESS used to double as the crossfade's
    # dim endpoint too, so retuning the ambient floor level also silently
    # changed the marker's fade dynamic range. MARKER_FADE_FLOOR/
    # MARKER_BRIGHTNESS must be independently tunable — changing
    # FLOOR_BRIGHTNESS alone must not move the settled marker's brightness.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=1.0, FLOOR_BRIGHTNESS=0.05,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0]), 0)
    dim_floor = m.np.buf[m._physical(5)]

    m2 = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=1.0, FLOOR_BRIGHTNESS=0.90,
    )
    m2.ACTIVE_CONTRACT.render(m2.LeaveSignal([5.0]), 0)
    bright_floor = m2.np.buf[m2._physical(5)]

    assert dim_floor == bright_floor  # marker unaffected by the floor change


def test_marker_fade_floor_independent_of_floor_brightness(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, GAMMA=1.0, MARKER_FADE_FLOOR=0.5, FLOOR_BRIGHTNESS=0.01,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)  # transition just started, progress=0
    at_start = sum(m.np.buf[m._physical(10)])
    # At progress=0 the marker's brightness mult is exactly MARKER_FADE_FLOOR,
    # nowhere near the near-off FLOOR_BRIGHTNESS=0.01 — confirms the two
    # constants are reading from separate knobs, not the same one.
    assert at_start > 0
    floor_only = sum(
        int(c * m.BRIGHTNESS * m.FLOOR_BRIGHTNESS) for c in m.FLOOR_COLOR
    )
    assert at_start > floor_only * 5  # comfortably above the near-off floor level


# ── registry ───────────────────────────────────────────────────────


def test_approach_selectable_via_config(load_main):
    m = load_main(CONTRACT="approach")
    assert isinstance(m.ACTIVE_CONTRACT, m.ApproachContract)
