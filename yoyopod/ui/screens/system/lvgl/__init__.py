"""LVGL views for system screens."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "LvglPowerView": ("yoyopod.ui.screens.system.lvgl.power_view", "LvglPowerView"),
}

__all__ = ["LvglPowerView"]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
