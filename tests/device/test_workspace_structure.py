from __future__ import annotations

import subprocess
from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]
DEVICE_ROOT = REPO_ROOT / "device"


def _cargo_workspace_members() -> set[str]:
    with (DEVICE_ROOT / "Cargo.toml").open("rb") as handle:
        payload = tomllib.load(handle)
    return set(payload["workspace"]["members"])


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_device_workspace_has_expected_manifest() -> None:
    assert (DEVICE_ROOT / "Cargo.toml").is_file()
    assert (DEVICE_ROOT / "Cargo.lock").is_file()


def test_device_workspace_has_no_generated_target_member() -> None:
    members = _cargo_workspace_members()

    assert "target" not in members
    assert not any(member.startswith("target/") for member in members)


def test_device_workspace_tracks_lockfile_even_when_cargo_lock_is_ignored() -> None:
    tracked = _git("ls-files", "--error-unmatch", "device/Cargo.lock")
    assert tracked.returncode == 0

    ignored = _git("check-ignore", "-q", "device/Cargo.lock")
    assert ignored.returncode != 0


def test_old_yoyopod_rs_workspace_is_gone() -> None:
    assert not (REPO_ROOT / "yoyopod_rs").exists()
