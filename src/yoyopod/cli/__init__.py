"""src/yoyopod/cli/__init__.py — yoyoctl root application."""

from __future__ import annotations

import importlib
import os
import sys
from functools import lru_cache
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

_MISSING_CLI_DEPENDENCY_MESSAGE = (
    "yoyoctl requires the contributor CLI dependencies. Bootstrap the repo with:\n"
    "  uv sync --extra dev"
)


class MissingCliDependencyError(ImportError):
    """Raised when the optional CLI dependency stack is unavailable."""


class _LazyCliApp:
    """Resolve the Typer application only when the CLI is actually used."""

    def _resolve(self) -> Any:
        return build_app()

    def __call__(self, *args: object, **kwargs: object) -> Any:
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


def _load_typer() -> Any:
    """Import Typer lazily so plain module import does not abort test collection."""

    try:
        import typer
    except ImportError as exc:  # pragma: no cover - exercised via import monkeypatching
        raise MissingCliDependencyError(_MISSING_CLI_DEPENDENCY_MESSAGE) from exc
    return typer


@lru_cache(maxsize=1)
def build_app() -> Any:
    """Build the root Typer app on demand."""

    typer = _load_typer()
    root_app = typer.Typer(
        name="yoyoctl",
        help="YoyoPod development and hardware CLI.",
        no_args_is_help=True,
    )

    from yoyopod.cli.build import build_app as build_group
    from yoyopod.cli.pi import pi_app
    from yoyopod.cli.remote import remote_app
    from yoyopod.cli.setup import setup_app

    root_app.add_typer(pi_app)
    root_app.add_typer(remote_app)
    root_app.add_typer(build_group)
    root_app.add_typer(setup_app)
    return root_app


app = _LazyCliApp()


def __getattr__(name: str) -> Any:
    """Resolve CLI subpackages lazily for dotted imports and monkeypatch paths."""

    if name in {"build", "pi", "remote", "setup"}:
        return importlib.import_module(f"yoyopod.cli.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run() -> None:
    """Entry point for the yoyoctl console script."""

    try:
        app()
    except MissingCliDependencyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
