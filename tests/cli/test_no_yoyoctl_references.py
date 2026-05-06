"""Regression guard: `yoyoctl` binary name must not appear anywhere except in
historical archive documentation (docs/archive/, docs/superpowers/ design/plan
files which describe the migration itself, and .git/)."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths that are allowed to keep historical mentions of the old binary name —
# these describe the migration itself and should not be scrubbed.
ALLOWED_PATHS = (
    "docs/archive/",
    "docs/superpowers/specs/",
    "docs/superpowers/plans/",
    ".github/",  # workflow history
    # The guard test itself references the old name in assertion messages and
    # documentation strings, so it must be excluded from its own check.
        "tests/cli/test_no_yoyoctl_references.py",
)

# The old binary name we're guarding against re-introduction of.
_OLD_BINARY = "yoyoctl"


def _path_is_allowed(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    return any(normalized.startswith(prefix) or normalized == prefix for prefix in ALLOWED_PATHS)


def test_no_old_binary_references_outside_historical_docs() -> None:
    result = subprocess.run(
        ["git", "grep", "-l", _OLD_BINARY],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    # git grep returns 1 (and empty stdout) when no matches; 0 when matches.
    if result.returncode not in (0, 1):
        raise AssertionError(f"git grep failed: {result.stderr}")

    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    unexpected = [f for f in files if not _path_is_allowed(f)]
    assert not unexpected, (
        f"`{_OLD_BINARY}` references found outside historical doc paths. "
        f"The binary was renamed to `yoyopod` — these must be updated.\nFiles: {unexpected}"
    )


def test_no_old_binary_references_in_runtime_code() -> None:
    """Runtime and operations code must never reference the old binary name."""
    result = subprocess.run(
        ["git", "grep", "-l", _OLD_BINARY, "--", "device/", "yoyopod_cli/"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(f"git grep failed: {result.stderr}")

    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert not files, (
        f"`{_OLD_BINARY}` found in runtime code. The binary was renamed to `yoyopod`.\n"
        f"Files: {files}"
    )
