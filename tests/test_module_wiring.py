"""Static check: every private name a firmware module uses actually resolves.

WHY THIS EXISTS
`from x import *` does not export underscore-prefixed names. During the V1.6
split (docs/v1.6-refactor.md) that repeatedly left a module calling a private
it had not imported — and on 2026-08-23 it nearly shipped one:
run_startup_sequence() called clock._check_ds3231_at_boot() with no import,
and the whole suite stayed green because no host test reaches the DS3231 boot
path. The failure would have been a NameError at boot, on hardware.

The ordinary test suite structurally cannot catch this class: it only covers
paths it exercises, and boot-time hardware paths are exactly the ones it
can't. So this is a static check over the AST instead — it needs no path
coverage at all.

Deliberately approximate. It collects every underscore name LOADED anywhere
in a module, subtracts everything STORED anywhere in it (any scope, which
covers locals like `_second`) and everything explicitly imported. What's left
is a name that can only come from a star-import — which will not deliver it.
"""

import ast
import os

import pytest

MICROPYTHON_DIR = os.path.join(os.path.dirname(__file__), "..", "micropython")

# Bring-up scripts are standalone by design and run via `mpremote run`, not
# imported by main.py. They have no star-imports and aren't part of the split.
_STANDALONE = {"config", "config_friend1", "led_test", "led_sandbox",
               "imu_test", "i2c_scan", "rtc_test", "gesture_sandbox",
               "vibration_sandbox", "handling_test", "orientation_test",
               "low_pwm_test"}


def _firmware_modules():
    return sorted(
        f[:-3] for f in os.listdir(MICROPYTHON_DIR)
        if f.endswith(".py") and f[:-3] not in _STANDALONE
    )


@pytest.mark.parametrize("module", _firmware_modules())
def test_private_names_resolve(module):
    tree = ast.parse(open(os.path.join(MICROPYTHON_DIR, module + ".py")).read())

    loaded, stored, imported = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else stored).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            stored.add(node.name)
        elif isinstance(node, ast.arg):
            stored.add(node.arg)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Attribute):
            pass  # obj._attr is not a bare name — not our problem

    unresolved = {n for n in loaded - stored - imported
                  if n.startswith("_") and not n.startswith("__")}
    assert not unresolved, (
        "%s.py uses %s but never imports them. `import *` does not export "
        "underscore names — add an explicit `from <module> import ...`."
        % (module, ", ".join(sorted(unresolved)))
    )


@pytest.mark.parametrize("module", _firmware_modules())
def test_declared_globals_exist_at_module_level(module):
    """A `global X` whose X is never assigned at module level.

    This is a BLIND SPOT in every other check we have, and it shipped a
    NameError to hardware on 2026-08-24:

        File "gestures.py", line 74, in _get_imu
        NameError: name '_imu_i2c' isn't defined

    `_get_imu()` is a lazy singleton — it declares `global _imu_i2c` and then
    READS it (`if _imu_i2c is None:`) before ever assigning. The initialisers
    `_imu_i2c = None` were left behind in main.py by the V1.6 split.

    Why nothing caught it: a `global X` declaration makes X look defined to
    both ruff's F821 and to test_private_names_resolve above — and in general
    that is correct, since a global CAN be created by first assignment inside
    a function. It is only a bug when the function reads before writing, which
    is exactly the lazy-singleton pattern this firmware uses for every piece
    of hardware it touches (_imu_i2c, _rtc_i2c, _rtc_cache).

    Nor could the suite reach it: _get_imu() is I/O, so no host test calls it.

    Treating any unassigned `global` as an error is stricter than Python
    requires, but it matches how this codebase actually uses them.
    """
    tree = ast.parse(open(os.path.join(MICROPYTHON_DIR, module + ".py")).read())

    assigned = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)

    declared = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            declared.update(node.names)

    missing = declared - assigned
    assert not missing, (
        "%s.py declares `global %s` but never assigns %s at module level. "
        "A lazy singleton that reads before writing needs an initialiser "
        "(e.g. `%s = None`) in this module — `global` alone does not create it."
        % (module, ", ".join(sorted(missing)),
           "them" if len(missing) > 1 else "it", sorted(missing)[0])
    )
