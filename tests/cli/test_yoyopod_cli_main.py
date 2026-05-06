"""Tests for the yoyopod entry point and bare-invocation behavior."""

from __future__ import annotations

import sys
import subprocess

from typer.testing import CliRunner

from yoyopod_cli._version import __version__
from yoyopod_cli.main import app


def test_help_lists_yoyopod() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "yoyopod" in result.output.lower()


def test_version_flag_present() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_module_invocation_dispatches_cli_subcommands() -> None:
    """Pi-side `python -m yoyopod_cli.main ...` must not silently no-op."""
    result = subprocess.run(
        [sys.executable, "-m", "yoyopod_cli.main", "build", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert "ensure-native" in result.stdout


def test_no_subcommand_prints_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "YoYoPod operations CLI" in result.output
    assert "build" in result.output
    assert "remote" in result.output
