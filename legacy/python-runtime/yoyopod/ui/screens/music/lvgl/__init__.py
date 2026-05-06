"""LVGL-backed music screen views."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "LvglNowPlayingView": (
        "yoyopod.ui.screens.music.lvgl.now_playing_view",
        "LvglNowPlayingView",
    ),
    "LvglPlaylistView": (
        "yoyopod.ui.screens.music.lvgl.playlist_view",
        "LvglPlaylistView",
    ),
}

__all__ = ["LvglNowPlayingView", "LvglPlaylistView"]


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
