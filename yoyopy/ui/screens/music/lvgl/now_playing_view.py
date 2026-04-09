"""LVGL-backed view for the now-playing screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.music.now_playing import NowPlayingScreen


@dataclass(slots=True)
class LvglNowPlayingView:
    """Own the LVGL object lifecycle for NowPlayingScreen."""

    screen: "NowPlayingScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        """Create the native now-playing scene once."""

        if self._built or self.backend.binding is None:
            return
        self.backend.binding.now_playing_build()
        self._built = True

    def sync(self) -> None:
        """Push the current playback controller state into the native scene."""

        if not self._built or self.backend.binding is None:
            return

        track_title, artist, progress, state_label, is_playing = self.screen._track_snapshot()
        footer = self.screen.get_footer_text(is_playing=is_playing, state_label=state_label)
        context = self.screen.context

        self.backend.binding.now_playing_sync(
            title_text=track_title,
            artist_text=artist,
            state_text=self.screen._display_state_text(state_label),
            footer=footer,
            progress_permille=max(0, min(1000, int(progress * 1000))),
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=LISTEN.accent,
        )

    def destroy(self) -> None:
        """Tear down the native now-playing scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.now_playing_destroy()
        self._built = False

    @staticmethod
    def _battery_percent(context: "AppContext | None") -> int:
        if context is None:
            return 100
        return max(0, min(100, int(getattr(context, "battery_percent", 100))))

    @staticmethod
    def _voip_state(context: "AppContext | None") -> int:
        if context is None or not getattr(context, "voip_configured", False):
            return 0
        return 1 if getattr(context, "voip_ready", False) else 2
