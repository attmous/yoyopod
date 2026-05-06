"""Tests for yoyopod_cli.remote_ops — runtime ops over SSH."""

from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_ops import (
    app,
    _build_native_shim_refresh,
    _build_status,
    _build_restart,
    _build_logs_tail,
    _build_sync,
    _build_startup_verification,
    _build_screenshot_alive_check,
    _build_screenshot_clear,
    _build_screenshot_ready_check,
    _build_screenshot_signal,
    _build_screenshot_wait,
)
from yoyopod_cli.paths import PiPaths


STALE_APP_PATTERN = r"pkill -f '[y]oyopod-runtime' || true"


def test_build_status_includes_repo_sha_and_log_tail() -> None:
    pi = PiPaths()
    shell = _build_status(pi)
    assert "git rev-parse HEAD" in shell
    assert pi.log_file in shell
    assert pi.pid_file in shell
    assert "linphonec" not in shell


def test_build_restart_uses_safe_stale_app_cleanup() -> None:
    pi = PiPaths(
        venv="venv",
        start_cmd="device/runtime/build/yoyopod-runtime --config-dir config",
        kill_processes=("yoyopod-runtime", "stale-helper"),
    )
    shell = _build_restart(pi)
    assert STALE_APP_PATTERN in shell
    assert "stale-helper" not in shell
    assert STALE_APP_PATTERN in shell
    assert "systemctl cat" in shell
    assert "sudo systemctl start" in shell
    assert "nohup" not in shell
    assert "source venv" not in shell
    assert "python " + "yoyopod.py" not in shell
    assert "venv/bin/python -m yoyopod_cli.main build ensure-native" in shell
    assert pi.pid_file in shell
    assert pi.log_file in shell
    assert pi.startup_marker in shell


def test_build_restart_does_not_kill_remote_shell_with_broad_python_pattern() -> None:
    shell = _build_restart(PiPaths(kill_processes=("python",)))

    assert "pkill -f python" not in shell
    assert "pkill -f 'python'" not in shell
    assert STALE_APP_PATTERN in shell


def test_build_restart_requires_dev_lane_service() -> None:
    shell = _build_restart(PiPaths())

    dev_probe = shell.index("systemctl cat yoyopod-dev.service")
    dev_start = shell.index("sudo systemctl start yoyopod-dev.service")

    assert dev_probe < dev_start
    assert "dev lane service is not installed" in shell
    assert "sudo systemctl reset-failed yoyopod-dev.service" in shell
    assert "yoyopod@" not in shell


def test_build_restart_only_starts_managed_service_for_selected_checkout() -> None:
    shell = _build_restart(PiPaths())

    assert 'selected_checkout="$(pwd -P)"' in shell
    assert "/etc/default/yoyopod-dev" in shell
    assert "YOYOPOD_DEV_CHECKOUT" in shell
    assert "[ -f /etc/default/yoyopod ]" not in shell
    assert "YOYOPOD_PROJECT_DIR" not in shell
    assert '[ "$selected_checkout" != "$dev_service_checkout" ]' in shell
    assert "selected checkout" in shell


def test_build_restart_has_no_legacy_checkout_fallbacks() -> None:
    shell = _build_restart(PiPaths())

    assert "$HOME/yoyopod-core" not in shell
    assert "$HOME/YoyoPod_Core" not in shell
    assert "$HOME/yoyo-py" not in shell
    assert "legacy_service_checkout" not in shell


def test_build_native_shim_refresh_runs_native_artifact_refresh() -> None:
    pi = PiPaths(venv="venv")
    shell = _build_native_shim_refresh(pi)
    assert "venv/bin/python -m yoyopod_cli.main build ensure-native" in shell
    assert "uv run" not in shell


def test_build_startup_verification_waits_for_pid_and_marker() -> None:
    pi = PiPaths()
    shell = _build_startup_verification(pi, attempts=5)
    assert "for _ in $(seq 1 5)" in shell
    assert "pid=\"$(tr -d '\\n' < " in shell
    assert 'kill -0 "$pid"' in shell
    assert f"grep -F '{pi.startup_marker}'" in shell or f'grep -F "{pi.startup_marker}"' in shell


def test_build_logs_tail_defaults() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=50, follow=False, errors=False, filter_pattern="")
    assert "tail -n 50" in shell
    assert pi.log_file in shell
    assert "-f" not in shell


def test_build_logs_tail_follow_errors_filter() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=20, follow=True, errors=True, filter_pattern="ERROR")
    assert "tail -n 20 -f" in shell
    assert pi.error_log_file in shell
    assert "grep -- 'ERROR'" in shell


def test_build_logs_tail_filter_starting_with_dash_does_not_trip_grep_flags() -> None:
    """A filter like `-ERR` must be passed AFTER `--` so grep treats it as data."""
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=50, follow=False, errors=False, filter_pattern="-ERR")
    # -- must separate options from pattern; otherwise grep thinks `-ERR` is a flag
    assert "grep -- '-ERR'" in shell


def test_build_logs_tail_filter_with_apostrophe_uses_posix_escape() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=50, follow=False, errors=False, filter_pattern="O'Brien")
    # Must produce grep -- 'O'\''Brien' — not 'O'''Brien'
    assert "grep -- 'O'\\''Brien'" in shell
    # Regression guard: no triple-single-quote malformed escape
    assert "'''" not in shell


def test_build_sync_includes_branch_and_restart() -> None:
    pi = PiPaths()
    shell = _build_sync(pi, branch="main")
    assert "git fetch --prune origin" in shell
    assert shell.count("git clean -fd") == 2
    assert (
        "git checkout --force -B 'main' 'origin/main'" in shell
        or "git checkout --force -B main origin/main" in shell
    )
    # sync ends with a restart pipeline
    assert STALE_APP_PATTERN in shell
    assert "grep -F" in shell


def test_build_sync_can_clean_native_build_dirs_before_restart() -> None:
    pi = PiPaths(venv="/opt/yoyopod-dev/venv")
    shell = _build_sync(pi, branch="feature-x", clean_native=True)

    clean_pos = shell.index("/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main build clean-native")
    ensure_pos = shell.index("/opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main build ensure-native")

    assert clean_pos < ensure_pos


def test_status_cli_invokes_run_remote(monkeypatch) -> None:
    calls: list[tuple[object, str]] = []

    def fake_run_remote(conn, cmd, tty=False):
        calls.append((conn, cmd))
        return 0

    monkeypatch.setattr("yoyopod_cli.remote_ops.run_remote", fake_run_remote)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    conn, cmd = calls[0]
    assert conn.host == "rpi-zero"
    assert "git rev-parse HEAD" in cmd


# ---- screenshot builder tests -----------------------------------------------


def test_build_screenshot_alive_check_uses_pid_file() -> None:
    pi = PiPaths()
    shell = _build_screenshot_alive_check(pi)
    assert pi.pid_file in shell
    assert "kill -0" in shell
    assert "ALIVE" in shell
    assert "DEAD" in shell


def test_build_screenshot_ready_check_waits_for_current_pid_handlers() -> None:
    pi = PiPaths()
    shell = _build_screenshot_ready_check(pi, attempts=7)

    assert "for _ in $(seq 1 7)" in shell
    assert pi.pid_file in shell
    assert "/proc/${pid_value}/status" in shell
    assert "SigCgt" in shell
    assert "0x200" in shell
    assert "0x800" in shell
    assert pi.log_file not in shell
    assert pi.startup_marker not in shell
    assert "Screenshot handlers installed" not in shell
    assert "READY" in shell
    assert "NOT_READY" in shell


def test_build_screenshot_clear_removes_screenshot_path() -> None:
    pi = PiPaths()
    shell = _build_screenshot_clear(pi)
    assert "rm -f" in shell
    assert pi.screenshot_path in shell


def test_build_screenshot_signal_readback_uses_sigusr1() -> None:
    pi = PiPaths()
    shell = _build_screenshot_signal(pi, readback=True)
    assert "kill -USR1" in shell
    assert pi.pid_file in shell
    assert "USR2" not in shell


def test_build_screenshot_signal_shadow_uses_sigusr2() -> None:
    pi = PiPaths()
    shell = _build_screenshot_signal(pi, readback=False)
    assert "kill -USR2" in shell
    assert pi.pid_file in shell
    assert "USR1" not in shell


def test_build_screenshot_wait_polls_for_file() -> None:
    pi = PiPaths()
    shell = _build_screenshot_wait(pi)
    assert pi.screenshot_path in shell
    assert "for _ in $(seq 1" in shell
    assert "READY" in shell
    assert "MISSING" in shell


def test_screenshot_aborts_when_app_is_not_ready(monkeypatch) -> None:
    """Full CLI: app not ready -> exit code 1, no SCP attempt."""
    import types

    capture_calls: list[str] = []
    capture_workdirs: list[str | None] = []
    scp_calls: list[list[str]] = []

    def fake_capture(conn, cmd, *, workdir=None):
        capture_calls.append(cmd)
        capture_workdirs.append(workdir)
        return types.SimpleNamespace(returncode=1, stdout="NOT_READY\n", stderr="")

    def fake_scp(argv, check=False):
        scp_calls.append(list(argv))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr("yoyopod_cli.remote_ops.run_remote_capture", fake_capture)
    monkeypatch.setattr("yoyopod_cli.remote_ops.subprocess.run", fake_scp)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["screenshot"])
    assert result.exit_code == 1, result.output
    # Only the readiness check ran; no scp
    assert len(capture_calls) == 1
    assert capture_workdirs == [None]
    assert len(scp_calls) == 0


def test_screenshot_sends_sigusr2_by_default_and_scps_back(monkeypatch, tmp_path) -> None:
    """Happy path: app ready, clear ok, signal ok, file READY, scp succeeds."""
    import types

    capture_calls: list[str] = []
    capture_workdirs: list[str | None] = []
    scp_calls: list[list[str]] = []

    def fake_capture(conn, cmd, *, workdir=None):
        capture_calls.append(cmd)
        capture_workdirs.append(workdir)
        if "SigCgt" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="READY\n", stderr="")
        if cmd.startswith("rm -f"):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "kill -USR" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "for _ in $(seq" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="READY\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_scp(argv, check=False):
        scp_calls.append(list(argv))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr("yoyopod_cli.remote_ops.run_remote_capture", fake_capture)
    monkeypatch.setattr("yoyopod_cli.remote_ops.subprocess.run", fake_scp)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    out_path = tmp_path / "out.png"
    runner = CliRunner()
    result = runner.invoke(app, ["screenshot", "--out", str(out_path)])
    assert result.exit_code == 0, result.output
    # 4 capture steps: readiness, clear, signal, wait
    assert len(capture_calls) == 4
    assert capture_workdirs == [None, None, None, None]
    # Default signal is USR2 (shadow buffer)
    assert any("kill -USR2" in c for c in capture_calls)
    assert not any("kill -USR1" in c for c in capture_calls)
    # SCP called once with the tmp_path out
    assert len(scp_calls) == 1
    assert scp_calls[0][0] == "scp"
    assert str(out_path) in scp_calls[0]


def test_screenshot_readback_uses_sigusr1(monkeypatch, tmp_path) -> None:
    import types

    capture_calls: list[str] = []
    capture_workdirs: list[str | None] = []

    def fake_capture(conn, cmd, *, workdir=None):
        capture_calls.append(cmd)
        capture_workdirs.append(workdir)
        if "SigCgt" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="READY\n", stderr="")
        if cmd.startswith("rm -f"):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "kill -USR" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "for _ in $(seq" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="READY\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("yoyopod_cli.remote_ops.run_remote_capture", fake_capture)
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.subprocess.run",
        lambda argv, check=False: types.SimpleNamespace(returncode=0),
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["screenshot", "--readback", "--out", str(tmp_path / "out.png")])
    assert result.exit_code == 0, result.output
    assert capture_workdirs == [None, None, None, None]
    assert any("kill -USR1" in c for c in capture_calls)
    assert not any("kill -USR2" in c for c in capture_calls)
