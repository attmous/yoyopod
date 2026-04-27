"""Tests for yoyopod_cli.pi.power."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi.power import app


def test_battery_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["battery", "--help"])
    assert result.exit_code == 0


def test_rtc_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rtc", "status", "--help"])
    assert result.exit_code == 0


def test_rtc_all_subcommands() -> None:
    runner = CliRunner()
    for sub in ("status", "sync-to", "sync-from", "set-alarm", "disable-alarm"):
        result = runner.invoke(app, ["rtc", sub, "--help"])
        assert result.exit_code == 0, f"rtc {sub} help failed"


def test_power_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "battery" in result.output
    assert "rtc" in result.output
