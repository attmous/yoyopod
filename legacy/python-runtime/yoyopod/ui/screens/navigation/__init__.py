"""Navigation screens for YoYoPod."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "HubScreen": ("yoyopod.ui.screens.navigation.hub", "HubScreen"),
    "HomeScreen": ("yoyopod.ui.screens.navigation.home", "HomeScreen"),
    "ListenScreen": ("yoyopod.ui.screens.navigation.listen", "ListenScreen"),
    "MenuScreen": ("yoyopod.ui.screens.navigation.menu", "MenuScreen"),
    "AskScreen": ("yoyopod.ui.screens.navigation.ask", "AskScreen"),
}

__all__ = ['HubScreen', 'HomeScreen', 'ListenScreen', 'MenuScreen', 'AskScreen']


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
