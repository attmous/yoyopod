from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
sys.path.insert(0, _SCRIPTS_DIR)
import build_release  # noqa: E402

sys.path.remove(_SCRIPTS_DIR)


def test_compute_version_from_git_or_fallback(tmp_path: Path) -> None:
    version = build_release.compute_version(fallback_date="2026-04-22", git_sha=None)
    assert version == "2026.04.22-dev"


def test_compute_version_embeds_short_sha() -> None:
    version = build_release.compute_version(fallback_date="2026-04-22", git_sha="abc12345deadbeef")
    assert version == "2026.04.22-abc12345"


def test_build_writes_manifest(tmp_path: Path) -> None:
    """Integration: point build at a tiny fake repo and check the output shape.

    The --skip-venv flag lets us assert the directory structure and manifest
    while skipping `uv pip install` (which would be slow and require network).
    """
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod" / "main.py").write_text("def main():\n    pass\n")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.1'\n")
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)

    out = tmp_path / "out"
    result_dir = build_release.build(
        repo_root=fake_repo,
        output_root=out,
        version="2026.04.22-test",
        channel="dev",
        skip_venv=True,
    )

    assert result_dir == out / "2026.04.22-test"
    assert (result_dir / "manifest.json").exists()
    assert (result_dir / "app" / "yoyopod" / "main.py").exists()
    assert (result_dir / "bin" / "launch").exists()
    assert os.access(result_dir / "bin" / "launch", os.X_OK)

    manifest = json.loads((result_dir / "manifest.json").read_text())
    assert manifest["version"] == "2026.04.22-test"
    assert manifest["channel"] == "dev"
    assert "full" in manifest["artifacts"]
    assert manifest["artifacts"]["full"]["type"] == "full"
    assert manifest["artifacts"]["full"]["size"] > 0


def test_build_refuses_existing_output_dir(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.1'\n")
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)

    out = tmp_path / "out"
    build_release.build(
        repo_root=fake_repo, output_root=out, version="2026.04.22-test",
        channel="dev", skip_venv=True,
    )
    with pytest.raises(FileExistsError):
        build_release.build(
            repo_root=fake_repo, output_root=out, version="2026.04.22-test",
            channel="dev", skip_venv=True,
        )


def test_build_uses_real_launcher_from_deploy_scripts(tmp_path: Path) -> None:
    """The real deploy/scripts/launch.sh in the repo is picked up by the build."""
    # Use the real repo root, not a fake.
    real_repo = Path(__file__).resolve().parents[2]
    # Confirm the real launcher exists (this also documents the contract).
    real_launcher = real_repo / "deploy" / "scripts" / "launch.sh"
    assert real_launcher.exists(), f"deploy/scripts/launch.sh missing at {real_launcher}"

    out = tmp_path / "out"
    slot = build_release.build(
        repo_root=real_repo,
        output_root=out,
        version="2026.04.22-launcher-test",
        channel="dev",
        skip_venv=True,
    )
    bundled = slot / "bin" / "launch"
    assert bundled.exists()
    # First line should be the bash shebang.
    first_line = bundled.read_text().splitlines()[0]
    assert first_line.startswith("#!/usr/bin/env bash")


def test_build_rejects_invalid_channel(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.1'\n")
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)

    with pytest.raises(ValueError, match="channel"):
        build_release.build(
            repo_root=fake_repo,
            output_root=tmp_path / "out",
            version="2026.04.22-test",
            channel="weird",
            skip_venv=True,
        )
