"""Music screens for YoYoPod."""

from __future__ import annotations

from yoyopod.ui._lazy_imports import exported_dir, load_attr

_EXPORTS = {
    "NowPlayingScreen": (
        "yoyopod.ui.screens.music.now_playing",
        "NowPlayingScreen",
    ),
    "PlaylistScreen": ("yoyopod.ui.screens.music.playlist", "PlaylistScreen"),
    "RecentTracksScreen": ("yoyopod.ui.screens.music.recent", "RecentTracksScreen"),
}

__all__ = ['NowPlayingScreen', 'PlaylistScreen', 'RecentTracksScreen']


def __getattr__(name: str) -> object:
    return load_attr(_EXPORTS, __name__, name)


def __dir__() -> list[str]:
    return exported_dir(globals(), _EXPORTS)
