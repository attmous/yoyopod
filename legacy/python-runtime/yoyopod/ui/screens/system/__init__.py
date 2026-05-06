"""System and device-status screens for YoYoPod."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "PowerScreen": ("yoyopod.ui.screens.system.power", "PowerScreen"),
}

__all__ = ["PowerScreen"]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
