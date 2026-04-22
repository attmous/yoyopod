from __future__ import annotations

import json
from pathlib import Path

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
    assert result.exit_code != 0


def test_preflight_fails_on_corrupt_manifest(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "manifest.json").write_text("{not json")
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code != 0


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
    result = runner.invoke(health_app, ["preflight", "--slot", str(release_dir)])
    assert result.exit_code != 0


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
    result = runner.invoke(health_app, ["live"])
    assert result.exit_code == 0
    assert "2026.04.22-abc" in result.stdout


def test_live_exits_nonzero_when_no_release_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", "/nonexistent/path.json")
    result = runner.invoke(health_app, ["live"])
    assert result.exit_code != 0
