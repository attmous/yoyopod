"""Tests for yoyopod_cli.setup — host + Pi setup commands."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.setup import app


def test_host_verify_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-host", "--help"])
    assert result.exit_code == 0


def test_pi_verify_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-pi", "--help"])
    assert result.exit_code == 0


def test_setup_lists_all_four_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "host" in result.output
    assert "pi" in result.output
    assert "verify-host" in result.output
    assert "verify-pi" in result.output
