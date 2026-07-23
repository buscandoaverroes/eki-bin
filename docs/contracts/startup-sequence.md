# Contract: startup sequence ("boot ceremony")

**Status:** design note — not yet implemented. Nothing in `main.py` reflects
this doc yet. Written before code per the v1.4 plan (see `dev-status.md`).

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
3. **Handoff — crossfade into the live contract.** The burst's fade-out
   doesn't end in black; it blends into whatever `ACTIVE_CONTRACT` would
   already be rendering for the current schedule/time. The ceremony ends,
   the clock paradigm takes over, and it never performs this sequence again
   until the next power cycle.
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
render a known value. **Proposal:** a standalone `run_startup_sequence()`
called once at the top of `main()`, before the main loop — not a contract.

**This forces a real structural change to `connect_wifi()`/`sync_ntp()`.**
Today, `connect_wifi()` blocks in a dumb `time.sleep(1)` poll loop (up to 20s)
with no LED output at all — see `micropython/main.py`'s current
`connect_wifi()`. To animate *during* that wait, the connect loop has to
interleave: render one loading-circle frame, check `wlan.isconnected()`,
sleep a short frame interval, repeat — not sleep(1) then check. This is the
main piece of real engineering risk here, not the animation math.

## Reusable primitives (nothing new at the math layer)

| Need | Existing primitive |
|---|---|
| Loading-circle position | `phase_sawtooth(elapsed_ms, period_ms)` → LED index |
| Hanabi rise/decay | `pulse()` or `breathe()` envelope, one-shot instead of looped |
| Error breathe | `breathe()`, exactly as `BreathingContract` already uses it, just red + `clear()`-free (whole strip, not an arc) |
| Crossfade into live contract | Same `progress` + `gamma()` pattern `ApproachContract`'s crossfade already established |

Consistent with this whole codebase's pattern so far: new *behavior*, not new
*math* — compose what's there.

## Proposed config (all new, all optional/`getattr`-defaulted)

```
STARTUP_COLOR = (255, 255, 255)   # loading-circle colour
STARTUP_SPIN_HZ = 0.4             # revolutions/sec, ~1/3-1/2 Hz per the ask
STARTUP_BURST_MS = 800            # hanabi rise+decay duration — GUESS, tune live
STARTUP_FADE_MS = 1500            # burst -> live-contract crossfade duration — GUESS
ERROR_COLOR = (255, 0, 0)
ERROR_BREATHE_PERIOD_MS = 4000    # separate from BREATHE_PERIOD_MS on purpose —
#                                    error state shouldn't inherit contract tuning
```

## Testability

The animation *math* (circle position mapping, burst envelope shape) is pure
and host-testable, same as every other primitive here. The actual
interleaved-connect-loop behavior is not — `connect_wifi()`/`sync_ntp()`
aren't unit tested today (`main()` itself isn't), and this doc doesn't change
that. Flag real-hardware validation as required, same as every LED behavior
in this project.

## Open questions (confirm before coding)

1. **Skippable/config-gated?** A future non-WiFi build (V2, DS3231 RTC) has
   no "connecting" phase to visualize at all — should `STARTUP_SEQUENCE`
   be a config toggle from day one, or is that premature for a V1-only
   feature?
2. **Hanabi shape:** literally radiating outward from `ANCHOR_INDEX`
   (ties into `ApproachContract`'s anchor concept, but couples the startup
   sequence to one specific contract) vs. all LEDs flashing together
   (contract-agnostic, works no matter what `CONTRACT` is active). Leaning
   the latter — the startup sequence runs before any contract is "current,"
   so it shouldn't assume `ApproachContract` semantics.
3. **Failure recovery:** confirm "persistent red, needs a physical
   reset/power-cycle to retry" is actually the intended behavior (vs. an
   auto-retry loop) — the ask said "keep this for infinity," read as
   deliberate, but worth confirming since it's a real usability choice for
   whoever's staring at a red jar.
