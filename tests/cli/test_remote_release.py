from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    (slot / "runtime-requirements.txt").write_text("typer>=0.12.0\n", encoding="utf-8")
    (slot / "app").mkdir()
    (slot / "venv").mkdir()
    (slot / "bin").mkdir()
    launch = slot / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launch.chmod(0o755)
    return slot


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
def test_push_runs_build_rsync_hydrate_preflight_flip_live(
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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    hydrate.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live_probe.return_value = 0

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code == 0, result.stdout

    rsync.assert_called_once()
    hydrate.assert_called_once()
    preflight.assert_called_once()
    flip.assert_called_once()
    live_probe.assert_called_once()


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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    hydrate.return_value = 1

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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    hydrate.return_value = 0
    preflight.return_value = 1

    result = runner.invoke(release_app, ["push", str(slot)])
    assert result.exit_code != 0
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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    hydrate.return_value = 0
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
    slot = _write_slot(tmp_path, "2026.04.22-abc")
    rsync.return_value = 0
    hydrate.return_value = 0
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
    hydrate.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0

    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot)])

    rr._slot_paths_cache = None

    assert result.exit_code == 0, result.stdout
    assert "/srv/yoyopod-alt" in result.stdout


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
    hydrate.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0

    slot = _write_slot(tmp_path, "2026.04.22-abc")
    result = runner.invoke(release_app, ["push", str(slot), "--first-deploy"])
    assert result.exit_code == 0, result.stdout
    check.assert_not_called()


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
    slot = _write_slot(tmp_path, "2026.04.22-abc")

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
    hydrate.return_value = 0
    preflight.return_value = 0
    flip.return_value = 0
    live.return_value = 0
    slot = _write_slot(tmp_path, "2026.04.22-abc")

    result = runner.invoke(release_app, ["push", str(slot), "--force"])
    assert result.exit_code == 0, result.stdout
    rsync.assert_called_once()


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
    assert "YOYOPOD_RELEASE_MANIFEST=" not in cmd
    assert "from yoyopod_cli.health import app; app()" not in cmd


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
    assert "/opt/yoyopod/releases/2026.04.22-abc/app" in cmd
    assert "PYTHONPATH=" not in cmd
    assert "libyoyopod_lvgl_shim.so" in cmd
    assert "libyoyopod_liblinphone_shim.so" in cmd
    assert run_remote_mock.call_args.kwargs["workdir"] is None


def test_slot_subapp_command_prepends_slot_app_to_sys_path() -> None:
    from yoyopod_cli.remote_release import _slot_subapp_command

    cmd = _slot_subapp_command("/opt/yoyopod/releases/2026.04.22-abc", "yoyopod_cli.health", "live")
    assert "sys.path.insert(0," in cmd
    assert "/opt/yoyopod/releases/2026.04.22-abc/app" in cmd
    assert "from yoyopod_cli.health import app; app()" in cmd
    assert "PYTHONPATH=" not in cmd


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
