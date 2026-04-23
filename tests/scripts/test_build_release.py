from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from yoyopod_cli.slot_contract import APP_NATIVE_RUNTIME_ARTIFACTS, SLOT_VENV_PYTHON

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
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")

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
    assert (result_dir / "config" / "app" / "core.yaml").exists()

    manifest = json.loads((result_dir / "manifest.json").read_text())
    assert manifest["version"] == "2026.04.22-test"
    assert manifest["channel"] == "dev"
    assert "full" in manifest["artifacts"]
    assert manifest["artifacts"]["full"]["type"] == "full"
    assert manifest["artifacts"]["full"]["size"] > 0
    with tarfile.open(out / "2026.04.22-test.tar.gz", "r:gz") as handle:
        assert "2026.04.22-test/manifest.json" in handle.getnames()


def test_build_writes_runtime_requirements_from_pyproject(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text(
        "[project]\n"
        "name='x'\n"
        "version='0.0.1'\n"
        'dependencies=["typer>=0.12.0", "gpiod<2; platform_system == \'Linux\'"]\n'
    )
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")

    slot = build_release.build(
        repo_root=fake_repo,
        output_root=tmp_path / "out",
        version="2026.04.22-reqs",
        channel="dev",
        skip_venv=True,
    )

    requirements = (slot / "runtime-requirements.txt").read_text(encoding="utf-8").splitlines()
    assert requirements == ["typer>=0.12.0", "gpiod<2; platform_system == 'Linux'"]


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
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")

    out = tmp_path / "out"
    build_release.build(
        repo_root=fake_repo,
        output_root=out,
        version="2026.04.22-test",
        channel="dev",
        skip_venv=True,
    )
    with pytest.raises(FileExistsError):
        build_release.build(
            repo_root=fake_repo,
            output_root=out,
            version="2026.04.22-test",
            channel="dev",
            skip_venv=True,
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


def test_build_release_script_runs_without_installed_checkout(tmp_path: Path) -> None:
    """CI slot containers run the script before installing the project package."""
    real_repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(real_repo / "scripts" / "build_release.py"),
            "--output",
            str(tmp_path / "out"),
            "--channel",
            "dev",
            "--version",
            "2026.04.22-no-site",
            "--skip-venv",
        ],
        cwd=real_repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "2026.04.22-no-site" / "manifest.json").is_file()


def test_build_normalizes_launcher_to_lf(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.1'\n")
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/usr/bin/env bash\r\nexit 0\r\n", encoding="utf-8", newline="\r\n")
    launch.chmod(0o755)

    slot = build_release.build(
        repo_root=fake_repo,
        output_root=tmp_path / "out",
        version="2026.04.22-lf",
        channel="dev",
        skip_venv=True,
    )

    bundled = slot / "bin" / "launch"
    contents = bundled.read_bytes()
    assert b"\r\n" not in contents
    assert contents.startswith(b"#!/usr/bin/env bash\n")


def test_build_can_skip_venv_when_requested(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "yoyopod").mkdir(parents=True)
    (fake_repo / "yoyopod" / "__init__.py").write_text("")
    (fake_repo / "yoyopod_cli").mkdir()
    (fake_repo / "yoyopod_cli" / "__init__.py").write_text("")
    (fake_repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.1'\n")
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")
    (fake_repo / "deploy" / "scripts").mkdir(parents=True)
    launch = fake_repo / "deploy" / "scripts" / "launch.sh"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)

    out = tmp_path / "out"
    slot = build_release.build(
        repo_root=fake_repo,
        output_root=out,
        version="2026.04.22-default",
        channel="dev",
        skip_venv=True,
    )
    assert (slot / "venv").is_dir()
    assert list((slot / "venv").iterdir()) == []


def test_build_release_cli_bundles_venv_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_build(**kwargs: object) -> Path:
        calls.update(kwargs)
        slot = tmp_path / "out" / "2026.04.22-default"
        slot.mkdir(parents=True)
        return slot

    monkeypatch.setattr(build_release, "build", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_release.py",
            "--output",
            str(tmp_path / "out"),
            "--channel",
            "dev",
            "--version",
            "2026.04.22-default",
        ],
    )

    build_release.main()

    assert calls["skip_venv"] is False


def test_build_release_cli_can_skip_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_build(**kwargs: object) -> Path:
        calls.update(kwargs)
        slot = tmp_path / "out" / "2026.04.22-skip"
        slot.mkdir(parents=True)
        return slot

    monkeypatch.setattr(build_release, "build", fake_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_release.py",
            "--output",
            str(tmp_path / "out"),
            "--channel",
            "dev",
            "--version",
            "2026.04.22-skip",
            "--skip-venv",
        ],
    )

    build_release.main()

    assert calls["skip_venv"] is True


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


def test_build_copies_native_runtime_artifacts_when_present(tmp_path: Path) -> None:
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
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = fake_repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n")

    slot = build_release.build(
        repo_root=fake_repo,
        output_root=tmp_path / "out",
        version="2026.04.22-native",
        channel="dev",
        skip_venv=True,
    )

    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        assert (slot / "app" / relative).is_file()


def test_build_with_venv_rejects_missing_native_runtime_artifacts(tmp_path: Path) -> None:
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
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")

    with pytest.raises(FileNotFoundError, match="native runtime artifact"):
        build_release.build(
            repo_root=fake_repo,
            output_root=tmp_path / "out",
            version="2026.04.22-native-missing",
            channel="dev",
            skip_venv=False,
        )


def test_build_with_venv_validates_self_contained_runtime_contract(tmp_path: Path) -> None:
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
    (fake_repo / "config" / "app").mkdir(parents=True)
    (fake_repo / "config" / "app" / "core.yaml").write_text("test: true\n")
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        target = fake_repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("shim\n")

    def _fake_resolve_venv(dest_venv: Path, requirements_path: Path, python_version: str) -> None:
        del requirements_path, python_version
        python_bin = dest_venv / "bin" / "python"
        python_bin.parent.mkdir(parents=True, exist_ok=True)
        python_bin.write_text("#!/bin/sh\nexit 0\n")
        python_bin.chmod(0o755)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(build_release, "_resolve_venv", _fake_resolve_venv)
        slot = build_release.build(
            repo_root=fake_repo,
            output_root=tmp_path / "out",
            version="2026.04.22-self-contained",
            channel="dev",
            skip_venv=False,
        )

    assert (slot / SLOT_VENV_PYTHON).is_file()
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        assert (slot / "app" / relative).is_file()
