"""Helpers for package-level lazy re-exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def exported_dir(
    module_globals: dict[str, Any],
    exports: dict[str, tuple[str, str]],
) -> list[str]:
    """Return a stable directory view for lazy-export packages."""

    return sorted(set(module_globals) | set(exports))


def load_attr(
    exports: dict[str, tuple[str, str]],
    package_name: str,
    name: str,
) -> Any:
    """Import and return one lazily re-exported attribute."""

    try:
        module_name, attr_name = exports[name]
    except KeyError as exc:
        raise AttributeError(f"module {package_name!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    return getattr(module, attr_name)
