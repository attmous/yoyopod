"""Tests for the dev profiling CLI wrappers."""

from __future__ import annotations

from typer.main import get_command
from typer.testing import CliRunner

from yoyopod_cli.dev_profile import build_profile_script_command
from yoyopod_cli.main import app

runner = CliRunner()


def _invoke_help(*args: str):
    """Render deterministic help output regardless of terminal environment."""

    return runner.invoke(app, list(args), color=False, terminal_width=120)


def _command_option_names(*path: str) -> set[str]:
    """Return the Click/Typer option names for one nested CLI command."""

    command = get_command(app)
    for segment in path:
        command = command.get_command(None, segment)
        assert command is not None, f"Missing CLI command path: {' '.join(path)}"
    return {
        option
        for param in command.params
        for option in getattr(param, "opts", [])
    }


def test_build_profile_script_command_points_at_repo_script() -> None:
    command = build_profile_script_command("list-targets")

    assert command[1].endswith("scripts\\profile.py") or command[1].endswith("scripts/profile.py")
    assert command[2:] == ("list-targets",)


def test_dev_help_lists_profile_group() -> None:
    result = _invoke_help("dev", "--help")

    assert result.exit_code == 0
    assert "profile" in result.output


def test_dev_profile_help_lists_commands() -> None:
    result = _invoke_help("dev", "profile", "--help")

    assert result.exit_code == 0
    output = result.output
    assert "targets" in output
    assert "tools" in output
    assert "cprofile" in output
    assert "pyinstrument" in output
    assert "pyperf" in output


def test_dev_profile_cprofile_exposes_expected_options() -> None:
    option_names = _command_option_names("dev", "profile", "cprofile")

    assert "--target" in option_names
    assert "--iterations" in option_names
    assert "--output" in option_names


def test_dev_profile_pyperf_exposes_expected_options() -> None:
    option_names = _command_option_names("dev", "profile", "pyperf")

    assert "--track-memory" in option_names
    assert "--fast" in option_names
    assert "--rigorous" in option_names
