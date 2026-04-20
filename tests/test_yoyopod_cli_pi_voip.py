"""Tests for yoyopod_cli.pi_voip — on-device VoIP diagnostics."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_voip import app


def test_check_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0


def test_debug_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["debug", "--help"])
    assert result.exit_code == 0


def test_help_lists_only_check_and_debug() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output
    assert "debug" in result.output
    assert "registration-stability" not in result.output
    assert "reconnect-drill" not in result.output
    assert "call-soak" not in result.output


def test_soak_commands_removed() -> None:
    runner = CliRunner()
    for cmd in ("registration-stability", "reconnect-drill", "call-soak"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code != 0, f"{cmd} should have been removed"
