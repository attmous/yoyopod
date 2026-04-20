"""Tests for yoyopod_cli.pi_validate."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_validate import app


def _collect_option_names(click_cmd: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(click_cmd, "params", []):
        names.update(getattr(param, "opts", []))
    return names


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
    import typer.main

    click_cmd = typer.main.get_command(app)
    voip_cmd = click_cmd.commands["voip"]  # type: ignore[attr-defined]
    names = _collect_option_names(voip_cmd)
    assert "--soak" in names


def test_voip_soak_call_requires_target() -> None:
    import re
    import typer

    runner = CliRunner()
    result = runner.invoke(app, ["voip", "--soak", "call"])
    assert result.exit_code != 0

    # BadParameter gets wrapped in SystemExit by Click's error handler.
    # The original exception is preserved on result.exc_info (a tuple) when
    # catch_exceptions=True (default).
    if result.exc_info is not None:
        _type, exc, _tb = result.exc_info
        if isinstance(exc, typer.BadParameter):
            assert "soak-target" in str(exc).lower()
            return

    # Fallback: strip ANSI codes and check in the combined output.
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    stripped = ansi_re.sub("", result.output)
    assert "soak-target" in stripped.lower(), (
        f"BadParameter message missing from output. Got exit={result.exit_code}, "
        f"exc_info={result.exc_info}, output_stripped={stripped!r}"
    )


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
