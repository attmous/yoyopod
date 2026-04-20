"""Tests for yoyopod_cli.remote_ops — runtime ops over SSH."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_ops import app, _build_status, _build_restart, _build_logs_tail, _build_sync
from yoyopod_cli.paths import PiPaths


def test_build_status_includes_repo_sha_and_log_tail() -> None:
    pi = PiPaths()
    shell = _build_status(pi)
    assert "git rev-parse HEAD" in shell
    assert pi.log_file in shell
    assert pi.pid_file in shell


def test_build_restart_uses_configured_processes() -> None:
    pi = PiPaths(kill_processes=("python", "linphonec"))
    shell = _build_restart(pi)
    assert "python" in shell
    assert "linphonec" in shell
    assert "pkill" in shell


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
    assert "grep 'ERROR'" in shell


def test_build_logs_tail_filter_with_apostrophe_uses_posix_escape() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=50, follow=False, errors=False, filter_pattern="O'Brien")
    # Must produce grep 'O'\''Brien' — not 'O'''Brien'
    assert "grep 'O'\\''Brien'" in shell
    # Regression guard: no triple-single-quote malformed escape
    assert "'''" not in shell


def test_build_sync_includes_branch_and_restart() -> None:
    pi = PiPaths()
    shell = _build_sync(pi, branch="main")
    assert "git fetch origin" in shell
    assert "git checkout 'main'" in shell or "git checkout main" in shell
    # sync ends with a restart pipeline
    assert "pkill" in shell


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
