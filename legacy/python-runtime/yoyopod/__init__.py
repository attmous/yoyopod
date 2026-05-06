"""YoYoPod package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod_cli._version import __version__

__author__ = "YoYoPod Team"

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp as YoyoPodApp

__all__ = ["YoyoPodApp", "__author__", "__version__"]


def __getattr__(name: str) -> Any:
    if name == "YoyoPodApp":
        from yoyopod.core.application import YoyoPodApp

        return YoyoPodApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
