from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi.network import app


def test_probe_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["probe", "--help"])
    assert result.exit_code == 0


def test_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_gps_command_cut() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gps", "--help"])
    assert result.exit_code != 0


def test_help_lists_only_probe_and_status() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "probe" in result.output
    assert "status" in result.output
    assert "gps" not in result.output
