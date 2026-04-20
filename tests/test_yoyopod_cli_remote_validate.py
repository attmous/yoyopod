"""Tests for yoyopod_cli.remote_validate."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_validate import app, _build_validate, _build_preflight_steps


def test_build_preflight_steps_include_git_and_quality() -> None:
    steps = _build_preflight_steps()
    assert any("git diff" in " ".join(argv) for _, argv in steps)
    assert any("quality.py" in " ".join(argv) for _, argv in steps)


def test_build_validate_minimal() -> None:
    shell = _build_validate(with_music=False, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    assert "yoyopod pi validate deploy" in shell
    assert "yoyopod pi validate smoke" in shell
    assert "voip" not in shell
    assert "lvgl" not in shell
    assert "navigation" not in shell


def test_build_validate_all_flags() -> None:
    shell = _build_validate(with_music=True, with_voip=True, with_lvgl_soak=True, with_navigation=True)
    assert "yoyopod pi validate music" in shell
    assert "yoyopod pi validate voip" in shell
    assert "yoyopod pi validate lvgl" in shell
    assert "yoyopod pi validate navigation" in shell


def test_build_validate_only_music() -> None:
    shell = _build_validate(with_music=True, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    assert "yoyopod pi validate music" in shell
    assert "voip" not in shell


def test_preflight_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["preflight", "--help"])
    assert result.exit_code == 0


def test_validate_help_shows_flags() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--with-music" in result.output
    assert "--with-voip" in result.output
    assert "--with-lvgl-soak" in result.output
    assert "--with-navigation" in result.output
