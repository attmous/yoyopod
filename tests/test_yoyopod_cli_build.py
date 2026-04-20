"""Tests for yoyopod_cli.build — native extension build commands."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.build import app


def test_lvgl_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0
    assert "lvgl" in result.output.lower()


def test_liblinphone_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["liblinphone", "--help"])
    assert result.exit_code == 0
    assert "liblinphone" in result.output.lower()
