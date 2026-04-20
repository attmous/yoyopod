"""Tests for the wired yoyopod pi subapp."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_pi_lists_all_subgroups() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "--help"])
    assert result.exit_code == 0
    for group in ("validate", "voip", "power", "network"):
        assert group in result.output


def test_pi_validate_lvgl_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "validate", "lvgl", "--help"])
    assert result.exit_code == 0


def test_pi_validate_voip_soak_flag_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "validate", "voip", "--help"])
    assert result.exit_code == 0
    assert "--soak" in result.output


def test_pi_power_rtc_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "power", "rtc", "status", "--help"])
    assert result.exit_code == 0


def test_pi_voip_check_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "voip", "check", "--help"])
    assert result.exit_code == 0


def test_pi_network_probe_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "network", "probe", "--help"])
    assert result.exit_code == 0


def test_pi_validate_deploy_reachable() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["pi", "validate", "deploy", "--help"])
    assert result.exit_code == 0
