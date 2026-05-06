"""Tests for the yoyopod entry point and bare-invocation behavior."""

from __future__ import annotations

import sys
import subprocess
import types

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


def test_bare_invocation_propagates_launch_app_exit_code(monkeypatch) -> None:
    """`yoyopod` (no subcommand) must exit with the app's return code."""
    fake_module = types.ModuleType("yoyopod.main")

    def fake_main() -> int:
        return 42

    fake_module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yoyopod.main", fake_module)

    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 42, f"expected 42, got {result.exit_code}; output={result.output}"


def test_bare_invocation_with_none_return_exits_zero(monkeypatch) -> None:
    """When launch_app() returns None, exit 0 cleanly."""
    fake_module = types.ModuleType("yoyopod.main")

    def fake_main() -> None:
        return None

    fake_module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yoyopod.main", fake_module)

    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0
