from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod_cli.slot_contract import SLOT_NATIVE_RUNTIME_ARTIFACTS

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash script")

INSTALL_RELEASE_SH = (
    Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "install_release.sh"
)


def _make_slot_artifact(
    tmp_path: Path, version: str, *, manifest_version: str | None = None
) -> Path:
    slot = tmp_path / version
    artifact = tmp_path / f"{version}.tar.gz"

    (slot / "venv" / "bin").mkdir(parents=True)
    python_bin = slot / "venv" / "bin" / "python"
    python_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    python_bin.chmod(0o755)

    (slot / "app" / "yoyopod_cli").mkdir(parents=True)
    for relative in SLOT_NATIVE_RUNTIME_ARTIFACTS:
        target = slot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"shim")

    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = slot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test: true\n", encoding="utf-8", newline="\n")

    launch = slot / "bin" / "launch"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    launch.chmod(0o755)

    manifest = slot / "manifest.json"
    manifest.write_text(
        json.dumps({"version": manifest_version or version, "channel": "dev"}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with tarfile.open(artifact, "w:gz") as handle:
        handle.add(slot, arcname=slot.name)

    return artifact


def test_install_release_uses_slot_state_tmp_and_supports_file_urls(tmp_path: Path) -> None:
    version = "test-install-url"
    artifact = _make_slot_artifact(tmp_path, version)
    root = tmp_path / "yoyopod"
    env = {
        **os.environ,
        "YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT": "1",
        "YOYOPOD_SKIP_SYSTEMCTL": "1",
    }

    result = subprocess.run(
        [
            "bash",
            "-x",
            str(INSTALL_RELEASE_SH),
            f"--root={root}",
            f"--url={artifact.resolve().as_uri()}",
            "--first-deploy",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert str(root / "state" / "tmp") in result.stderr
    assert (root / "current").resolve() == (root / "releases" / version).resolve()
    assert not (root / "previous").exists()
    assert "install-release: skipping systemctl" in result.stdout


def test_install_release_live_probe_requires_extended_stability() -> None:
    script = INSTALL_RELEASE_SH.read_text(encoding="utf-8")

    assert "local required_stable=120" in script
    assert 'local last_pid=""' in script


def test_install_release_rejects_path_like_manifest_version(tmp_path: Path) -> None:
    artifact = _make_slot_artifact(tmp_path, "safe-slot", manifest_version="../../escape")
    root = tmp_path / "yoyopod"
    env = {
        **os.environ,
        "YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT": "1",
        "YOYOPOD_SKIP_SYSTEMCTL": "1",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_RELEASE_SH),
            f"--root={root}",
            f"--artifact={artifact}",
            "--first-deploy",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unsafe version" in result.stderr.lower()
    assert not (tmp_path / "escape").exists()


def test_install_release_rejects_non_object_manifest(tmp_path: Path) -> None:
    version = "bad-manifest-root"
    artifact = _make_slot_artifact(tmp_path, version)
    with tarfile.open(artifact, "r:gz") as source:
        source.extractall(tmp_path / "rewrite", filter="data")
    manifest = tmp_path / "rewrite" / version / "manifest.json"
    manifest.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with tarfile.open(artifact, "w:gz") as output:
        output.add(tmp_path / "rewrite" / version, arcname=version)
    root = tmp_path / "yoyopod"
    env = {
        **os.environ,
        "YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT": "1",
        "YOYOPOD_SKIP_SYSTEMCTL": "1",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_RELEASE_SH),
            f"--root={root}",
            f"--artifact={artifact}",
            "--first-deploy",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "manifest root must be an object" in result.stderr.lower()


def test_install_release_rejects_dangling_previous_symlink(tmp_path: Path) -> None:
    version = "dangling-previous"
    artifact = _make_slot_artifact(tmp_path, version)
    root = tmp_path / "yoyopod"
    (root / "releases").mkdir(parents=True)
    (root / "previous").symlink_to(root / "releases" / "missing")
    env = {
        **os.environ,
        "YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT": "1",
        "YOYOPOD_SKIP_SYSTEMCTL": "1",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_RELEASE_SH),
            f"--root={root}",
            f"--artifact={artifact}",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "previous rollback target is dangling" in result.stderr.lower()
    assert not (root / "current").exists()


def test_install_release_rolls_back_when_restart_fails(tmp_path: Path) -> None:
    version = "restart-fails"
    artifact = _make_slot_artifact(tmp_path, version)
    root = tmp_path / "yoyopod"
    old_slot = root / "releases" / "old"
    old_slot.mkdir(parents=True)
    (root / "current").symlink_to(old_slot)
    (root / "previous").symlink_to(old_slot)
    rollback_marker = tmp_path / "rollback-called"
    rollback = root / "bin" / "rollback.sh"
    rollback.parent.mkdir(parents=True)
    rollback.write_text(
        f"#!/usr/bin/env bash\ntouch {rollback_marker}\nexit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    rollback.chmod(0o755)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "reset-failed" ]; then exit 0; fi\n'
        'if [ "$1" = "restart" ]; then exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    systemctl.chmod(0o755)
    env = {
        **os.environ,
        "YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT": "1",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_RELEASE_SH),
            f"--root={root}",
            f"--artifact={artifact}",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert rollback_marker.exists()
    assert "restart failed, attempting rollback" in result.stderr.lower()
