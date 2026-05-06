"""Import-graph regression tests for lazy screen loading."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SCREEN_PREFIXES = (
    "yoyopod.ui.screens.navigation",
    "yoyopod.ui.screens.music",
    "yoyopod.ui.screens.system",
    "yoyopod.ui.screens.voip",
)


def _loaded_screen_modules_for(module_name: str) -> list[str]:
    """Import one module in a fresh interpreter and report any feature screen modules."""

    env = os.environ.copy()
    pythonpath_parts = [str(REPO_ROOT / "src"), str(REPO_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    command = f"""
import importlib
import json
import sys

importlib.import_module({module_name!r})
prefixes = {FORBIDDEN_SCREEN_PREFIXES!r}
loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
)
print(json.dumps(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", command],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )
    return json.loads(result.stdout)


def test_importing_core_bootstrap_keeps_feature_screens_unloaded() -> None:
    """Importing the canonical bootstrap module should not eagerly import feature screens."""

    assert _loaded_screen_modules_for("yoyopod.core.bootstrap") == []


def test_importing_app_keeps_feature_screens_unloaded() -> None:
    """Importing the app shell should not eagerly import screen feature modules."""

    assert _loaded_screen_modules_for("yoyopod.app") == []
