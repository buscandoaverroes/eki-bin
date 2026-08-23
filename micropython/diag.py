# micropython/diag.py — eki-bin
# Memory instrumentation. Extracted verbatim from main.py by the V1.6
# split (docs/v1.6-refactor.md) — MOVED, not rewritten.
#
# Deliberately has no dependents: nothing in the firmware needs this to
# run, which is what made it the safest possible second extraction.
# Off unless MEM_DEBUG_ENABLED, so it costs a boolean check in production.

import gc

from settings import MEM_DEBUG_ENABLED

# ─────────────────────────────────────────────────────────────
# Memory instrumentation — docs/insights.md §11
#
# Why this exists rather than poking gc.mem_free() by hand: the ESP32-C3
# investigation cost days, and the expensive part wasn't the measuring, it
# was measuring the WRONG POOL and drawing a confident wrong conclusion.
# gc.mem_free() reported 155KB free while esp_wifi was starving, because
# MicroPython's GC heap and ESP-IDF's malloc heap are separate arenas
# competing for the same SRAM. Automating only gc.mem_free() would have
# automated that mistake, so this reports every heap the platform has and
# names them.
#
# Reports DELTAS between labelled checkpoints, not totals — "how much did
# THIS step cost" is the question that actually gets answered; a single
# free-bytes number never told us anything useful.
#
# ⚠ REAL LIMIT, worth knowing before trusting this to explain an OOM:
# each checkpoint samples AFTER a step completes, so it captures the
# step's RESIDENT cost, not its transient PEAK. The C3's actual failure
# was a compile-time spike that permanently enlarged the GC heap — this
# table would show the aftermath, not the spike. Per-frame render
# allocation is likewise not captured; that's a different question needing
# a different tool.
# ─────────────────────────────────────────────────────────────

_mem_marks = []  # [(label, free, alloc)] — only populated when enabled


def _mem_checkpoint(label):
    """Record free/alloc under `label`. No-op unless MEM_DEBUG_ENABLED, so
    production pays one boolean test and this can't itself become a
    consumer of the thing it measures."""
    if not MEM_DEBUG_ENABLED:
        return
    gc.collect()  # measure reclaimable-vs-live, not "whatever hasn't been
    #               swept yet" — otherwise deltas are dominated by GC timing
    _mem_marks.append((label, gc.mem_free(), gc.mem_alloc()))


def _mem_report():
    """Print the checkpoint table with per-step deltas. Called once after
    boot; safe to call with nothing recorded."""
    if not MEM_DEBUG_ENABLED or not _mem_marks:
        return
    print("\n  ── memory ─────────────────────────────────────")
    prev_free = None
    for label, free, alloc in _mem_marks:
        if prev_free is None:
            print("    %-22s free %7d  alloc %7d" % (label, free, alloc))
        else:
            delta = free - prev_free
            print("    %-22s free %7d  alloc %7d   (%+d)"
                  % (label, free, alloc, delta))
        prev_free = free

    # The §11 lesson, encoded: on ESP32 the GC heap above is NOT the pool a
    # WiFi failure comes from. Show the real one too, or this tool repeats
    # the exact error it exists to prevent.
    try:
        import esp32
        print("    ESP-IDF heap (the pool esp_wifi allocates from —")
        print("    NOT the GC heap above; see insights.md §11):")
        for i, region in enumerate(esp32.idf_heap_info(esp32.HEAP_DATA)):
            total, free, largest, minimum = region
            print("      region %d: total %7d  free %7d  largest %7d"
                  % (i, total, free, largest))
    except (ImportError, AttributeError):
        pass  # not an ESP32 — one heap, already reported above
    print()

