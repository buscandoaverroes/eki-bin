"""scripts/imu_protocol.py — guided trials for `make imu-record PROTOCOL=...`.

WHY GUIDED. The first dry run of the tap-vs-grab session (2026-10-26) showed
the cost of labelling by hand: one hand on the bottle, the other on the keys,
pressing `l` at the grab and `.` at the tilt. The motion that produces is not
a natural motion, and a natural motion is the thing being measured.

The order is known in advance, so the SCRIPT says what to do and when, and
the label is the cue: "trial 14, GRAB AND TILT, GO at h=…". Both hands do the
motion. The keyboard says only "done" (space) or "I messed that up" (r).

What this gives up: the hand-pressed sub-event times (grab / tilt start /
release). Those were late anyway — "press the key AFTER the thing", plus
reaction time; the analysis already searched ±1.5 s for the trigger a label
meant. The data finds the onset inside the trial window [go, done] better
than a finger did.

Nothing is ever deleted (same rule as the rest of the recording). A botched
attempt stays in the file with status "redo", and the trial is repeated
straight away as attempt 2. Botches are data too, as long as they are
labelled.

Pure: no I/O, no clock. The recorder calls it with `now` and writes what it
returns. Host-tested in tests/test_imu_protocol.py.
"""

import math

# What each trial type asks for, in words: no abbreviations at the moment
# you have to act on them. {where} is filled in for the trials that tap.
KINDS = {
    "T": ("TAP", "tap it once on the {where}, then leave it alone"),
    "G": ("GRAB AND TILT", "grab it and tilt straight away, as if changing the "
                           "brightness — put it back, let go"),
    "H": ("GRAB, HOLD, THEN TILT", "grab it, hold still for about a second, then "
                                   "tilt — put it back, let go"),
    "D": ("TAP, WAIT, THEN GRAB AND TILT", "tap once on the {where}, wait about 2 s, "
                                           "then grab and tilt — put it back, let go"),
}
# Where to tap, in rotation over the trials that tap. Chosen by the script
# rather than reported afterwards: reporting it was a third thing to do with
# the hands. Body first because it is where a hand lands without thinking.
WHERE = ("body", "top", "base")

# The order from the 2026-10-25 session plan: seeded, shuffled, never more
# than three of a kind in a row. Kept as the literal string, not regenerated,
# so it stays the same however the shuffle code might change.
PROTOCOLS = {
    "tap-vs-grab": ("HGTHDTTTDT" "DDTTTGGGTH" "THTTTGGTHH" "HTHTHGGTHT"
                    "THTTHTGTTG" "HDDTGHGHTG" "DTTDTGTG"),
}

DONE_KEYS = (" ", "\n", "\r")
REDO_KEY = "r"
# No real trial is over this soon after GO: reaction time alone is ~0.25 s.
# A "done" inside it is a double-pressed space from the previous trial.
MIN_TRIAL_S = 0.4


def plan(name):
    """[(kind, where-or-None)] for a protocol, trial 1 first."""
    out, taps = [], 0
    for kind in PROTOCOLS[name]:
        where = None
        if "{where}" in KINDS[kind][1]:
            where = WHERE[taps % len(WHERE)]
            taps += 1
        out.append((kind, where))
    return out


def describe(kind, where):
    title, how = KINDS[kind]
    return title, how.format(where=where)


class Guide:
    """rest (counting down, hands off) → go (doing it) → rest … → finished.
    A stall pauses it; data coming back starts the paused trial's rest again.

    Every method that changes something returns the label records to write
    (without "id": the recorder numbers them along with its own labels)."""

    def __init__(self, trials, rest_s=4.0, start_at=1):
        self.trials = trials
        self.rest_s = rest_s
        self.queue = list(range(start_at, len(trials) + 1))
        self.attempts = {}
        self.phase = "idle"
        self.current = None
        self.go_at = None
        self.went = None          # when the current attempt's GO fired
        self.fresh = False        # a new countdown began: the recorder announces it
        self.last = None          # (trial, attempt, status) of the last finished attempt
        self.kept = {}            # trial -> attempt that counts

    # ── moving through the session ─────────────────────────────────────
    def begin(self, now):
        if not self.queue:
            self.phase, self.current = "finished", None
            return []
        self.current = self.queue.pop(0)
        self.phase, self.go_at, self.fresh = "rest", now + self.rest_s, True
        return []

    def countdown(self, now):
        """Whole seconds left before GO (3, 2, 1), or None outside rest."""
        if self.phase != "rest":
            return None
        return max(1, math.ceil(self.go_at - now))

    def tick(self, now):
        if self.phase != "rest" or now < self.go_at:
            return []
        n = self.current
        self.attempts[n] = self.attempts.get(n, 0) + 1
        kind, where = self.trials[n - 1]
        self.phase, self.went = "go", now
        rec = {"k": "l", "h": now, "trial": n, "attempt": self.attempts[n],
               "type": kind, "edge": "go"}
        if where:
            rec["where"] = where
        return [rec]

    def _finish(self, now, status):
        n, a = self.current, self.attempts[self.current]
        self.last = (n, a, status)
        if status == "ok":
            self.kept[n] = a
        else:
            self.queue.insert(0, n)
        return {"k": "l", "h": now, "trial": n, "attempt": a, "edge": "done", "status": status}

    def key(self, ch, now):
        """(records, handled). Keys the guide doesn't own fall through to the
        recorder's ordinary labels (h for "mark" still works mid-trial)."""
        if self.phase == "go" and ch in DONE_KEYS and now - self.went < MIN_TRIAL_S:
            return [], True
        if self.phase == "go" and (ch in DONE_KEYS or ch == REDO_KEY):
            rec = self._finish(now, "ok" if ch in DONE_KEYS else "redo")
            return [rec] + self.begin(now), True
        if self.phase == "rest" and ch == REDO_KEY:
            # Noticed during the next countdown. Re-judge the attempt just
            # finished, and repeat it before the trial that was coming.
            if self.last is None or self.last[2] != "ok":
                return [], True
            n, a, _ = self.last
            self.last = (n, a, "redo")
            del self.kept[n]
            self.queue[:0] = [n, self.current]
            rec = {"k": "l", "h": now, "trial": n, "attempt": a, "edge": "verdict",
                   "status": "redo"}
            return [rec] + self.begin(now), True
        if ch in DONE_KEYS:
            return [], True       # space during a countdown: swallow, never a label
        return [], False

    def stall(self, now):
        """No data: a trial in progress has nothing under it. Void it and
        wait. Nothing is lost by pausing a countdown either."""
        out = []
        if self.phase == "go":
            out.append(self._finish(now, "stalled"))
        elif self.phase == "rest":
            self.queue.insert(0, self.current)
        if self.phase in ("go", "rest"):
            self.phase = "paused"
        return out

    def resume(self, now):
        return self.begin(now) if self.phase == "paused" else []

    def abandon(self, now):
        """Quitting mid-trial: close the attempt so every go has a done."""
        return [self._finish(now, "abandoned")] if self.phase == "go" else []

    # ── what to show ───────────────────────────────────────────────────
    def announce(self):
        n = self.current
        kind, where = self.trials[n - 1]
        title, how = describe(kind, where)
        again = self.attempts.get(n, 0)
        lines = [f"  ── {n}/{len(self.trials)}" + (f"  (again — attempt {again + 1})" if again else "")
                 + f"  {title}", f"     {how}"]
        if self.queue:
            nxt_kind, nxt_where = self.trials[self.queue[0] - 1]
            lines.append(f"     then: {describe(nxt_kind, nxt_where)[0].lower()}")
        return "\n".join(lines)

    def summary(self):
        by_kind = {}
        for n, _ in self.kept.items():
            k = self.trials[n - 1][0]
            by_kind[k] = by_kind.get(k, 0) + 1
        redone = sum(a - 1 for a in self.attempts.values())
        return by_kind, redone


def trials(records):
    """[{trial, attempt, type, where, go, done, status}] from a recording's
    label records, one per attempt, with later verdicts applied. An attempt
    with no done (the recording was cut off) has status None. Analysis keeps
    status == "ok"; the window [go, done] is where the data holds the act."""
    by = {}
    for r in records:
        if r.get("k") != "l" or "trial" not in r:
            continue
        key = (r["trial"], r["attempt"])
        if r["edge"] == "go":
            by[key] = {"trial": r["trial"], "attempt": r["attempt"], "type": r["type"],
                       "where": r.get("where"), "go": r["h"], "done": None, "status": None}
        elif key in by and r["edge"] in ("done", "verdict"):
            if r["edge"] == "done":
                by[key]["done"] = r["h"]
            by[key]["status"] = r["status"]
    return sorted(by.values(), key=lambda t: t["go"])
