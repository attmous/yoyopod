"""Tests for yoyopod_cli.pi_validate."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_validate import app


def test_deploy_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0


def test_smoke_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["smoke", "--help"])
    assert result.exit_code == 0


def test_music_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["music", "--help"])
    assert result.exit_code == 0


def test_voip_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--help"])
    assert result.exit_code == 0


def test_stability_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["stability", "--help"])
    assert result.exit_code == 0


def test_navigation_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["navigation", "--help"])
    assert result.exit_code == 0


def test_all_six_base_subcommands_present() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("deploy", "smoke", "music", "voip", "stability", "navigation"):
        assert name in result.output


def test_voip_soak_flag_registered() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--help"])
    assert result.exit_code == 0
    assert "--soak" in result.output
    assert "registration" in result.output
    assert "reconnect" in result.output
    assert "call" in result.output


def test_voip_soak_call_requires_target() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--soak", "call"])
    # should fail with BadParameter
    assert result.exit_code != 0
    assert "soak-target" in result.output.lower() or "soak_target" in result.output.lower()


def test_voip_soak_unknown_value_rejected() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--soak", "invalid"])
    assert result.exit_code != 0


def test_lvgl_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0


def test_all_seven_subcommands_present() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("deploy", "smoke", "music", "voip", "stability", "navigation", "lvgl"):
        assert name in result.output
