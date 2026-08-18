"""scripts/convert_schedule.py — YAML → minutes-since-midnight JSON.

Covers the multi-line extension (docs/contracts/schedule-json.md § Multiple
lines) and, just as importantly, that adding it did NOT change the
single-line shape. Every existing schedule predates `lines:` and must keep
converting byte-identically — design principle #9.

Host-side only; this script never runs on the device.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "convert_schedule.py"


def _convert(tmp_path, yaml_text):
    src = tmp_path / "s.yaml"
    src.write_text(yaml_text)
    r = subprocess.run([sys.executable, str(SCRIPT), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((tmp_path / "s.json").read_text())


SINGLE = """
station: teststation
weekday:
  a: ["05:37", "06:01", "24:03"]
  b: ["05:02"]
"""

MULTI = """
station: teststation
lines:
  - name: green
    color: [154, 205, 50]
    weekday:
      a: ["05:37", "06:01"]
      b: ["05:02"]
  - name: red
    color: [243, 0, 8]
    weekday:
      a: ["05:40"]
      b: ["05:05"]
"""


def test_single_line_shape_is_unchanged(tmp_path):
    out = _convert(tmp_path, SINGLE)
    assert out["station"] == "teststation"
    assert "lines" not in out  # must NOT gain the new key
    assert out["weekday"]["a"] == [337, 361, 1443]  # 24:03 stays extended-hours


def test_multi_line_shape(tmp_path):
    out = _convert(tmp_path, MULTI)
    assert [l["name"] for l in out["lines"]] == ["green", "red"]
    assert out["lines"][0]["color"] == [154, 205, 50]
    assert out["lines"][0]["weekday"]["a"] == [337, 361]
    assert out["lines"][1]["weekday"]["b"] == [305]


def test_line_name_defaults_when_omitted(tmp_path):
    out = _convert(tmp_path, """
station: s
lines:
  - weekday:
      a: ["06:00"]
""")
    assert out["lines"][0]["name"] == "line_1"


def test_color_is_optional(tmp_path):
    out = _convert(tmp_path, """
station: s
lines:
  - name: plain
    weekday:
      a: ["06:00"]
""")
    assert "color" not in out["lines"][0]


@pytest.mark.parametrize("bad", ["[1, 2]", "[0, 0, 999]"])
def test_bad_color_is_rejected(tmp_path, bad):
    # A malformed colour should fail loudly at conversion time, on the host,
    # rather than reaching the device and rendering as something confusing.
    src = tmp_path / "s.yaml"
    src.write_text(f"station: s\nlines:\n  - name: x\n    color: {bad}\n"
                   f"    weekday:\n      a: [\"06:00\"]\n")
    r = subprocess.run([sys.executable, str(SCRIPT), str(src)],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "color" in (r.stdout + r.stderr)


def test_unsorted_times_still_rejected_inside_a_line(tmp_path):
    # The ascending-order invariant is what lets the firmware just "find the
    # first entry > now". It must hold per-line, not only at top level.
    src = tmp_path / "s.yaml"
    src.write_text('station: s\nlines:\n  - name: x\n    weekday:\n'
                   '      a: ["08:00", "06:00"]\n')
    r = subprocess.run([sys.executable, str(SCRIPT), str(src)],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "ascending" in (r.stdout + r.stderr)
