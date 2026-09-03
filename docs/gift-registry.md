# Gift registry — a record per unit

**Status: ⬜ proposed, not built.** Written up while the first unit is being
assembled, because the format is cheap to get right now and expensive to
retrofit across several bottles.

---

## Why a per-unit record is not optional

Most of this project's hard-won numbers are **facts about one physical
object**, not about the design. They do not transfer, and several are already
measured:

| fact | why it is per-unit |
|---|---|
| gesture thresholds | cross-bottle position accuracy measured **0%** — worse than random (`insights.md` §9). Amplitude features do not survive a change of enclosure. |
| low-PWM floor | a property of *that* strip. Measured 3 on the 8-LED bench stick; different batch, possibly different number. |
| usable line count | a property of *that* vessel. Thick opaque brown 2-3, mid 4-5, clear 5+ (`insights.md` §12). |
| DS3231 drift | a property of *that* crystal. −0.61 ppm on the bench unit, and the campaign needs its own baseline per chip. |
| absolute clock offset | inherited from the host clock **at the moment of seeding** (`rtc-drift-theory.md` §1). |
| schedule staleness | that unit was given a timetable on a date, and Japanese timetables change around March/April. |

Today all of this lives in `config.py`, commit messages, and this
conversation. With one unit that is survivable. With three it is not — and
the failure is silent: you would tune the second bottle with the first
bottle's thresholds and conclude the recognizer regressed.

**`data/rtc-drift-summary.json` is already unit-agnostic**, which stops being
correct the moment there is a second DS3231. That file is the immediate
forcing function.

## Shape

One JSON file per unit, `data/units/<id>.json`. **Gitignored** — the same
reasoning `.gitignore` already applies to `schedules/`: a recipient's name and
their station reveal where someone lives.

```jsonc
{
  "id": "bottle-01",
  "role": "bench",                  // bench | gift | spare
  "given_to": null,                 // name, or null while it's yours
  "built": "2026-09-03",

  "hardware": {
    "board": "Seeed XIAO RP2350",
    "firmware": "1.29.0-preview.731",   // ⚠ must postdate 2026-04-06 (§13)
    "strip": { "type": "WS2812B", "leds": 21, "low_pwm_floor": null },
    "vessel": { "desc": "thick opaque brown", "usable_line_colours": 3 },
    "imu": "LSM6DSV16X @0x6B",
    "rtc": { "part": "DS3231 #3013", "cell": "CR1220", "cell_fitted": "2026-09-03" }
  },

  "clock": {
    "seeded": "2026-09-03T19:54",
    "host_offset_at_seed_s": 0.133,   // the error this unit INHERITED
    "drift_ppm": null,                // from rtc-drift-summary, once trusted
    "drift_trustworthy": false
  },

  "schedule": {
    "station": "mystation",
    "lines": ["yamanote", "chuo"],
    "loaded": "2026-09-03",
    "stale_after": "2027-03-01"       // Japanese timetables change Mar/Apr
  },

  "gestures": { "tap_energy_threshold": 138000, "note": "per-bottle; §9" },

  "notes": "faint always-on charge LED taped over before assembly"
}
```

## What it should be able to answer

Not "store everything" — these four questions, which are the ones that will
actually be asked:

1. **Which units need attention?** — schedule past `stale_after`, cell older
   than ~3 years, drift outside spec.
2. **What are this bottle's numbers?** — when re-flashing a unit that has been
   away, so its per-unit tuning is restored rather than re-derived.
3. **Which vessel did I give whom?** — because that sets the line count, and
   therefore which palettes are legible in that person's kitchen.
4. **What did this unit inherit?** — the host clock's error at seeding is a
   permanent floor, and it is invisible afterwards.

## Design notes

- **Derived, not authored, where possible.** `make rtc-drift` already writes
  `rtc-drift-summary.json`; it should write into the unit's record instead, or
  the registry should read from it. A number typed by hand is a number that
  goes stale.
- **`config.py` is not the registry.** It says how a unit is *configured*; the
  registry says what was *measured* about it, and those diverge — the vessel's
  line ceiling constrains config but is not a config value.
- **Cheapest useful version:** a JSON file per unit and a `make units` target
  that prints which ones need attention. No database, no schema migrations —
  the same reasoning that kept the drift log a `.jsonl`.

## Open

- [ ] Where does the drift summary go once there are two units? (blocking)
- [ ] Does the unit know its own id — written to the device, so a board found
      in a drawer can identify itself? Cheap and probably worth it.
- [ ] Does the registry hold the *schedule source*, so a stale unit can be
      refreshed without hunting for the YAML that made it?
