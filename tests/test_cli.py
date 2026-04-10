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


def test_build_lvgl_help():
    result = runner.invoke(app, ["build", "lvgl", "--help"])
    assert result.exit_code == 0
    assert "--source-dir" in result.output
    assert "--build-dir" in result.output
    assert "--skip-fetch" in result.output


def test_build_liblinphone_help():
    result = runner.invoke(app, ["build", "liblinphone", "--help"])
    assert result.exit_code == 0
    assert "--build-dir" in result.output


def test_pi_voip_check_help():
    result = runner.invoke(app, ["pi", "voip", "check", "--help"])
    assert result.exit_code == 0


def test_pi_voip_debug_help():
    result = runner.invoke(app, ["pi", "voip", "debug", "--help"])
    assert result.exit_code == 0
