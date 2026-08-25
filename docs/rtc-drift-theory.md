# Measuring DS3231 drift — the maths

_Why `make rtc-drift` reports what it reports, and what each number does and
does not mean. Written 2026-08-25 after three days of measurements that were
mostly noise, to stop the same confusions recurring._

---

## The one distinction that matters

**`offset` is not drift.**

```
offset  =  how wrong the chip is RIGHT NOW          (one measurement)
drift   =  how fast that wrongness CHANGES          (two measurements)
```

Everything below follows from keeping those apart.

---

## 1. Where the chip's error comes from

Two independent contributions, and only one of them is interesting:

```
  chip_error(t)   =   seed_error        +        drift_rate × elapsed
                      ^^^^^^^^^^                 ^^^^^^^^^^^^^^^^^^^^
                      fixed, inherited            what we actually
                      at provisioning             want to measure
```

`seed_error` arrives through the provisioning chain, and **nothing in it ever
checks against real time**:

```
   macOS clock  ──►  mpremote rtc --set  ──►  board RTC  ──►  DS3231
        │                                                       │
        │  measured +4.140 s off true time (2026-08-24)         │
        │           +2.136 s off true time (2026-08-25)         │
        └──────────── that error is copied straight through ────┘
```

So this project's DS3231 was seeded from a Mac that was itself **seconds**
wrong, and it inherited that. Its `offset` of about **−1.9 s** is
overwhelmingly `seed_error`, not accumulated drift.

> **This answers the obvious misreading.** An `offset` of −1.963 s does *not*
> mean the chip drifted two seconds since the baseline. It means the chip is
> two seconds from true time, almost all of which it started with.

---

## 2. Why the seed error cancels

Drift is a *difference of two offsets*, and `seed_error` is the same constant
in both:

```
  offset(t₁) = seed_error + rate·t₁
  offset(t₂) = seed_error + rate·t₂
  ─────────────────────────────────  subtract
  Δoffset    =              rate·(t₂ − t₁)          ← seed_error is GONE

              Δoffset
  rate  =  ─────────────  ×  10⁶     (parts per million)
             t₂ − t₁
```

**This is why the tool never tries to correct the absolute offset.** It does
not need to. The same argument retires two other worries:

- **Transfer latency** between the device printing and the host timestamping
  is a roughly constant bias → cancels.
- **Timezone.** A chip holding UTC against a JST host shows a constant −9 h
  offset → cancels. The tool is deliberately indifferent to which is stored.

Anything constant at both ends is invisible to a difference. Only things that
**change between samples** can corrupt the result — which is the entire story
of §4.

---

## 3. Measuring `offset` precisely: catch the EDGE

Reading the seconds register tells you the time to the nearest second — far
too coarse, since 2 ppm is 0.173 s/day and would need a week to outgrow ±1 s
of reading error.

Instead, poll until the register **changes**:

```
   register value:   ...  04    04    04    04  │  05    05   ...
                                                 ▲
                                 the instant it flips to 05, the
                                 chip's true time is EXACTLY 05.000
                                 — no fractional part to guess

   host records its own time at that instant  ──►  offset to ±(poll + USB)
```

Measured jitter on this rig: **±4 ms**, ~250× better than reading the
register. The DS3231 double-buffers its time registers, so a read cannot tear
mid-tick.

---

## 4. The reference is the hard part

The measurement is `chip − reference`. If the *reference* moves, that motion
appears as fake drift. macOS disciplines its clock against NTP and steps it
across sleep/wake, so the host clock is **not** a fixed yardstick:

```
   what we want                      what we had
   ────────────                      ───────────
   chip ──── true time               chip ──── macOS clock ~~~ wandering
        (fixed reference)                             ↑
                                          moved 2 s in 24 h; observed
                                          707 ms of scatter about the fit,
                                          against 4 ms of jitter — 168×
```

Two host-referenced figures from that period: **+11.94 ppm**, then
**−3.66 ppm**. Both were the Mac, not the chip.

**Fix: ask NTP directly at sample time.** The four-timestamp form cancels
symmetric network latency:

```
   host   t₁ ──────────────► t₂   server
                                  (receive)
                                    │
   host   t₄ ◄────────────── t₃   server
        (receive)                 (transmit)

              (t₂ − t₁) + (t₃ − t₄)
   offset  =  ─────────────────────      ← seconds to ADD to the host clock
                        2
```

Latency cancels **only if it is symmetric**, so the residual error is
round-trip *asymmetry*. That varies per packet, which is why the tool takes
the **median of several queries** — one badly-delayed packet gets outvoted
rather than averaged in.

> Samples record which reference they used, and a fit **never mixes them**. A
> host-referenced and an NTP-referenced sample differ by whatever the host was
> wrong by at the time — mixing them reinjects exactly the error NTP removes.

---

## 5. How long you must wait

Drift has to outgrow the reference noise:

```
                   reference_error
   t_needed  =  ─────────────────────
                  drift_rate

   at 2 ppm (= 2×10⁻⁶ s/s):

     reference error │  time to equal it  │  5:1 confidence
     ────────────────┼────────────────────┼─────────────────
       707 ms (host) │       98 h         │     491 h
        20 ms (NTP)  │      2.8 h         │      14 h
         4 ms (ideal)│      0.6 h         │       3 h
```

The tool refuses to report a figure when the scatter about its own fit
exceeds ~5× the measured jitter, because that means the samples do not
describe a constant drift at all — and a long elapsed time alone is *not*
evidence that they do.

---

## 6. Result on this unit

```
  2026-08-24 22:59  offset −1.9132 s   (ntp)
  2026-08-25 21:40  offset −1.9632 s   (ntp)
  ────────────────────────────────────────────
  Δoffset  −0.0500 s   over  22.69 h

  drift = −0.0500 / 81683 × 10⁶  =  −0.61 ppm
                                    ±0.35 ppm  (~20 ms reference error)

  = −0.053 s/day  ≈  −19 s/year        DS3231 spec: ±2 ppm
```

**Within spec, running very slightly slow.** Two samples give no scatter
check, so a third is needed before this is trustworthy — but it is the first
figure here not dominated by the reference.

For a one-minute-granularity display, −19 s/year is invisible. The chip would
take **roughly three years** to accumulate a single minute of error, which is
comparable to the CR1220's own life.

---

## 7. Practical notes

- **The log is worktree-stable.** `data/` is gitignored, so each git worktree
  has its own — a campaign run from two directories silently splits into two
  logs, each too short to yield a figure. The script resolves the *main*
  worktree deliberately. (This happened, and cost a day's sample.)
- **`--history`** prints every sample with running deltas: the campaign view.
- **Re-seeding destroys the baseline.** `--mark-seed` starts a new epoch;
  drift only ever fits within one.
- **Check the host before seeding a unit you care about.** `rtc-drift`'s first
  line reports the host's NTP offset. Seconds rather than milliseconds means
  fix the Mac first — that error becomes permanent in the unit.
