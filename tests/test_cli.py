"""tests/test_cli.py — yoyoctl CLI smoke tests."""

from typer.testing import CliRunner

from yoyopy.cli import app

runner = CliRunner()


def test_root_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pi" in result.output
    assert "remote" in result.output
    assert "build" in result.output


def test_pi_help():
    result = runner.invoke(app, ["pi", "--help"])
    assert result.exit_code == 0


def test_remote_help():
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0


def test_build_help():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
