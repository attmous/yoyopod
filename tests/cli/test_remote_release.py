from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yoyopod_cli.remote_release import app as release_app

runner = CliRunner()


def _write_slot(tmp_path: Path, version: str) -> Path:
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
    (slot / "app").mkdir()
    (slot / "venv").mkdir()
    (slot / "bin").mkdir()
    launch = slot / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    return slot


def _fake_conn() -> MagicMock:
    """Return a mock RemoteConnection with test-safe host/user attributes."""
    conn = MagicMock()
    conn.host = "test-pi.local"
    conn.user = "pi"
    return conn


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_runs_build_rsync_preflight_flip_live(
    live_probe: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0  # previous symlink exists
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code == 0, result.stdout

    rsync.assert_called_once()
    preflight.assert_called_once()
    flip.assert_called_once()
    live_probe.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._cleanup_remote_slot")
def test_push_aborts_and_cleans_up_on_preflight_fail(
    cleanup: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0  # previous symlink exists
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    preflight.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    flip.assert_not_called()
    cleanup.assert_called_once()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_push_rolls_back_on_live_fail(
    rollback: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0  # previous symlink exists
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
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
def test_status_surfaces_ssh_failure(
    conn: MagicMock,
    capture: MagicMock,
) -> None:
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
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._rollback_on_pi")
def test_push_surfaces_rollback_failure_when_rollback_also_fails(
    rollback: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
    rsync: MagicMock,
    conn: MagicMock,
    check_rb: MagicMock,
    state: MagicMock,
    tmp_path: Path,
) -> None:
    conn.return_value = _fake_conn()
    check_rb.return_value = 0  # previous symlink exists
    state.return_value = "NEW"
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 1
    rollback.return_value = 2  # rollback also fails

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    assert "rollback also failed" in (result.stderr or result.stdout).lower()


# --- New tests for Fix 1: SlotPaths override ---


@patch("yoyopod_cli.remote_release.load_slot_paths")
@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
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
    rsync: MagicMock,
    state: MagicMock,
    load_paths: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify a non-default slot.root flows through to rsync."""
    import yoyopod_cli.remote_release as rr
    from yoyopod_cli.paths import SlotPaths

    load_paths.return_value = SlotPaths(root="/srv/yoyopod-alt")
    # Reset module-level cache so the new mock is picked up.
    rr._slot_paths_cache = None

    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    conn.return_value = fake_conn
    check_rb.return_value = 0  # previous symlink exists
    state.return_value = "NEW"
    rsync.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0

    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot)])

    # Reset cache after test so it doesn't pollute other tests.
    rr._slot_paths_cache = None

    assert result.exit_code == 0, result.stdout
    # The rsync echo line in push() calls _slots().releases_dir(), which should
    # use the overridden root.  Since _rsync_to_pi itself is mocked, the echo
    # output is the observable signal that the override propagated.
    assert "/srv/yoyopod-alt" in result.stdout


# --- New tests for Fix 2: --first-deploy flag ---


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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    check.return_value = 1  # no previous symlink
    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "first-deploy" in combined.lower()
    rsync.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._conn")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
def test_push_with_first_deploy_flag_skips_rollback_check(
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
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

    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot), "--first-deploy"])
    assert result.exit_code == 0, result.stdout
    check.assert_not_called()  # check was skipped because of the flag


# --- New tests for Fix 5: immutable release slots ---


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
    check.return_value = 0  # rollback available
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
    assert "already exists" in (result.stderr or result.stdout).lower()
    rsync.assert_not_called()


@patch("yoyopod_cli.remote_release._slot_exists_state")
@patch("yoyopod_cli.remote_release._check_rollback_available")
@patch("yoyopod_cli.remote_release._rsync_to_pi")
@patch("yoyopod_cli.remote_release._run_preflight_on_pi")
@patch("yoyopod_cli.remote_release._flip_symlinks_on_pi")
@patch("yoyopod_cli.remote_release._run_live_probe_on_pi")
@patch("yoyopod_cli.remote_release._conn")
def test_push_with_force_overwrites_non_current_slot(
    conn: MagicMock,
    live: MagicMock,
    flip: MagicMock,
    preflight: MagicMock,
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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot), "--force"])
    assert result.exit_code == 0, result.stdout
    rsync.assert_called_once()


# --- New tests for Fix 3: YOYOPOD_RELEASE_MANIFEST in SSH health invocations ---


@patch("yoyopod_cli.remote_release.run_remote")
def test_live_probe_command_exports_release_manifest_env(
    run_remote_mock: MagicMock,
) -> None:
    """The SSH command for the live probe must export YOYOPOD_RELEASE_MANIFEST."""
    fake_conn = MagicMock()
    fake_conn.host = "pi"
    fake_conn.user = "user"
    run_remote_mock.return_value = 0
    from yoyopod_cli.remote_release import _run_live_probe_on_pi

    _run_live_probe_on_pi(fake_conn, "2026.04.22-abc", timeout_s=1)
    cmd = run_remote_mock.call_args[0][1]
    assert "YOYOPOD_RELEASE_MANIFEST=" in cmd
    assert "/current/manifest.json" in cmd


@patch("yoyopod_cli.remote_release.run_remote_capture")
def test_status_command_exports_release_manifest_env(
    capture: MagicMock,
) -> None:
    """The SSH command for status must export YOYOPOD_RELEASE_MANIFEST."""
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
    assert "YOYOPOD_RELEASE_MANIFEST=" in cmd
    assert "/current/manifest.json" in cmd


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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot), "--force"])
    assert result.exit_code != 0
    assert (
        "active" in (result.stderr or result.stdout).lower()
        or "current" in (result.stderr or result.stdout).lower()
    )
    rsync.assert_not_called()
