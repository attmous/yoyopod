from __future__ import annotations

import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from yoyopod_cli.contracts.setup import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod_cli.remote_release import app as release_app
from yoyopod_cli.slot_contract import (
    APP_NATIVE_RUNTIME_ARTIFACTS,
    SLOT_VENV_PYTHON,
    SLOT_VOICE_WORKER_ARTIFACT,
    slot_python_bin,
    slot_python_stdlib_marker,
)

runner = CliRunner()


def _write_slot(
    tmp_path: Path,
    version: str,
    *,
    self_contained: bool = True,
    python_version: str = "3.12",
) -> Path:
    slot = tmp_path / version
    slot.mkdir()
    (slot / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "version": version,
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 100}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    (slot / "runtime-requirements.txt").write_text("typer>=0.12.0\n", encoding="utf-8")
    (slot / "app").mkdir()
    (slot / "bin").mkdir()
    launch = slot / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launch.chmod(0o755)
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = slot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# placeholder\n", encoding="utf-8")

    if self_contained:
        python_bin = slot / SLOT_VENV_PYTHON
        python_bin.parent.mkdir(parents=True, exist_ok=True)
        python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python_bin.chmod(0o755)
        runtime_python = slot / slot_python_bin(python_version)
        runtime_python.parent.mkdir(parents=True, exist_ok=True)
        runtime_python.write_text("python\n", encoding="utf-8")
        runtime_stdlib = slot / slot_python_stdlib_marker(python_version)
        runtime_stdlib.parent.mkdir(parents=True, exist_ok=True)
        runtime_stdlib.write_text("# stdlib marker\n", encoding="utf-8")
        for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
            target = slot / "app" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("shim\n", encoding="utf-8")
        worker = slot / SLOT_VOICE_WORKER_ARTIFACT
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text("worker\n", encoding="utf-8")
    else:
        (slot / "venv").mkdir()

    return slot


def _write_slot_tarball(
    tmp_path: Path,
    version: str,
    *,
    self_contained: bool = True,
    python_version: str = "3.12",
) -> Path:
    slot = _write_slot(
        tmp_path,
        version,
        self_contained=self_contained,
        python_version=python_version,
    )
    artifact = tmp_path / f"{version}.tar.gz"
    with tarfile.open(artifact, "w:gz") as handle:
        handle.add(slot, arcname=slot.name)
    return artifact


def _fake_conn() -> MagicMock:
    conn = MagicMock()
    conn.host = "test-pi.local"
    conn.user = "pi"
    return conn


@patch("yoyopod_cli.remote_release.run_remote")
@patch("yoyopod_cli.remote_release.subprocess.run")
def test_rsync_to_pi_uses_ssh_transport(
    run_mock: MagicMock,
    run_remote_mock: MagicMock,
    tmp_path: Path,
) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 0
    run_mock.return_value = fake_result
    run_remote_mock.return_value = 0

    from yoyopod_cli.remote_release import _rsync_to_pi

    rc = _rsync_to_pi(_fake_conn(), tmp_path, "2026.04.22-abc")
    command = run_mock.call_args[0][0]
    assert rc == 0
    assert command[:4] == ["rsync", "-az", "-e", "ssh"]
    assert "chmod 755" in run_remote_mock.call_args[0][1]
    assert run_remote_mock.call_args.kwargs["workdir"] is None


@patch("yoyopod_cli.remote_release.run_remote")
@patch("yoyopod_cli.remote_release.subprocess.run")
def test_rsync_to_pi_falls_back_to_scp_when_rsync_fails(
    run_mock: MagicMock,
    run_remote_mock: MagicMock,
    tmp_path: Path,
) -> None:
    rsync_result = MagicMock()
    rsync_result.returncode = 12
    scp_result = MagicMock()
    scp_result.returncode = 0
    run_mock.side_effect = [rsync_result, scp_result]
    run_remote_mock.return_value = 0

    from yoyopod_cli.remote_release import _rsync_to_pi

    rc = _rsync_to_pi(_fake_conn(), tmp_path / "2026.04.22-abc", "2026.04.22-abc")
    assert rc == 0
    assert run_mock.call_args_list[1][0][0][:2] == ["scp", "-r"]
    assert "2026.04.22-abc/." in run_mock.call_args_list[1][0][0][2]
    assert run_remote_mock.call_count == 2
    assert "chmod 755" in run_remote_mock.call_args_list[1][0][1]
    assert run_remote_mock.call_args_list[0].kwargs["workdir"] is None
    assert run_remote_mock.call_args_list[1].kwargs["workdir"] is None


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_runs_rsync_preflight_flip_live_for_self_contained_slot(
    live_probe: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code == 0, result.stdout

    rsync.assert_called_once()
    hydrate.assert_not_called()
    preflight.assert_called_once()
    flip.assert_called_once()
    live_probe.assert_called_once()
    assert "self-contained slot detected" in result.stdout.lower()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
def test_push_rejects_source_only_slot_without_hydrate_flag(
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=False)

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "not self-contained" in combined.lower()
    assert "hydrate-on-target" in combined


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_hydrates_source_only_slot_when_flag_is_set(
    live_probe: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=False)
    rsync.return_value = 0
    hydrate.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(slot), "--hydrate-on-target"])
    assert result.exit_code == 0, result.stdout
    hydrate.assert_called_once()
    preflight.assert_called_once_with(
        conn.return_value,
        "2026.04.22-abc",
        allow_hydrated_runtime=True,
    )


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_accepts_self_contained_tarball(
    live_probe: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    artifact = _write_slot_tarball(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(artifact)])
    assert result.exit_code == 0, result.stdout
    hydrate.assert_not_called()
    rsync.assert_called_once()
    uploaded_slot = rsync.call_args[0][1]
    assert uploaded_slot.name == "2026.04.22-abc"


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_accepts_self_contained_tarball_with_non_default_python(
    live_probe: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    artifact = _write_slot_tarball(
        tmp_path,
        "2026.04.22-py311",
        self_contained=True,
        python_version="3.11",
    )
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(artifact)])

    assert result.exit_code == 0, result.stdout
    hydrate.assert_not_called()
    preflight.assert_called_once_with(
        conn.return_value,
        "2026.04.22-py311",
        allow_hydrated_runtime=False,
    )


def test_safe_extract_tarball_rejects_symlink_escape_on_legacy_python(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoyopod_cli.remote_release import _safe_extract_tarball

    outside = tmp_path / "outside"
    outside.mkdir()
    artifact = tmp_path / "malicious.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("owned\n", encoding="utf-8")
    with tarfile.open(artifact, "w:gz") as handle:
        link = tarfile.TarInfo("slot/link")
        link.type = tarfile.SYMTYPE
        link.linkname = str(outside)
        handle.addfile(link)
        handle.add(payload, arcname="slot/link/pwned.txt")

    original_extractall = tarfile.TarFile.extractall

    def python311_extractall(self, path=".", members=None, *, numeric_owner=False, filter=None):
        if filter is not None:
            raise TypeError("filter is unsupported")
        return original_extractall(self, path, members, numeric_owner=numeric_owner)

    monkeypatch.setattr(tarfile.TarFile, "extractall", python311_extractall)

    try:
        _safe_extract_tarball(artifact, tmp_path / "stage")
    except ValueError as exc:
        assert "unsafe" in str(exc).lower()
    else:
        raise AssertionError("expected unsafe tarball to be rejected")
    assert not (outside / "pwned.txt").exists()


def test_safe_extract_tarball_allows_internal_venv_symlink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoyopod_cli.remote_release import _safe_extract_tarball

    artifact = tmp_path / "venv.tar.gz"
    with tarfile.open(artifact, "w:gz") as handle:
        python3 = tarfile.TarInfo("slot/venv/bin/python3")
        python3.size = 0
        handle.addfile(python3)
        link = tarfile.TarInfo("slot/venv/bin/python")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3"
        handle.addfile(link)

    monkeypatch.setattr(tarfile.TarFile, "extractall", lambda *args, **kwargs: None)

    _safe_extract_tarball(artifact, tmp_path / "stage")


def test_safe_extract_tarball_rejects_hardlink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoyopod_cli.remote_release import _safe_extract_tarball

    artifact = tmp_path / "hardlink.tar.gz"
    with tarfile.open(artifact, "w:gz") as handle:
        target = tarfile.TarInfo("slot/target")
        target.size = 0
        handle.addfile(target)
        link = tarfile.TarInfo("slot/link")
        link.type = tarfile.LNKTYPE
        link.linkname = "slot/target"
        handle.addfile(link)

    monkeypatch.setattr(tarfile.TarFile, "extractall", lambda *args, **kwargs: None)

    try:
        _safe_extract_tarball(artifact, tmp_path / "stage")
    except ValueError as exc:
        assert "hard link" in str(exc).lower()
    else:
        raise AssertionError("expected hardlink tarball to be rejected")


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._cleanup_remote_slot")
def test_push_aborts_and_cleans_up_on_hydration_fail(
    cleanup: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=False)
    rsync.return_value = 0
    hydrate.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot), "--hydrate-on-target"])
    assert result.exit_code != 0
    cleanup.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._cleanup_remote_slot")
def test_push_aborts_and_cleans_up_on_transfer_fail(
    cleanup: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 12

    result = runner.invoke(release_app, ["push", str(slot)])

    assert result.exit_code != 0
    cleanup.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._cleanup_remote_slot")
def test_push_aborts_and_cleans_up_on_preflight_fail(
    cleanup: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    hydrate.assert_not_called()
    flip.assert_not_called()
    cleanup.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_push_rolls_back_on_live_fail(
    rollback: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    hydrate.assert_not_called()
    rollback.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_push_rolls_back_on_flip_or_restart_fail(
    rollback: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])

    assert result.exit_code != 0
    hydrate.assert_not_called()
    live.assert_not_called()
    rollback.assert_called_once()


def test_push_rejects_non_slot_directory(tmp_path: Path) -> None:
    bogus = tmp_path / "not_a_slot"
    bogus.mkdir()
    result = runner.invoke(release_app, ["push", str(bogus)])
    assert result.exit_code != 0


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_rollback_invokes_pi_side(rollback: MagicMock, conn: MagicMock) -> None:
    conn.return_value = _fake_conn()
    rollback.return_value = 0
    result = runner.invoke(release_app, ["rollback"])
    assert result.exit_code == 0
    rollback.assert_called_once()


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._status_from_pi")
def test_status_prints_current_and_previous(status: MagicMock, conn: MagicMock) -> None:
    conn.return_value = _fake_conn()
    status.return_value = "current=2026.04.22-abc\nprevious=2026.04.20-def\nhealth=ok\n"
    result = runner.invoke(release_app, ["status"])
    assert result.exit_code == 0
    assert "2026.04.22-abc" in result.stdout
    assert "2026.04.20-def" in result.stdout


@patch("yoyopod_cli.remote_release.run_remote_capture")
@patch("yoyopod_cli.remote_release._conn")
def test_status_surfaces_ssh_failure(conn: MagicMock, capture: MagicMock) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "fake-host"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    fake_result = MagicMock()
    fake_result.returncode = 255
    fake_result.stdout = ""
    fake_result.stderr = "ssh: Could not resolve hostname fake-host"
    capture.return_value = fake_result

    result = runner.invoke(release_app, ["status"])
    assert result.exit_code != 0
    out = (result.stderr or result.stdout).lower()
    assert "failed" in out or "could not resolve" in out


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_push_surfaces_rollback_failure_when_rollback_also_fails(
    rollback: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 1
    rollback.return_value = 2

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    assert "rollback also failed" in (result.stderr or result.stdout).lower()


@patch("yoyopod_cli.remote_release.load_slot_paths")
@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
def test_push_uses_slotpaths_root_override(
    conn: MagicMock,
    check_rb: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    state: MagicMock,
    load_paths: MagicMock,
    tmp_path: Path,
) -> None:
    import yoyopod_cli.remote_release as rr
    from yoyopod_cli.paths import SlotPaths

    load_paths.return_value = SlotPaths(root="/srv/yoyopod-alt")
    rr._slot_paths_cache = None

    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    check_rb.return_value = 0
    state.return_value = "NEW"
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0

    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    result = runner.invoke(release_app, ["push", str(slot)])

    rr._slot_paths_cache = None

    assert result.exit_code == 0, result.stdout
    assert "/srv/yoyopod-alt" in result.stdout
    hydrate.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
def test_push_refuses_when_no_rollback_path_without_flag(
    rsync: MagicMock,
    check: MagicMock,
    conn: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    check.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "first-deploy" in combined.lower()
    rsync.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_with_first_deploy_flag_skips_rollback_check(
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    state.return_value = "NEW"
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0

    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)
    result = runner.invoke(release_app, ["push", str(slot), "--first-deploy"])
    assert result.exit_code == 0, result.stdout
    check.assert_not_called()
    hydrate.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._conn")
def test_push_refuses_to_overwrite_existing_slot_without_force(
    conn: MagicMock,
    rsync: MagicMock,
    check: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    state.return_value = "EXISTS"
    check.return_value = 0
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    assert "already exists" in (result.stderr or result.stdout).lower()
    rsync.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._hydrate_slot_on_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._conn")
def test_push_with_force_overwrites_non_current_slot(
    conn: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    hydrate: MagicMock,
    rsync: MagicMock,
    check: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    state.return_value = "EXISTS"
    check.return_value = 0
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)

    result = runner.invoke(release_app, ["push", str(slot), "--force"])
    assert result.exit_code == 0, result.stdout
    rsync.assert_called_once()
    hydrate.assert_not_called()


@patch("yoyopod_cli.remote_release.run_remote")
def test_live_probe_command_uses_shell_only_status_check(run_remote_mock: MagicMock) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    run_remote_mock.return_value = 0

    from yoyopod_cli.remote_release import _run_live_probe_on_pi

    _run_live_probe_on_pi(fake_conn, "2026.04.22-abc", timeout_s=1)
    cmd = run_remote_mock.call_args[0][1]
    assert "systemctl is-active --quiet" in cmd
    assert "/proc/$pid/cwd" in cmd
    assert 'basename "$slot"' in cmd
    assert "required_stable=120" in cmd
    assert "last_pid=" in cmd
    assert "stable=$((stable + 1))" in cmd
    assert "YOYOPOD_RELEASE_MANIFEST=" not in cmd
    assert "from yoyopod_cli.health import app; app()" not in cmd


@patch("yoyopod_cli.remote_release.run_remote")
def test_flip_symlinks_only_sets_previous_when_current_resolves(run_remote_mock: MagicMock) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    run_remote_mock.return_value = 0

    from yoyopod_cli.remote_release import _flip_symlinks_on_pi

    _flip_symlinks_on_pi(fake_conn, "2026.04.22-abc")
    cmd = run_remote_mock.call_args[0][1]
    assert "test -L /opt/yoyopod-prod/current" in cmd
    assert "readlink -e /opt/yoyopod-prod/current" in cmd


@patch("yoyopod_cli.remote_release.run_remote_capture")
def test_status_command_uses_shell_only_status_check(capture: MagicMock) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = ""
    fake_result.stderr = ""
    capture.return_value = fake_result

    from yoyopod_cli.remote_release import _status_from_pi

    _status_from_pi(fake_conn)
    cmd = capture.call_args[0][1]
    assert "systemctl is-active --quiet" in cmd
    assert "/proc/$pid/cwd" in cmd
    assert "YOYOPOD_RELEASE_MANIFEST=" not in cmd
    assert capture.call_args.kwargs["workdir"] is None


@patch("yoyopod_cli.remote_release.run_remote")
def test_hydrate_slot_uses_build_subapp_entrypoint(run_remote_mock: MagicMock) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    run_remote_mock.return_value = 0

    from yoyopod_cli.remote_release import _hydrate_slot_on_pi

    _hydrate_slot_on_pi(fake_conn, "2026.04.22-abc")
    cmd = run_remote_mock.call_args[0][1]
    assert "from yoyopod_cli.build import app; app()" in cmd
    assert "-m yoyopod_cli.main" not in cmd
    assert "sys.path.insert(0," in cmd
    assert "/opt/yoyopod-prod/releases/2026.04.22-abc/app" in cmd
    assert "PYTHONPATH=" not in cmd
    assert "libyoyopod_lvgl_shim.so" in cmd
    for relative in APP_NATIVE_RUNTIME_ARTIFACTS:
        assert f"/opt/yoyopod-prod/current/app/{relative.as_posix()}" in cmd
        assert f"/opt/yoyopod-prod/releases/2026.04.22-abc/app/{relative.as_posix()}" in cmd
    assert "yoyopod-power-host" in cmd
    assert "yoyopod-runtime" in cmd
    assert "libyoyopod_liblinphone_shim.so" not in cmd
    assert "pip install -r /opt/yoyopod-prod/releases/2026.04.22-abc/runtime-requirements.txt" in cmd
    assert 'python3 -m venv "$tmp_venv"' in cmd
    assert "cp -aL /opt/yoyopod-prod/current/venv" not in cmd
    assert "touch /opt/yoyopod-prod/releases/2026.04.22-abc" not in cmd
    assert "command -v python3.12" not in cmd
    assert run_remote_mock.call_args.kwargs["workdir"] is None


def test_slot_subapp_command_requires_slot_python() -> None:
    from yoyopod_cli.remote_release import _slot_subapp_command

    cmd = _slot_subapp_command(
        "/opt/yoyopod-prod/releases/2026.04.22-abc", "yoyopod_cli.health", "live"
    )
    assert "sys.path.insert(0," in cmd
    assert "/opt/yoyopod-prod/releases/2026.04.22-abc/app" in cmd
    assert "from yoyopod_cli.health import app; app()" in cmd
    assert "command -v python3.12" not in cmd
    assert "test -x" in cmd


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._conn")
def test_push_refuses_to_overwrite_current_slot_even_with_force(
    conn: MagicMock,
    rsync: MagicMock,
    check: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    state.return_value = "CURRENT"
    check.return_value = 0
    slot = _write_slot(tmp_path, "2026.04.22-abc", self_contained=True)

    result = runner.invoke(release_app, ["push", str(slot), "--force"])
    assert result.exit_code != 0
    assert (
        "active" in (result.stderr or result.stdout).lower()
        or "current" in (result.stderr or result.stdout).lower()
    )
    rsync.assert_not_called()


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release.run_remote")
@patch("yoyopod_cli.remote_release.run_remote_capture")
@patch("yoyopod_cli.remote_release.subprocess.run")
def test_build_pi_downloads_artifact_and_cleans_up_remote_root(
    run_mock: MagicMock,
    capture: MagicMock,
    run_remote_mock: MagicMock,
    conn: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    remote_result = MagicMock()
    remote_result.returncode = 0
    remote_result.stdout = (
        "Ensured native artifacts: LVGL\n"
        "YOYOPOD_BUILD_ROOT=/tmp/yoyopod-release-build.abcd12\n"
        "YOYOPOD_SLOT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc\n"
        "YOYOPOD_ARTIFACT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc.tar.gz\n"
    )
    remote_result.stderr = ""
    capture.return_value = remote_result
    scp_result = MagicMock()
    scp_result.returncode = 0
    run_mock.return_value = scp_result
    run_remote_mock.return_value = 0

    result = runner.invoke(release_app, ["build-pi", "--output", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    remote_cmd = capture.call_args[0][1]
    assert "/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main build ensure-native" in remote_cmd
    assert "scripts/build_release.py" in remote_cmd
    assert "tail -n 1" in remote_cmd
    assert "set -euo pipefail" in remote_cmd
    assert "trap cleanup_build_root EXIT" in remote_cmd
    assert 'rm -rf "$build_root"' in remote_cmd
    assert "trap - EXIT" in remote_cmd
    assert "--with-venv" in remote_cmd
    assert "--python-version 3.12" in remote_cmd
    scp_cmd = run_mock.call_args[0][0]
    assert scp_cmd[0] == "scp"
    assert scp_cmd[1].endswith("/tmp/yoyopod-release-build.abcd12/2026.04.22-abc.tar.gz")
    assert str(tmp_path) in scp_cmd[2]
    assert "rm -rf /tmp/yoyopod-release-build.abcd12" in run_remote_mock.call_args[0][1]
    assert str(tmp_path / "2026.04.22-abc.tar.gz") in result.stdout


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release.run_remote")
@patch("yoyopod_cli.remote_release.run_remote_capture")
@patch("yoyopod_cli.remote_release.subprocess.run")
def test_build_pi_cleans_up_remote_root_when_local_artifact_already_exists(
    run_mock: MagicMock,
    capture: MagicMock,
    run_remote_mock: MagicMock,
    conn: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    remote_result = MagicMock()
    remote_result.returncode = 0
    remote_result.stdout = (
        "YOYOPOD_BUILD_ROOT=/tmp/yoyopod-release-build.abcd12\n"
        "YOYOPOD_SLOT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc\n"
        "YOYOPOD_ARTIFACT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc.tar.gz\n"
    )
    remote_result.stderr = ""
    capture.return_value = remote_result
    run_remote_mock.return_value = 0
    (tmp_path / "2026.04.22-abc.tar.gz").write_text("already here\n", encoding="utf-8")

    result = runner.invoke(release_app, ["build-pi", "--output", str(tmp_path)])

    assert result.exit_code == 2
    run_mock.assert_not_called()
    assert "rm -rf /tmp/yoyopod-release-build.abcd12" in run_remote_mock.call_args[0][1]


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release.run_remote")
@patch("yoyopod_cli.remote_release.run_remote_capture")
@patch("yoyopod_cli.remote_release.subprocess.run")
def test_build_pi_keep_remote_skips_cleanup(
    run_mock: MagicMock,
    capture: MagicMock,
    run_remote_mock: MagicMock,
    conn: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    remote_result = MagicMock()
    remote_result.returncode = 0
    remote_result.stdout = (
        "YOYOPOD_BUILD_ROOT=/tmp/yoyopod-release-build.abcd12\n"
        "YOYOPOD_SLOT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc\n"
        "YOYOPOD_ARTIFACT=/tmp/yoyopod-release-build.abcd12/2026.04.22-abc.tar.gz\n"
    )
    remote_result.stderr = ""
    capture.return_value = remote_result
    scp_result = MagicMock()
    scp_result.returncode = 0
    run_mock.return_value = scp_result
    run_remote_mock.return_value = 0

    result = runner.invoke(release_app, ["build-pi", "--output", str(tmp_path), "--keep-remote"])
    assert result.exit_code == 0, result.stdout
    run_remote_mock.assert_not_called()


def test_remote_build_pi_preserves_home_relative_venv(monkeypatch) -> None:
    from yoyopod_cli.paths import PiPaths
    from yoyopod_cli.remote_release import _remote_build_pi_command

    monkeypatch.setattr(
        "yoyopod_cli.remote_release.load_pi_paths",
        lambda: PiPaths(venv="~/.venv"),
    )

    command = _remote_build_pi_command(channel="dev", version=None, python_version="3.12")

    assert '"$HOME/.venv/bin/python" -m yoyopod_cli.main build ensure-native' in command
    assert "'~/.venv/bin/python'" not in command


@patch("yoyopod_cli.remote_release._run_slot_remote")
def test_check_rollback_available_requires_resolved_target(run_remote_mock: MagicMock) -> None:
    from yoyopod_cli.remote_release import _check_rollback_available

    run_remote_mock.return_value = 0

    assert _check_rollback_available(_fake_conn()) == 0
    command = run_remote_mock.call_args[0][1]
    assert "test -L /opt/yoyopod-prod/previous" in command
    assert "readlink -e /opt/yoyopod-prod/previous" in command
    assert 'test -n "$target"' in command


@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release.run_remote")
def test_install_url_invokes_root_installer_script_directly(
    run_remote_mock: MagicMock,
    conn: MagicMock,
) -> None:
    conn.return_value = _fake_conn()
    run_remote_mock.return_value = 0

    result = runner.invoke(
        release_app,
        [
            "install-url",
            "https://example.com/yoyopod-slot-v0.2.0-linux-arm64.tar.gz",
            "--first-deploy",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.stdout
    command = run_remote_mock.call_args[0][1]
    assert "sudo" in command
    assert "/opt/yoyopod-prod/bin/install-release.sh" in command
    assert "--root=/opt/yoyopod-prod" in command
    assert "--url=https://example.com/yoyopod-slot-v0.2.0-linux-arm64.tar.gz" in command
    assert "--first-deploy" in command
    assert "--force" in command
    assert run_remote_mock.call_args.kwargs["workdir"] is None
    assert run_remote_mock.call_args.kwargs["tty"] is True


@patch("yoyopod_cli.remote_release.run_remote_capture")
def test_slot_exists_state_fails_closed_on_ssh_error(capture: MagicMock) -> None:
    from yoyopod_cli.remote_release import _slot_exists_state

    fake_conn = _fake_conn()
    fake_result = MagicMock()
    fake_result.returncode = 255
    fake_result.stdout = ""
    fake_result.stderr = "ssh failed"
    capture.return_value = fake_result

    try:
        _slot_exists_state(fake_conn, "2026.04.22-abc")
    except RuntimeError as exc:
        assert "slot state probe failed" in str(exc)
    else:
        raise AssertionError("expected slot state probe failure")
