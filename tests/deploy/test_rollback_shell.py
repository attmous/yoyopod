from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash script")

ROLLBACK_SH = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "rollback.sh"


def _make_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "yoyopod"
    releases = root / "releases"
    releases.mkdir(parents=True)
    v1 = releases / "v1"
    v2 = releases / "v2"
    v1.mkdir()
    v2.mkdir()
    current = root / "current"
    previous = root / "previous"
    current.symlink_to(v2)  # v2 is active, v1 was prior
    previous.symlink_to(v1)
    return root, current, previous, v1


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "YOYOPOD_ROOT": str(root), "YOYOPOD_SKIP_SYSTEMCTL": "1"}
    return subprocess.run(
        ["bash", str(ROLLBACK_SH)],
        env=env,
        capture_output=True,
        text=True,
    )


def test_rollback_swaps_current_and_previous(tmp_path: Path) -> None:
    root, current, previous, v1 = _make_layout(tmp_path)
    result = _run(root)
    assert result.returncode == 0, result.stderr
    assert current.resolve() == v1.resolve()
    assert previous.resolve() == (root / "releases" / "v2").resolve()


def test_rollback_fails_when_previous_missing(tmp_path: Path) -> None:
    root = tmp_path / "yoyopod"
    releases = root / "releases"
    releases.mkdir(parents=True)
    (releases / "v1").mkdir()
    (root / "current").symlink_to(releases / "v1")
    # no previous symlink
    result = _run(root)
    assert result.returncode != 0
    assert "previous" in result.stderr.lower()


def test_rollback_fails_when_current_is_not_symlink(tmp_path: Path) -> None:
    root = tmp_path / "yoyopod"
    root.mkdir()
    (root / "current").mkdir()  # real dir, not a symlink
    (root / "releases").mkdir()
    (root / "releases" / "v1").mkdir()
    (root / "previous").symlink_to(root / "releases" / "v1")
    result = _run(root)
    assert result.returncode != 0


def test_rollback_fails_when_previous_target_is_dangling(tmp_path: Path) -> None:
    root = tmp_path / "yoyopod"
    releases = root / "releases"
    releases.mkdir(parents=True)
    (releases / "v2").mkdir()
    (root / "current").symlink_to(releases / "v2")
    (root / "previous").symlink_to(releases / "missing")

    result = _run(root)

    assert result.returncode != 0
    assert "dangling" in result.stderr.lower() or "does not resolve" in result.stderr.lower()


def test_rollback_resets_systemd_start_limit_before_restart(tmp_path: Path) -> None:
    root, current, _previous, v1 = _make_layout(tmp_path)
    calls = tmp_path / "systemctl-calls.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$YOYOPOD_SYSTEMCTL_CALLS\"\n"
        "exit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    systemctl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "YOYOPOD_ROOT": str(root),
        "YOYOPOD_SYSTEMCTL_CALLS": str(calls),
    }

    result = subprocess.run(
        ["bash", str(ROLLBACK_SH)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert current.resolve() == v1.resolve()
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "reset-failed yoyopod-prod.service",
        "restart yoyopod-prod.service",
    ]


def test_rollback_self_locates_root_from_script_path(tmp_path: Path) -> None:
    """When YOYOPOD_ROOT is unset, ROOT is derived from the script's own path."""
    import shutil

    root = tmp_path / "yoyopod-alt"
    bin_dir = root / "bin"
    releases = root / "releases"
    bin_dir.mkdir(parents=True)
    releases.mkdir()
    (releases / "v1").mkdir()
    (releases / "v2").mkdir()
    (root / "current").symlink_to(releases / "v2")
    (root / "previous").symlink_to(releases / "v1")
    # Copy rollback.sh into the fake root.
    rollback_in_fake_root = bin_dir / "rollback.sh"
    shutil.copy(ROLLBACK_SH, rollback_in_fake_root)
    rollback_in_fake_root.chmod(0o755)
    env = {**os.environ, "YOYOPOD_SKIP_SYSTEMCTL": "1"}
    # Note: YOYOPOD_ROOT NOT set — script must self-locate.
    env.pop("YOYOPOD_ROOT", None)
    result = subprocess.run(
        ["bash", str(rollback_in_fake_root)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (root / "current").resolve() == (releases / "v1").resolve()
