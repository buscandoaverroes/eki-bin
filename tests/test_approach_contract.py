"""ApproachContract — positional/approach paradigm.

See docs/contracts/approach-contract.md for the design. Distinct from every
other contract here: it carries instance state across render() calls (the
crossfade), so several tests render the SAME contract instance multiple times
in sequence, unlike the stateless single-shot renders elsewhere.

Terminology (matches the config/docs, not arbitrary): ANCHOR = the "0"
reference point. MARKER = every idle "tick" LED — the gaps on the
thermometer, neither the anchor nor the train. The train itself has no
separate brightness knob — where it currently is renders at BRIGHTNESS
directly (mult=1.0, once settled).
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


def test_idle_leds_render_marker_not_black(load_main):
    # GAMMA=1.0 (linear): with the default perceptual GAMMA=2.2, a
    # MARKER_BRIGHTNESS this low legitimately rounds to (0,0,0) without
    # dithering carrying the fractional value across frames — see
    # test_dither_averages_to_target. That's correct, expected low-end
    # behaviour, not what this test is checking.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, MARKER_BRIGHTNESS=0.05, DITHER=False, BRIGHTNESS=1.0,
        GAMMA=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)
    # every non-anchor LED is on (a marker tick), not dark — never clear()s
    assert _lit(m.np) == list(range(21))


def test_marker_color_is_not_a_dimmed_line_color(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, LINE_COLOR=(34, 139, 34), MARKER_COLOR=(80, 80, 80),
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


def test_train_beyond_arm_len_is_dropped_anchor_and_markers_remain(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=5, NUM_LEDS=8,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([20.0]), 0)  # offset 20 > arm_len 5
    assert m.np.buf[m._physical(0)] == _anchor_level(m)  # anchor still lit
    # no LED shows the line colour — the dropped train left no mark
    assert m.LINE_COLOR not in m.np.buf


def test_only_primary_ttl_used_at_default_n_trains(load_main):
    # N_TRAINS=1 default (unchanged) — only ttls[0] is ever shown.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 12.0]), 0)
    assert m.np.buf[m._physical(5)] == tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(12)] != tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)


# ── N_TRAINS (iteration 2: N trains per arm) ────────────────────────


def test_n_trains_shows_multiple_simultaneous_markers(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, N_TRAINS=3,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 8.0, 12.0]), 0)
    assert m.np.buf[m._physical(5)] != (0, 0, 0)
    assert m.np.buf[m._physical(8)] != (0, 0, 0)
    assert m.np.buf[m._physical(12)] != (0, 0, 0)
    # a 4th train beyond N_TRAINS leaves no mark
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 8.0, 12.0, 16.0]), 0)
    marker = tuple(int(c * m.BRIGHTNESS * m.MARKER_BRIGHTNESS) for c in m.MARKER_COLOR)
    assert m.np.buf[m._physical(16)] == marker


def test_n_trains_primary_stays_unshifted_secondaries_hue_shifted(load_main):
    # Dimming a secondary layer is the exact failure mode docs/insights.md §6
    # ruled out (breaks at low absolute brightness on real hardware) — every
    # CHASE-rendered train is full brightness regardless of rank, so
    # differentiation must come from colour (hue), not brightness.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, N_TRAINS=2, SECONDARY_HUE_SHIFT_DEG=20,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 8.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    shifted = tuple(
        int(c * m.BRIGHTNESS) for c in m.hue_rotate(m.LINE_COLOR, 20)
    )
    assert m.np.buf[m._physical(5)] == full      # primary: unshifted
    assert m.np.buf[m._physical(8)] == shifted    # secondary: hue-shifted
    # both are FULL brightness — no dimming of the secondary at all
    assert sum(m.np.buf[m._physical(8)]) > 0
    assert m.np.buf[m._physical(8)] != m.np.buf[m._physical(5)]  # visibly distinct


def test_n_trains_primary_wins_on_index_collision(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, N_TRAINS=2,
    )
    # 5.0 and 4.5 both ceil to offset 5 (see _position_offset) — same LED
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0, 4.5]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(5)] == full  # primary's unshifted colour wins


def test_n_trains_each_slot_chases_independently(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, N_TRAINS=2,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([5.0, 10.0]), 0)
    assert contract._arm_a[0].index == 5
    assert contract._arm_a[1].index == 10
    # only the secondary train hops — its slot animates, the primary's
    # slot must be completely unaffected (still settled at index 5)
    contract.render(m.LeaveSignal([5.0, 9.0]), 0)
    assert contract._arm_a[0].sweep_from is None   # primary: no new sweep
    assert contract._arm_a[1].sweep_from == 10     # secondary: mid-sweep


def test_hidden_signal_shows_anchor_and_markers_only(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([]), 0)  # empty ttls → HIDDEN
    assert m.LINE_COLOR not in m.np.buf
    assert m.np.buf[m._physical(0)] == _anchor_level(m)


# ── chase transition ─────────────────────────────────────────────
# Replaced an earlier brightness/colour-blend crossfade — that design
# necessarily passed through low-brightness values, where temporal dithering
# breaks down on this hardware (see docs/insights.md §6, and the marker-tick
# fix earlier this session). CHASE sweeps a highlight LED-by-LED between old
# and new positions, always at full brightness — never a dim intermediate
# value, so dithering is never needed during a transition at all.


def test_chase_first_appearance_snaps_immediately(load_main):
    # No prior position to sweep FROM — appears at full brightness right
    # away, regardless of TRANSITION_MS (nothing to animate between).
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert contract._arm_a[0].index == 10
    assert contract._arm_a[0].sweep_from is None  # nothing to sweep from
    assert m.np.buf[m._physical(10)] == full


def test_chase_disappearance_snaps_off_immediately(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    contract.render(m.LeaveSignal([]), 100)  # train no longer catchable
    assert contract._arm_a[0].index is None
    assert contract._arm_a[0].sweep_from is None
    assert m.LINE_COLOR not in m.np.buf


def test_chase_one_led_hop_switches_sharply_at_midpoint(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)   # settle at index 10
    contract.render(m.LeaveSignal([9.0]), 0)    # target hops to 9 (1 LED)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)

    contract.render(m.LeaveSignal([9.0]), 1999)  # just before halfway
    assert m.np.buf[m._physical(10)] == full
    assert m.np.buf[m._physical(9)] != full

    contract.render(m.LeaveSignal([9.0]), 2000)  # exactly halfway — sharp switch
    assert m.np.buf[m._physical(9)] == full
    assert m.np.buf[m._physical(10)] != full


def test_chase_multi_led_hop_sweeps_through_each_intermediate_led(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=3000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([13.0]), 0)   # settle at index 13
    contract.render(m.LeaveSignal([10.0]), 0)   # target hops to 10 (distance 3)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)

    def lit_index():
        return next(i for i in (13, 12, 11, 10) if m.np.buf[m._physical(i)] == full)

    assert lit_index() == 13
    contract.render(m.LeaveSignal([10.0]), 750)    # 1/4 through
    assert lit_index() == 12
    contract.render(m.LeaveSignal([10.0]), 1500)   # 1/2 through
    assert lit_index() == 11
    contract.render(m.LeaveSignal([10.0]), 3000)   # settled
    assert lit_index() == 10


def test_chase_never_produces_an_intermediate_brightness_value(load_main):
    # The whole point of CHASE: every non-anchor LED is always EXACTLY full
    # brightness or the marker baseline — never anything dithering-prone in
    # between, at any point during a transition.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=0.1,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([15.0]), 0)
    contract.render(m.LeaveSignal([5.0]), 0)  # a big hop, many intermediate LEDs
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    marker = tuple(int(c * m.BRIGHTNESS * m.MARKER_BRIGHTNESS) for c in m.MARKER_COLOR)
    for phase in range(0, 4001, 100):
        contract.render(m.LeaveSignal([5.0]), phase)
        for i in range(1, 21):  # excludes the anchor at index 0
            assert m.np.buf[m._physical(i)] in (full, marker)


def test_chase_transition_ms_zero_switches_in_one_frame(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    contract.render(m.LeaveSignal([9.0]), 0)  # same tick, target hops
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(9)] == full
    assert m.np.buf[m._physical(10)] != full


def test_chase_progress_uses_absolute_clock_not_relative(load_main):
    # Matches the seamless-breathing pattern: phase_ms is absolute ticks_ms(),
    # so a sweep started at t=50_000 must still measure elapsed time from its
    # own start, not from 0.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 50_000)
    contract.render(m.LeaveSignal([9.0]), 50_000)
    assert contract._arm_a[0].transition_start == 50_000
    contract.render(m.LeaveSignal([9.0]), 52_000)  # +2000ms → halfway
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(9)] == full


def test_repeated_render_same_target_does_not_restart_transition(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=4000, DITHER=False, BRIGHTNESS=1.0,
    )
    contract = m.ACTIVE_CONTRACT
    contract.render(m.LeaveSignal([10.0]), 0)
    contract.render(m.LeaveSignal([10.0]), 4000)  # settled, full brightness
    contract.render(m.LeaveSignal([10.0]), 5000)  # same target again, later tick
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(10)] == full  # still full, no re-fade
    assert contract._arm_a[0].sweep_from is None


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


# ── the three independent brightness knobs ──────────────────────────


def test_train_brightness_is_just_global_brightness_not_a_separate_knob(load_main):
    # Design decision: unlike ANCHOR_BRIGHTNESS and MARKER_BRIGHTNESS, the
    # train has NO brightness knob of its own — "where the train is" renders
    # at BRIGHTNESS directly (mult=1.0), full stop. Confirms that invariant.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=0.5,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0]), 0)
    assert m.np.buf[m._physical(5)] == tuple(int(c * 0.5) for c in m.LINE_COLOR)


def test_marker_brightness_independent_of_anchor_and_train(load_main):
    # The bug this guards: brightness constants used to be coupled (an idle
    # tick's ambient level doubling as the crossfade's dim endpoint), so
    # retuning one silently moved the other. MARKER_BRIGHTNESS must be
    # freely tunable without moving the anchor or the settled train at all.
    dim = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=0.05,
    )
    dim.ACTIVE_CONTRACT.render(dim.LeaveSignal([5.0]), 0)

    bright = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=0.90,
    )
    bright.ACTIVE_CONTRACT.render(bright.LeaveSignal([5.0]), 0)

    assert dim.np.buf[dim._physical(0)] == bright.np.buf[bright._physical(0)]  # anchor
    assert dim.np.buf[dim._physical(5)] == bright.np.buf[bright._physical(5)]  # train


def test_marker_brightness_actually_changes_the_marker_ticks(load_main):
    # Directly verifies MARKER_BRIGHTNESS moves the 19 idle tick LEDs (not the
    # anchor, not the train) — the mirror image of the test above.
    dim = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=0.1,
    )
    dim.ACTIVE_CONTRACT.render(dim.LeaveSignal([5.0]), 0)

    bright = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False,
        BRIGHTNESS=1.0, MARKER_BRIGHTNESS=0.9,
    )
    bright.ACTIVE_CONTRACT.render(bright.LeaveSignal([5.0]), 0)

    for i in range(1, 21):
        if i == 5:  # the train, unaffected — checked in the test above
            continue
        assert sum(dim.np.buf[dim._physical(i)]) < sum(bright.np.buf[bright._physical(i)])


# ── colour (LINE_SATURATION) ─────────────────────────────────────────


def test_line_saturation_mutes_line_color(load_main):
    m = load_main(
        CONTRACT="approach", LINE_COLOR=(34, 139, 34), LINE_SATURATION=0.3,
    )
    assert m.ACTIVE_CONTRACT.line_color == m.desaturate((34, 139, 34), 0.3)
    assert m.ACTIVE_CONTRACT.line_color != (34, 139, 34)  # actually changed


def test_line_saturation_default_is_unchanged(load_main):
    m = load_main(CONTRACT="approach", LINE_COLOR=(34, 139, 34))
    assert m.ACTIVE_CONTRACT.line_color == (34, 139, 34)


# ── registry ───────────────────────────────────────────────────────


def test_approach_selectable_via_config(load_main):
    m = load_main(CONTRACT="approach")
    assert isinstance(m.ACTIVE_CONTRACT, m.ApproachContract)


# ── per-line colour — schedule-json.md § Multiple lines ──────────


def test_set_line_color_overrides_the_config_default(load_main):
    m = load_main(CONTRACT="approach", LINE_COLOR=(34, 139, 34), LINE_SATURATION=1.0)
    c = m.ApproachContract()
    assert c.line_color == (34, 139, 34)
    c.set_line_color((243, 0, 8))
    assert c.line_color == (243, 0, 8)


def test_set_line_color_none_restores_the_config_default(load_main):
    m = load_main(CONTRACT="approach", LINE_COLOR=(34, 139, 34), LINE_SATURATION=1.0)
    c = m.ApproachContract()
    c.set_line_color((243, 0, 8))
    c.set_line_color(None)
    assert c.line_color == (34, 139, 34)


def test_set_line_color_still_honours_line_saturation(load_main):
    # LINE_SATURATION is a PER-ENCLOSURE correction (how a colour must be
    # driven to look right through YOUR glass). It has to keep applying
    # across every line, or the schedule's nominal colours would defeat it.
    m = load_main(CONTRACT="approach", LINE_SATURATION=0.0)
    c = m.ApproachContract()
    c.set_line_color((243, 0, 8))
    r, g, b = c.line_color
    assert r == g == b, "saturation 0.0 should render fully desaturated"


def test_per_line_colour_reaches_the_rendered_train(load_main):
    # The point of the whole feature: the train dot must actually take the
    # line's colour, since that is what makes a line identifiable on a random
    # glance rather than only at the moment you cycle. Differential rather
    # than asserting an exact RGB, so it doesn't re-derive the brightness
    # pipeline and break every time that's tuned.
    m = load_main(CONTRACT="approach", NUM_LEDS=21, ANCHOR_INDEX=10,
                  ARM_A_LEN=10, ARM_B_LEN=10, LINE_SATURATION=1.0,
                  POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0)
    signal = m.LeaveSignal([3.0])

    red = m.ApproachContract()
    red.set_line_color((243, 0, 8))
    red.render(signal, 0)
    red_frame = list(m.np.buf)

    green = m.ApproachContract()
    green.set_line_color((0, 255, 0))
    green.render(signal, 0)

    assert list(m.np.buf) != red_frame, "train dot ignored the line colour"


def test_apply_line_color_is_a_noop_without_a_colour(load_main):
    m = load_main(CONTRACT="approach", LINE_COLOR=(34, 139, 34), LINE_SATURATION=1.0)
    c = m.ApproachContract()
    m._apply_line_color(c, {"name": "plain"})  # line declares no colour
    assert c.line_color == (34, 139, 34)


def test_apply_line_color_ignores_contracts_without_the_capability(load_main):
    # Arc/urgency contracts have no per-line colour concept — their palette
    # means URGENCY, not identity — so they must be left untouched rather
    # than needing to opt out.
    m = load_main(CONTRACT="breathing")
    m._apply_line_color(m.BreathingContract(), {"color": [1, 2, 3]})  # must not raise
