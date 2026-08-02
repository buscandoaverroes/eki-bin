# LED status messages — a shared vocabulary

**Status:** design note — not yet implemented. Spun out of
`docs/contracts/wake-interaction.md`'s Open question #1 (quiet hours vs. a
deliberate tap), which turned out to need more than a yes/no — a proper
vocabulary for anything the LEDs say that isn't a `DisplayContract`'s normal
per-tick rendering.

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
| Extend confirmation *(from wake-interaction.md)* | Double-tap while AWAKE | Quick pulse, whole strip | `STARTUP_COLOR` (reused) | ~0.5–1s | No — brief overlay |
| **Quiet-hours tap acknowledgment (new)** | Any tap while `is_quiet(now)` | Single LED, `STATUS_LED_INDEX` | `QUIET_TAP_COLOR` (purple) | A few seconds, then dark again | No — display stays otherwise dark throughout |
| **Wake-to-no-data acknowledgment (new)** | A wake ceremony completes but every active direction's signal is `HIDDEN` | Single LED, `STATUS_LED_INDEX` | `NO_DATA_COLOR` | A few seconds, then settles into the (correct) anchor/marker-only view | No — brief, then normal render |

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

One reusable primitive backs both new single-LED acknowledgments:

```python
def _flash_status_led(index, color, duration_ms):
    """Hold ONE LED at `color`, full brightness, STATIC path (see
    _write_frame) for `duration_ms`, everything else off, then return —
    caller decides what renders next. No gamma, no dither: a single LED at
    a fixed colour for a fixed duration has no low-brightness intermediate
    value to worry about, same reasoning every STATIC entry in this
    codebase already uses."""
```

`_run_startup_failure_forever()` generalizes to accept a colour parameter
(currently hardcoded to `ERROR_COLOR`) so the new schedule-load failure path
can call the exact same persistent-breathe loop with `SCHEDULE_ERROR_COLOR`
instead of duplicating it.

## Proposed config

Colours below are proposals to react to, not decisions — pick different
ones freely, nothing else in this design depends on the specific hues:

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

"Which message should play" is a pure decision — given `(is_quiet, tap_type,
current_wake_state, all_signals_hidden)`, there's exactly one right answer —
so that dispatch logic is host-testable, same "separate the decision from
the real-time loop" split every other real-time piece in this codebase
already uses. The actual flash/breathe loops (`_flash_status_led`, the
generalized failure loop) are not — real `time.ticks_ms()`/`sleep_ms()`,
same limitation as `_play_startup_burst()` and `connect_wifi()`.

## Open questions

1. **Colours above are placeholders** — react to them, don't treat them as
   final.
2. **Does the no-data acknowledgment repeat on every tap into an empty
   state, or only once per wake attempt?** Proposed: every time — simplest,
   no extra state to track, and a tap into silence should always
   acknowledge, not just the first time.
3. **Schedule-load failure is new scope beyond what wake-interaction.md
   asked for** — it fell out of formalizing the catalog (the gap was
   already there: today a missing/corrupt `schedule.json` crashes with a
   console print and zero LED indication). Worth confirming this is wanted
   now rather than a separate follow-up, since it's a small, self-contained
   addition once `_run_startup_failure_forever()` takes a colour parameter.
