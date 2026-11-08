"""load_schedule must read the file in ONE call.

MicroPython's json.load(f) pulls the stream a byte at a time. Locally that is
free; over `mpremote mount` (make dev, make interaction-log) every byte is a
serial round trip, so a real-sized schedule held the boot for a minute with no
output — indistinguishable from a hang (2026-09-29). The fix is json.loads of
one read(); this pins it, because nothing else would notice the regression:
on a host, both forms are instant.
"""

import json
import sys


class _CountingFile:
    def __init__(self, text):
        self._text, self.reads = text, 0

    def read(self, n=-1):
        self.reads += 1
        return self._text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_schedule_is_read_in_a_single_call(load_main):
    load_main()
    schedule = sys.modules["schedule"]
    data = {"station": "s", "weekday": {"a": [1, 2, 3]}}
    f = _CountingFile(json.dumps(data))
    schedule.open = lambda name: f          # module-level lookup beats builtins
    try:
        assert schedule.load_schedule("schedule.json") == data
    finally:
        del schedule.open
    assert f.reads == 1
