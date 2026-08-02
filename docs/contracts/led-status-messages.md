# LED status messages — a shared vocabulary

**Status:** implemented on `feature/wake-interaction-layer`, host-tested,
**not yet on real hardware.** Spun out of
`docs/contracts/wake-interaction.md`'s Open question #1 (quiet hours vs. a
deliberate tap), which turned out to need more than a yes/no — a proper
vocabulary for anything the LEDs say that isn't a `DisplayContract`'s normal
per-tick rendering. All three "Decisions" below (colours, no-data-repeats-
every-time, schedule-load-failure in scope) were confirmed before
implementation and are reflected in the code as shipped.

**What already exists, informally, before this doc:** the boot ceremony
(`docs/contracts/startup-sequence.md`) already has two message-like states —
the loading circle / success burst, and the persistent red breathe on WiFi
failure. This doc doesn't replace either; it names the pattern they're
already an instance of, and extends it to cover three new cases that came up
discussing tap gestures:

1. A tap during quiet hours (shouldn't do nothing, shouldn't fully wake either)
2. Waking up to find there's genuinely nothing to show (no catchable trains)
3. The schedule file itself failing to load — today this crashes with a
   console print and **no LED indication at all**, which is worth fixing
   while formalizing everything else here

---

## Design principles

- **Errors are persistent and unambiguous.** A broken device should look
  broken, not almost-normal — the existing red-breathe-forever pattern for
  WiFi failure already does this right; extend it, don't soften it.
- **Different failure *causes* get visually distinct colours.** The whole
  point of formalizing this is that someone looking at a jar with no laptop
  handy can tell *which* thing failed. One universal "something's wrong,
  breathe red" for every failure defeats that.
- **Acknowledgments are brief and deliberately smaller than a full wake.** A
  quick, restrained cue says "I heard you" without pretending to be the real
  thing — same "different colour, not just dimmer" logic `MARKER_COLOR` and
  `ANCHOR_COLOR` already use to stay distinguishable from what they're not.
- **Never blend between states.** Every message here renders via the STATIC
  path (full brightness or off) or, if genuinely animated, the same
  deliberate ANIMATED path the boot burst already uses. This is the third
  time this session a low-brightness blend has caused a real bug (marker
  ticks, then CHASE) — worth stating as a standing rule for this codebase,
  not re-deriving it a fourth time.

## The catalog

| Message | Trigger | Mechanic | Colour | Duration | Blocks contract render? |
|---|---|---|---|---|---|
| Boot ceremony *(existing)* | Successful WiFi/NTP connect | Loading circle → burst | `STARTUP_COLOR` | ~connect time + burst | Yes, boot-time only |
| Connect failure *(existing)* | WiFi/NTP connect fails | Persistent breathe, whole strip | `ERROR_COLOR` (red) | Forever, needs reset | Yes, terminal |
| **Schedule-load failure (new)** | `load_schedule()` can't read/parse `schedule.json` | Persistent breathe, whole strip — same mechanism as connect failure, generalized to take a colour | `SCHEDULE_ERROR_COLOR` (distinct from `ERROR_COLOR`) | Forever, needs reset | Yes, terminal |
| Wake-from-sleep *(from wake-interaction.md)* | Any tap while ASLEEP, not quiet hours | Reuses `_play_startup_burst()` as-is | `STARTUP_COLOR` | ~2.3s | Yes, then hands off to normal render |
| Extend confirmation *(from wake-interaction.md)* | Double-tap while AWAKE | `_StatusMessage` overlay — see Shared mechanism below | `EXTEND_CONFIRM_COLOR` (`STARTUP_COLOR` by default) | `EXTEND_CONFIRM_MS` (600ms) | No — brief overlay |
| **Quiet-hours tap acknowledgment (new)** | Any tap while `is_quiet(now)` | `_StatusMessage` overlay, single LED at `STATUS_LED_INDEX` | `QUIET_TAP_COLOR` (purple) | `QUIET_TAP_DURATION_MS` (2500ms), then dark again | No — display stays otherwise dark throughout |
| **Wake-to-no-data acknowledgment (new)** | A wake ceremony completes but every active direction's signal is `HIDDEN` | `_StatusMessage` overlay, single LED at `STATUS_LED_INDEX` | `NO_DATA_COLOR` (gold) | `NO_DATA_DURATION_MS` (2500ms), then settles into the (correct) anchor/marker-only view | No — brief, then normal render |

## `STATUS_LED_INDEX`: one shared position, deliberately not `ANCHOR_INDEX`

The quiet-hours ack and no-data ack both want "roughly the middle" — which
is exactly what `ANCHOR_INDEX` already means for `ApproachContract`. **Not
reusing it on purpose:** this vocabulary needs to work the same way
regardless of which `CONTRACT` is active, the same "no contract is
current" principle the boot ceremony's burst already follows (flash all
LEDs, not radiate from an anchor that might not exist under a different
contract). `ANCHOR_INDEX` defaults to `0` when `CONTRACT` isn't `"approach"`
— not the middle at all — so a shared, contract-agnostic middle needs its
own definition:

```
STATUS_LED_INDEX = getattr(config, "STATUS_LED_INDEX", NUM_LEDS // 2)
```

Matches "middle-ish, middle+1 if not even" directly: for an odd `NUM_LEDS`
this lands on the exact centre; for even, integer division picks the upper
of the two centre-adjacent LEDs — a deterministic, defensible choice for a
position that has no single exact middle either way.

## Precedence: quiet hours is checked first, always

Directly answers `wake-interaction.md`'s Open question #1:

1. **Quiet hours check happens before gesture classification.** If
   `is_quiet(now)`, *any* tap (single or double — no need to distinguish
   here) plays the quiet-hours acknowledgment and nothing else: the display
   stays dark, the AWAKE/ASLEEP countdown is **not** touched, no full wake
   happens. Quiet hours always wins on whether the display *lights up*; a
   tap is never ignored outright, it just gets the smaller message instead
   of the real thing.
2. **Outside quiet hours**, `wake-interaction.md`'s state machine runs as
   designed: ASLEEP+tap → wake ceremony, AWAKE+single → secondary action,
   AWAKE+double → extend.
3. **After a wake ceremony resolves** (not quiet hours), check whether every
   active direction's `LeaveSignal.urgency` is `HIDDEN`. If so, play the
   no-data acknowledgment before settling — a tap that reveals nothing
   shouldn't feel like it did nothing.

## Shared mechanism

One reusable primitive backs all three brief acknowledgments (quiet-tap,
no-data, extend) — implemented as a small **non-blocking** class, not a
blocking flash function as originally sketched, specifically so it doesn't
stall tap classification or the schedule-refresh check for its duration:

```python
class _StatusMessage:
    """Set once via show(now_ms, color, duration_ms); the normal fast-tick
    loop checks active(now_ms) each render step and paints ONE LED at
    STATUS_LED_INDEX, full brightness, STATIC path (no gamma, no dither —
    a fixed colour for a fixed duration has no low-brightness intermediate
    value to worry about) for as long as it's active, then falls through to
    whatever would normally render."""
```

`_run_startup_failure_forever()` was generalized to accept a colour
parameter (`color=None` defaults to `ERROR_COLOR`) so the new schedule-load
failure path calls the exact same persistent-breathe loop with
`SCHEDULE_ERROR_COLOR` instead of duplicating it.

## Implemented config

Colours below were confirmed as good starting defaults, not final — real
tuning happens on the actual glass (see the Decisions below):

```
STATUS_LED_INDEX = NUM_LEDS // 2   # shared "middle-ish" position, contract-agnostic
QUIET_TAP_COLOR = (128, 0, 200)    # purple — quiet-hours acknowledgment
QUIET_TAP_DURATION_MS = 2500
NO_DATA_COLOR = (200, 160, 0)      # gold/amber — distinct from ANCHOR_COLOR's
                                     #   warm white and from ERROR_COLOR's red
NO_DATA_DURATION_MS = 2500
SCHEDULE_ERROR_COLOR = (200, 0, 120)  # distinct from ERROR_COLOR (red) — a
                                        #   different failure cause should look
                                        #   like a different failure
```

## Testability

"Which message should play" is a pure decision (`_classify_wake_response`,
`_all_signals_hidden` — both in `wake-interaction.md`'s implemented-pieces
table) — host-tested alongside the rest of the interaction layer in
`tests/test_wake_interaction.py`. `_StatusMessage.show()`/`.active()` are
likewise pure and tested (no real clock needed — plain ms integers in,
bool/state out). The actual persistent-failure breathe loop
(`_run_startup_failure_forever()`) is not host-testable — real
`time.ticks_ms()`/`sleep_ms()`, same limitation `_play_startup_burst()` and
`connect_wifi()` already have, and it never was tested even before this
colour-parameter generalization.

## Decisions (confirmed 2026-07-25)

1. **Colours confirmed as proposed** — the real test is on actual glass, not
   in the abstract; iterate once this is on hardware rather than
   bikeshedding hex values now.
2. **No-data acknowledgment repeats every time**, not just on the first
   occurrence — confirmed as proposed, simplest, no extra state to track.
3. **Schedule-load failure confirmed in scope**: should show an error if the
   load fails, but needs no indicator at all if it loads fine (matching
   every other successful, silent path in this codebase — success doesn't
   need its own announcement, only failure does).
