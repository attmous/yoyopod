"""Tests for ``yoyopod release`` versioning and release packaging commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

import yoyopod_cli.release as release_cli
from yoyopod_cli._version import __version__
from yoyopod_cli.release import app


def test_current_prints_version_and_tag() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["current"])

    assert result.exit_code == 0
    assert f"version: {__version__}" in result.output
    assert f"tag: v{__version__}" in result.output


def test_bump_dry_run_shows_next_patch_version() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["bump", "patch", "--dry-run"])

    assert result.exit_code == 0
    assert result.output.strip() == release_cli._next_version(__version__, "patch")


def test_set_version_rewrites_version_file(monkeypatch, tmp_path: Path) -> None:
    version_file = tmp_path / "_version.py"
    version_file.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    monkeypatch.setattr(release_cli, "_VERSION_FILE", version_file)

    runner = CliRunner()
    result = runner.invoke(app, ["set-version", "0.2.0"])

    assert result.exit_code == 0
    assert '__version__ = "0.2.0"' in version_file.read_text(encoding="utf-8")


def test_build_fails_when_tag_does_not_match_version(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(release_cli, "_DIST_DIR", tmp_path / "dist")

    runner = CliRunner()
    result = runner.invoke(app, ["build", "--check-tag", "v9.9.9", "--allow-dirty"])

    assert result.exit_code != 0
    assert "Release tag mismatch" in result.output


def test_build_creates_release_metadata_and_checksums(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    monkeypatch.setattr(release_cli, "_DIST_DIR", dist_dir)
    monkeypatch.setattr(release_cli, "_tracked_worktree_is_clean", lambda: True)
    monkeypatch.setattr(release_cli, "_git_sha", lambda: "abc123")
    monkeypatch.setattr(release_cli, "_current_version", lambda: __version__)

    sdist_name = f"yoyopod-{__version__}.tar.gz"
    wheel_name = f"yoyopod-{__version__}-py3-none-any.whl"
    repo_tar_name = f"yoyopod-core-{__version__}.tar.gz"
    repo_zip_name = f"yoyopod-core-{__version__}.zip"

    def fake_run(
        command: list[str],
        *,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, cwd
        if command[:2] == ["uv", "build"]:
            (dist_dir / sdist_name).write_text("sdist", encoding="utf-8")
            (dist_dir / wheel_name).write_text("wheel", encoding="utf-8")
        elif command[:2] == ["git", "archive"]:
            output_index = command.index("-o") + 1
            Path(command[output_index]).write_text("bundle", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(release_cli, "_run", fake_run)

    runner = CliRunner()
    result = runner.invoke(app, ["build", "--allow-dirty"])

    assert result.exit_code == 0
    metadata = json.loads((dist_dir / "release-metadata.json").read_text(encoding="utf-8"))
    assert metadata["version"] == __version__
    assert metadata["tag"] == f"v{__version__}"
    assert metadata["git_sha"] == "abc123"
    checksums = (dist_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "release-metadata.json" in checksums
    assert repo_tar_name in checksums
    assert repo_zip_name in checksums
    assert wheel_name in checksums
    assert sdist_name in checksums


def test_build_uses_updated_version_after_set_version(monkeypatch, tmp_path: Path) -> None:
    version_file = tmp_path / "_version.py"
    version_file.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    dist_dir = tmp_path / "dist"

    monkeypatch.setattr(release_cli, "_VERSION_FILE", version_file)
    monkeypatch.setattr(release_cli, "_DIST_DIR", dist_dir)
    monkeypatch.setattr(release_cli, "_tracked_worktree_is_clean", lambda: True)
    monkeypatch.setattr(release_cli, "_git_sha", lambda: "abc123")

    def fake_run(
        command: list[str],
        *,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, cwd
        version = release_cli._current_version()
        if command[:2] == ["uv", "build"]:
            (dist_dir / f"yoyopod-{version}.tar.gz").write_text("sdist", encoding="utf-8")
            (dist_dir / f"yoyopod-{version}-py3-none-any.whl").write_text("wheel", encoding="utf-8")
        elif command[:2] == ["git", "archive"]:
            output_index = command.index("-o") + 1
            Path(command[output_index]).write_text("bundle", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(release_cli, "_run", fake_run)

    runner = CliRunner()
    set_result = runner.invoke(app, ["set-version", "0.2.0"])
    assert set_result.exit_code == 0

    build_result = runner.invoke(app, ["build", "--allow-dirty", "--check-tag", "v0.2.0"])
    assert build_result.exit_code == 0
    metadata = json.loads((dist_dir / "release-metadata.json").read_text(encoding="utf-8"))
    assert metadata["version"] == "0.2.0"
    assert metadata["tag"] == "v0.2.0"


def test_build_recomputes_metadata_hash_when_dist_already_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "release-metadata.json").write_text("stale-metadata\n", encoding="utf-8")
    (dist_dir / "SHA256SUMS.txt").write_text("stale-checksums\n", encoding="utf-8")

    monkeypatch.setattr(release_cli, "_DIST_DIR", dist_dir)
    monkeypatch.setattr(release_cli, "_tracked_worktree_is_clean", lambda: True)
    monkeypatch.setattr(release_cli, "_git_sha", lambda: "abc123")
    monkeypatch.setattr(release_cli, "_current_version", lambda: __version__)

    sdist_name = f"yoyopod-{__version__}.tar.gz"
    wheel_name = f"yoyopod-{__version__}-py3-none-any.whl"

    def fake_run(
        command: list[str],
        *,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, cwd
        if command[:2] == ["uv", "build"]:
            (dist_dir / sdist_name).write_text("sdist", encoding="utf-8")
            (dist_dir / wheel_name).write_text("wheel", encoding="utf-8")
        elif command[:2] == ["git", "archive"]:
            output_index = command.index("-o") + 1
            Path(command[output_index]).write_text("bundle", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(release_cli, "_run", fake_run)

    runner = CliRunner()
    result = runner.invoke(app, ["build", "--allow-dirty", "--no-clean"])

    assert result.exit_code == 0

    metadata_path = dist_dir / "release-metadata.json"
    metadata_sha = release_cli._artifact_sha256(metadata_path)
    checksum_lines = (dist_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    metadata_lines = [line for line in checksum_lines if line.endswith("  release-metadata.json")]
    assert len(metadata_lines) == 1
    assert metadata_lines[0] == f"{metadata_sha}  release-metadata.json"
