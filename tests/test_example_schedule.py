"""The committed schedules/mystation.example.yaml is the public template.

It must stay (a) exactly what `make example-schedule` generates, so nobody
hand-edits a real timetable into a public file, and (b) convertible by the real
converter. See docs/security.md.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import make_test_schedule as gen  # noqa: E402

COMMITTED = ROOT / "schedules" / "mystation.example.yaml"


def test_committed_example_is_what_the_generator_produces():
    assert COMMITTED.read_text() == gen.render_example(gen.build_example()), (
        "schedules/mystation.example.yaml drifted — run `make example-schedule`")


def test_example_is_obviously_synthetic():
    ex = gen.build_example()
    minutes = {int(t[3:]) for p in ex.values() for d in p.values() for t in d}
    # Round numbers only: no real timetable is all multiples of 5.
    assert all(m % 5 == 0 for m in minutes)


def test_example_converts(tmp_path):
    src = tmp_path / "s.yaml"
    src.write_text(COMMITTED.read_text())
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "convert_schedule.py"),
                        str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["weekday"]["a"] and data["weekend"]["b"]
