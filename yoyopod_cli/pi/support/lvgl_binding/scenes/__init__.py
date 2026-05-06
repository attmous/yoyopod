"""Scene-level LVGL binding mixins for per-screen UI operations."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Protocol

from .ask import AskSceneMixin
from .calls import CallsSceneMixin
from .hub import HubSceneMixin
from .listen import ListenSceneMixin
from .now_playing import NowPlayingSceneMixin
from .playlist import PlaylistSceneMixin
from .power import PowerSceneMixin
from .status_bar import StatusBarSceneMixin
from .talk import TalkSceneMixin


class _LvglBindingHost(Protocol):
    """Shared contract that scene mixins expect from LvglBinding."""

    ffi: Any
    lib: Any
    HUB_SYNC_STRING_CACHE_LIMIT: int
    _hub_sync_string_cache: OrderedDict[str, object]

    @staticmethod
    def _pack_rgb(color: tuple[int, int, int]) -> int: ...

    def _new_char_array(self, value: str) -> object: ...

    def _get_cached_char_array(
        self,
        cache: OrderedDict[str, object],
        value: str,
        *,
        max_entries: int,
    ) -> object: ...

    def _raise_if_error(self, result: int) -> None: ...


__all__ = [
    "AskSceneMixin",
    "CallsSceneMixin",
    "HubSceneMixin",
    "ListenSceneMixin",
    "NowPlayingSceneMixin",
    "PlaylistSceneMixin",
    "PowerSceneMixin",
    "StatusBarSceneMixin",
    "TalkSceneMixin",
]
