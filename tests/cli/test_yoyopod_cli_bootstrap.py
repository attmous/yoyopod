"""Smoke test for the new yoyopod_cli package scaffold."""
from __future__ import annotations

import importlib
import importlib.util


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


def test_legacy_yoyopod_cli_package_is_gone() -> None:
    assert importlib.util.find_spec("yoyopod_cli") is not None
    assert importlib.util.find_spec("yoyo" + "pod.cli") is None
