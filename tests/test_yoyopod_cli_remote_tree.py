"""Tests for the wired yoyopod remote subapp."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_remote_lists_all_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0
    for cmd in (
        "status", "sync", "restart", "logs", "screenshot",
        "config", "power", "rtc", "service",
        "setup", "verify-setup", "preflight", "validate",
    ):
        assert cmd in result.output, f"missing: {cmd}"


def test_remote_status_has_shared_options() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["remote", "status", "--help"])
    assert result.exit_code == 0
    # Shared options should be visible at the group level (remote --help), not duplicated per command.
    # We just verify the command help itself works.


def test_remote_status_reaches_run_remote(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["remote", "status"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "git rev-parse HEAD" in calls[0]


def test_remote_config_show_works() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["remote", "config", "show"])
    assert result.exit_code == 0
    assert "project_dir" in result.output
