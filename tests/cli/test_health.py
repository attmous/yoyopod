from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yoyopod_cli.health import app as health_app


runner = CliRunner()


def test_preflight_passes_with_valid_release_dir(tmp_path: Path) -> None:
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
    (release_dir / "venv").mkdir()
    (release_dir / "app").mkdir()
    (release_dir / "config").mkdir()
    # Materialize the required config files (preflight checks each).
    from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# placeholder\n")
    (release_dir / "bin").mkdir()
    launch = release_dir / "bin" / "launch"
    launch.write_text("#!/bin/sh\necho hi\n")
    launch.chmod(0o755)

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
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text(
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
    (release_dir / "venv").mkdir()
    (release_dir / "app").mkdir()
    (release_dir / "config").mkdir()
    from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# placeholder\n")
    # NO bin/launch — should fail
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1


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
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text(
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
    (release_dir / "venv").mkdir()
    (release_dir / "app").mkdir()
    (release_dir / "bin").mkdir()
    launch = release_dir / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    # NO config/ dir — should fail
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "config" in (result.stderr or result.stdout).lower()


@pytest.mark.skipif(sys.platform == "win32", reason="os.X_OK is always True on Windows")
def test_preflight_fails_on_non_executable_launcher(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text(
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
    (release_dir / "venv").mkdir()
    (release_dir / "app").mkdir()
    (release_dir / "config").mkdir()
    from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# placeholder\n")
    (release_dir / "bin").mkdir()
    launch = release_dir / "bin" / "launch"
    launch.write_text("#!/bin/sh\necho hi\n")
    launch.chmod(0o644)  # readable but NOT executable
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
    assert "inactive" in (result.stderr or result.stdout).lower() or "not active" in (
        result.stderr or result.stdout
    ).lower()


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
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text(
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
    (release_dir / "venv").mkdir()
    (release_dir / "app").mkdir()
    (release_dir / "config").mkdir()  # exists but EMPTY
    (release_dir / "bin").mkdir()
    launch = release_dir / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code == 1
    assert "core.yaml" in (result.stderr or result.stdout).lower()
