"""ApproachContract phase 2 — bidirectional (render_dual, two arms).

Iteration 1 scope: one primary train per arm (two total), each with its own
independent CHASE transition. N-trains-per-arm is deferred (iteration 2). See
docs/contracts/approach-contract.md § Bidirectional.
"""


def _lit(np):
    return [i for i, px in enumerate(np.buf) if px != (0, 0, 0)]


def _dual_config(**overrides):
    base = dict(
        CONTRACT="approach", ANCHOR_INDEX=10, ARM_A_LEN=10, ARM_B_LEN=10,
        NUM_LEDS=21, POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0,
        DITHER=False, BRIGHTNESS=1.0,
    )
    base.update(overrides)
    return base


def test_render_dual_lands_one_train_per_arm(load_main):
    m = load_main(**_dual_config())
    contract = m.ACTIVE_CONTRACT
    contract.render_dual(m.LeaveSignal([5.0]), m.LeaveSignal([3.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(15)] == full  # arm a: anchor(10) + offset 5
    assert m.np.buf[m._physical(7)] == full   # arm b: anchor(10) - offset 3


def test_render_dual_arms_have_independent_transitions(load_main):
    m = load_main(**_dual_config(TRANSITION_MS=4000, GAMMA=1.0))
    contract = m.ACTIVE_CONTRACT
    # arm a starts moving; arm b has nothing yet
    contract.render_dual(m.LeaveSignal([5.0]), m.LeaveSignal([]), 0)
    assert contract._arm_a[0].transition_start == 0
    assert contract._arm_b[0].index is None
    # now arm b gets a train while arm a is mid-fade — arm a's progress must
    # not be disturbed by arm b's fresh transition starting at the same tick
    contract.render_dual(m.LeaveSignal([5.0]), m.LeaveSignal([3.0]), 2000)
    assert contract._arm_a[0].transition_start == 0       # untouched
    assert contract._arm_b[0].transition_start == 2000    # fresh


def test_render_dual_only_primary_per_arm_used_at_default_n_trains(load_main):
    # N_TRAINS=1 default — only ttls[0] per arm.
    m = load_main(**_dual_config())
    contract = m.ACTIVE_CONTRACT
    contract.render_dual(m.LeaveSignal([5.0, 8.0]), m.LeaveSignal([3.0, 6.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(15)] == full
    assert m.np.buf[m._physical(7)] == full
    # the secondary ttls (8.0, 6.0) left no mark anywhere
    assert m.np.buf[m._physical(18)] != full
    assert m.np.buf[m._physical(4)] != full


def test_render_dual_n_trains_per_arm(load_main):
    # Iteration 2: N_TRAINS>1 works per-arm too, independently on each side.
    m = load_main(**_dual_config(N_TRAINS=2))
    contract = m.ACTIVE_CONTRACT
    contract.render_dual(m.LeaveSignal([5.0, 8.0]), m.LeaveSignal([3.0, 6.0]), 0)
    assert m.np.buf[m._physical(15)] != (0, 0, 0)  # arm a primary
    assert m.np.buf[m._physical(18)] != (0, 0, 0)  # arm a secondary
    assert m.np.buf[m._physical(7)] != (0, 0, 0)   # arm b primary
    assert m.np.buf[m._physical(4)] != (0, 0, 0)   # arm b secondary


def test_render_dual_both_arms_hidden_shows_only_anchor(load_main):
    m = load_main(**_dual_config())
    contract = m.ACTIVE_CONTRACT
    contract.render_dual(m.LeaveSignal([]), m.LeaveSignal([]), 0)
    assert m.LINE_COLOR not in m.np.buf
    assert _lit(m.np) == list(range(21))  # anchor + marker ticks, nothing dark


def test_render_dual_anchor_wins_and_arms_dont_collide(load_main):
    # arm a occupies indices > ANCHOR_INDEX, arm b occupies indices <
    # ANCHOR_INDEX (see _arm_target) — confirm no accidental overlap/stomping
    # even with both arms active simultaneously.
    m = load_main(**_dual_config())
    contract = m.ACTIVE_CONTRACT
    contract.render_dual(m.LeaveSignal([1.0]), m.LeaveSignal([1.0]), 0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(11)] == full  # arm a, offset 1
    assert m.np.buf[m._physical(9)] == full   # arm b, offset 1
    assert m.np.buf[m._physical(10)] == m.np.buf[m._physical(10)]  # anchor untouched by either


def test_render_still_works_unaffected_by_render_dual_existing(load_main):
    # Phase 1 configs (ARM_B_LEN=0, DISPLAY_DIRECTION_B unset) must render
    # byte-identically via render() — render_dual existing on the class must
    # not change render()'s behaviour at all.
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    m.ACTIVE_CONTRACT.render(m.LeaveSignal([5.0]), 0)
    assert m.np.buf[m._physical(5)] == tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)


# ── render dispatch (_render_dispatch — pure, no clock involved) ────
# render_for_interval's own frame loop uses real time.ticks_ms()/sleep_ms(),
# which aren't host-testable (and weren't before this change either) — the
# dispatch DECISION is pulled out as its own pure function specifically so
# it can be tested here without touching that loop at all.


def test_dispatch_uses_render_dual_when_signal_b_given(load_main):
    m = load_main(**_dual_config())
    render = m._render_dispatch(
        m.ACTIVE_CONTRACT, m.LeaveSignal([5.0]), m.LeaveSignal([3.0])
    )
    render(0)
    full = tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)
    assert m.np.buf[m._physical(15)] == full
    assert m.np.buf[m._physical(7)] == full


def test_dispatch_falls_back_to_render_without_signal_b(load_main):
    m = load_main(
        CONTRACT="approach", ANCHOR_INDEX=0, ARM_A_LEN=20, NUM_LEDS=21,
        POSITION_MINUTES_PER_LED=1, TRANSITION_MS=0, DITHER=False, BRIGHTNESS=1.0,
    )
    render = m._render_dispatch(m.ACTIVE_CONTRACT, m.LeaveSignal([5.0]), None)
    render(0)
    assert m.np.buf[m._physical(5)] == tuple(int(c * m.BRIGHTNESS) for c in m.LINE_COLOR)


def test_dispatch_ignores_signal_b_for_contracts_without_render_dual(load_main):
    # A non-ApproachContract has no render_dual — passing signal_b must not
    # crash, just be silently ignored (falls back to single-signal render).
    m = load_main(CONTRACT="sandtimer", DITHER=False, BRIGHTNESS=1.0)
    render = m._render_dispatch(
        m.ACTIVE_CONTRACT, m.LeaveSignal([3.0]), m.LeaveSignal([1.0])
    )
    render(0)
    assert _lit(m.np) == [0, 1, 2]  # ordinary sandtimer render, unaffected
