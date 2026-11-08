# Contract: startup sequence ("boot ceremony")

**Status:** implemented on `feature/startup-sequence`, host-tested, **not yet
validated on real hardware**. See `dev-status.md` for status.

**Resolves an open design fork:** `docs/insights.md` §5 "Startup / boot
ceremony vs the clock paradigm" (2026-06-29) parked exactly this question —
*"a boot animation may break the clock illusion... is it OK to hold the
paradigm in suspense during connection?"* — without deciding it. This doc is
that decision: yes, with a bounded, one-time ceremony that never recurs during
normal operation (see `insights.md`'s updated note).

---

## What it needs to communicate

Four questions, in order, from the moment power is applied:

1. **Is it on at all?** — any LED, immediately.
2. **Is it trying to connect** (WiFi / NTP)?
3. **Did it succeed?**
4. **Did anything fail** — and if so, say so persistently, don't fail silently.

## Stages

Per the original ask, "plug in → time sync starts right away" — there's no
meaningful gap between "powered on" and "connecting," so stage 1 and 2 collapse
into one: the loading animation's first frame *is* the power-on indicator.

1. **Connecting — "loading circle."** A slow, single point of light circling
   the ring, ~1/3–1/2 Hz (one revolution every ~2–3s). Runs for as long as
   `connect_wifi()` + `sync_ntp()` take.
2. **Success — "hanabi" burst.** A quick, bright pulse across the strip, then
   a slow fade — a firework, not a blink.
3. **Handoff — decay to black, then the live contract takes over.**
   **Revised from the original plan:** rather than blending the burst's
   fade-out directly into whatever `ACTIVE_CONTRACT` would render (a
   brightness/colour blend between two independently-coloured frames), the
   burst decays to black on its own, and `main()`'s ordinary loop begins
   immediately after — no explicit crossfade logic. This is a direct
   consequence of the CHASE-transition lesson from `feature/positional-display`
   (`docs/contracts/approach-contract.md` § Chase transition): blending
   between two brightness/colour states necessarily passes through
   low-brightness intermediate values, which is exactly what caused the
   dithering flicker that CHASE was built to eliminate. Re-introducing that
   exact pattern here — right after fixing it elsewhere — would be a
   regression. The burst's own decay already provides the "gentle handoff"
   feel; a hard cut immediately after a fade-to-black doesn't read as
   jarring. The ceremony ends, the clock paradigm takes over, and it never
   performs this sequence again until the next power cycle.
4. **Failure — persistent red breathe.** All LEDs, slow `breathe()`, solid
   red, **forever** — a genuine dead end, not a retry loop. Distinguishes
   "broken, needs help" from every other state at a glance, and doesn't
   pretend to work when it can't.

## The real architecture question

`DisplayContract.render(signal, phase_ms)` is a pure function of an
already-built `LeaveSignal` — but at boot time **there is no signal yet**
(no WiFi, no NTP time, schedule not even loaded). So this can't be a
`DisplayContract` subclass; it's fundamentally a different kind of thing —
boot-time procedural code that needs to observe *live connection state*, not
render a known value. **Implemented as a standalone `run_startup_sequence()`**,
called once at the top of `main()`, before the main loop — not a contract.

**This forced a real structural change to `connect_wifi()`.** It used to
block in a dumb `time.sleep(1)` poll loop (up to 20s) with no LED output at
all. It now polls on a `FRAME_MS`-driven loop instead, drawing one
loading-circle frame (`_draw_startup_circle`) per iteration — same ~20s
budget, now animated throughout. This was the main piece of real engineering
this doc anticipated; the animation math itself was nothing new.
`sync_ntp()` is unchanged (a single blocking call, typically near-instant —
nothing to usefully animate during it).

## Reusable primitives (nothing new at the math layer)

| Need | Existing primitive | Used in |
|---|---|---|
| Loading-circle position | `phase_sawtooth(elapsed_ms, period_ms)` → LED index | `_startup_circle_index` |
| Hanabi rise/decay | Linear rise/decay over `STARTUP_BURST_MS`/`STARTUP_FADE_MS` | `_startup_burst_mult` |
| Error breathe | `breathe()`, exactly as `BreathingContract` already uses it, just red + whole-strip (not an arc) | `_startup_error_mult` |
| Compositing / render seam | `_write_frame()` — STATIC for the circle (single lit LED, nothing dim), ANIMATED for the burst (genuinely changing every frame, so dithering is appropriate there) | `_draw_startup_circle`, `_play_startup_burst`, `_run_startup_failure_forever` |

Consistent with this whole codebase's pattern so far: new *behavior*, not new
*math* — compose what's there.

## Config

```
STARTUP_COLOR = (255, 255, 255)   # loading-circle + success-burst colour
STARTUP_SPIN_HZ = 0.4             # revolutions/sec while connecting
STARTUP_BURST_MS = 800            # success burst: rise duration, ms — GUESS, tune live
STARTUP_FADE_MS = 1500            # success burst: decay duration, ms — GUESS, tune live
ERROR_COLOR = (255, 0, 0)
ERROR_BREATHE_PERIOD_MS = 4000    # separate from BREATHE_PERIOD_MS on purpose —
#                                    error state shouldn't inherit contract tuning
```

## Testability

The animation *math* is pure and host-testable — `_startup_circle_index`,
`_startup_burst_mult`, `_startup_error_mult`, and the one-frame renderer
`_draw_startup_circle` all have tests in `tests/test_startup_sequence.py`
(14 tests). The actual real-time loops — `connect_wifi()`'s animated poll,
`_play_startup_burst()`, `_run_startup_failure_forever()`, and
`run_startup_sequence()` itself — are **not** host-testable (real
`time.ticks_ms()`/`sleep_ms()`, and `connect_wifi()` touches `network`),
same limitation `render_for_interval`'s real frame loop already has.
**Real-hardware validation is required for all of it** — nothing here has
run on the actual device yet.

## Decisions (confirmed 2026-07-24, before implementation)

1. **No config toggle for now.** `STARTUP_SEQUENCE_ENABLED` (or similar)
   was considered for a future non-WiFi V2 build with no "connecting" phase
   to show — decided against for now: this is a V1/WiFi-era feature, and
   adding the toggle only when V2 actually needs it avoids growing the
   config surface for a hypothetical that isn't built yet.
2. **Hanabi flashes all LEDs together — not radiating from `ANCHOR_INDEX`.**
   Confirmed contract-agnostic: the startup sequence runs before any
   `CONTRACT` is "current," so it shouldn't assume `ApproachContract`'s
   anchor concept exists. `_play_startup_burst()` treats every LED
   identically.
3. **Failure state is a genuine dead end — no auto-retry.** Confirmed: on
   WiFi failure, `_run_startup_failure_forever()` breathes red forever and
   only exits via a physical reset/power-cycle. "Broken, needs help" stays
   honest rather than silently retrying in the background.
