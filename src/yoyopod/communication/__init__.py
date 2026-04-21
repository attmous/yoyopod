"""Communication domain public package entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .calling.manager import VoIPManager


def __getattr__(name: str) -> Any:
    """Load the public manager lazily to avoid heavy integration imports on package import."""

    if name != "VoIPManager":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .calling.manager import VoIPManager as _VoIPManager

    return _VoIPManager

__all__ = ["VoIPManager"]
