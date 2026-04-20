"""Smoke test for the new yoyopod_cli package scaffold."""
from __future__ import annotations

import importlib


def test_package_imports() -> None:
    module = importlib.import_module("yoyopod_cli")
    assert module.__name__ == "yoyopod_cli"


def test_version_exposed() -> None:
    module = importlib.import_module("yoyopod_cli")
    assert isinstance(module.__version__, str)
    assert module.__version__


def test_common_imports() -> None:
    module = importlib.import_module("yoyopod_cli.common")
    assert callable(module.configure_logging)
    assert callable(module.resolve_config_dir)
    assert module.REPO_ROOT.exists()
