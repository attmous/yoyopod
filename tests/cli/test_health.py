from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod_cli.health import app as health_app
from yoyopod_cli.slot_contract import (
    APP_NATIVE_RUNTIME_ARTIFACTS,
    SLOT_PYTHON_BIN,
    SLOT_PYTHON_STDLIB_MARKER,
    SLOT_VENV_PYTHON,
)

runner = CliRunner()


def _write_release_dir(tmp_path: Path) -> Path:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "2026.04.22-abc",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 10}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# placeholder\n", encoding="utf-8")

    python_bin = release_dir / SLOT_VENV_PYTHON
    python_bin.parent.mkdir(parents=True, exist_ok=True)
    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_bin.chmod(0o755)
    runtime_python = release_dir / SLOT_PYTHON_BIN
    runtime_python.parent.mkdir(parents=True, exist_ok=True)
    runtime_python.write_text("python\n", encoding="utf-8")
    runtime_stdlib = release_dir / SLOT_PYTHON_STDLIB_MARKER
    runtime_stdlib.parent.mkdir(parents=True, exist_ok=True)
    runtime_stdlib.write_text("# stdlib marker\n", encoding="utf-8")

    (release_dir / "app").mkdir(exist_ok=True)
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = release_dir / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n", encoding="utf-8")

    (release_dir / "bin").mkdir(exist_ok=True)
    launch = release_dir / "bin" / "launch"
    launch.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    launch.chmod(0o755)
    return release_dir


def test_preflight_passes_with_valid_release_dir(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 0, result.stdout


def test_preflight_fails_on_missing_manifest(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1


def test_preflight_fails_on_corrupt_manifest(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text("{not json")
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1


def test_preflight_fails_on_missing_launcher(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    (release_dir / "bin" / "launch").unlink()

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1


def test_preflight_fails_on_missing_self_contained_python(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    (release_dir / SLOT_VENV_PYTHON).unlink()

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "venv/bin/python" in (result.stderr or result.stdout)


def test_preflight_allows_hydrated_runtime_without_bundled_python(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    shutil.rmtree(release_dir / "python")

    strict = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert strict.exit_code == 1

    hydrated = runner.invoke(
        health_app,
        ["preflight", "--slot", str(release_dir), "--allow-hydrated-runtime"],
    )
    assert hydrated.exit_code == 0, hydrated.stdout


def test_preflight_fails_on_missing_native_runtime_shim(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    missing = release_dir / "app" / APP_NATIVE_RUNTIME_ARTIFACTS[0]
    missing.unlink()

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert missing.name in (result.stderr or result.stdout)


def test_live_reports_current_release_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "2026.04.22-abc",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 10}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    result = runner.invoke(health_app, ["live", "--skip-systemd"])
    assert result.exit_code == 0
    assert "version=2026.04.22-abc" in result.stdout
    assert "2026.04.22-abc" in result.stdout


def test_live_exits_nonzero_when_no_release_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", "/nonexistent/path.json")
    result = runner.invoke(health_app, ["live", "--skip-systemd"])
    assert result.exit_code == 1


def test_preflight_fails_on_missing_config(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    shutil.rmtree(release_dir / "config")

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "config" in (result.stderr or result.stdout).lower()


@pytest.mark.skipif(sys.platform == "win32", reason="os.X_OK is always True on Windows")
def test_preflight_fails_on_non_executable_launcher(tmp_path: Path) -> None:
    release_dir = _write_release_dir(tmp_path)
    launch = release_dir / "bin" / "launch"
    launch.chmod(0o644)
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "not executable" in (result.stderr or result.stdout).lower()


def test_live_fails_when_systemctl_reports_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "x",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 10}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    fake_result = MagicMock()
    fake_result.stdout = "inactive\n"
    with patch("yoyopod_cli.health.subprocess.run", return_value=fake_result):
        result = runner.invoke(health_app, ["live"])
    assert result.exit_code == 1
    assert (
        "inactive" in (result.stderr or result.stdout).lower()
        or "not active" in (result.stderr or result.stdout).lower()
    )


def test_live_passes_when_systemctl_reports_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "2026.04.22-abc",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 10}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    fake_result = MagicMock()
    fake_result.stdout = "active\n"
    with patch("yoyopod_cli.health.subprocess.run", return_value=fake_result):
        result = runner.invoke(health_app, ["live"])
    assert result.exit_code == 0
    assert "version=2026.04.22-abc" in result.stdout


def test_preflight_fails_when_required_config_file_missing(tmp_path: Path) -> None:
    """Empty config/ dir doesn't satisfy the runtime contract."""
    release_dir = _write_release_dir(tmp_path)
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = release_dir / relative
        if target.name == "core.yaml":
            target.unlink()
            break

    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "core.yaml" in (result.stderr or result.stdout).lower()
