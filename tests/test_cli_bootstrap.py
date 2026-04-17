"""Regression tests for graceful CLI bootstrap failures."""

from __future__ import annotations

import builtins
import importlib
import sys
from types import ModuleType

import pytest


def _import_cli_without_typer(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import `yoyopod.cli` while forcing `typer` imports to fail."""

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, object] | None = None,
        locals_dict: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "typer" or name.startswith("typer."):
            raise ModuleNotFoundError("No module named 'typer'")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "typer", raising=False)
    monkeypatch.delitem(sys.modules, "typer.testing", raising=False)
    monkeypatch.delitem(sys.modules, "yoyopod.cli", raising=False)
    return importlib.import_module("yoyopod.cli")


def test_importing_cli_without_typer_does_not_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain module import should stay lazy when the optional CLI stack is missing."""

    module = _import_cli_without_typer(monkeypatch)

    assert module.__name__ == "yoyopod.cli"
    assert module.app is not None


def test_running_cli_without_typer_prints_bootstrap_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The failure should happen at invocation time with a short bootstrap message."""

    module = _import_cli_without_typer(monkeypatch)

    with pytest.raises(module.MissingCliDependencyError):
        module.build_app()

    with pytest.raises(SystemExit) as exc_info:
        module.run()

    assert exc_info.value.code == 1
    assert "uv sync --extra dev" in capsys.readouterr().err
