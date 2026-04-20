"""Tests for the yoyopod entry point and bare-invocation behavior."""
from __future__ import annotations

import sys
import types

from typer.testing import CliRunner

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
    assert "0.1.0" in result.output


def test_bare_invocation_propagates_launch_app_exit_code(monkeypatch) -> None:
    """`yoyopod` (no subcommand) must exit with the app's return code."""
    fake_module = types.ModuleType("yoyopod.main")

    def fake_main() -> int:
        return 42

    fake_module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yoyopod.main", fake_module)

    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 42, (
        f"expected 42, got {result.exit_code}; output={result.output}"
    )


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
