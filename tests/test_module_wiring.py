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
