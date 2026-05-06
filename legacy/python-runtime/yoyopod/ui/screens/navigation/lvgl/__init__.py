"""LVGL-backed navigation screen views."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "LvglAskView": ("yoyopod.ui.screens.navigation.lvgl.ask_view", "LvglAskView"),
    "LvglHubView": ("yoyopod.ui.screens.navigation.lvgl.hub_view", "LvglHubView"),
    "LvglListenView": (
        "yoyopod.ui.screens.navigation.lvgl.listen_view",
        "LvglListenView",
    ),
}

__all__ = ["LvglAskView", "LvglHubView", "LvglListenView"]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
