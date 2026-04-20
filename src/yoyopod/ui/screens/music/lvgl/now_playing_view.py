"""LVGL-backed view for the now-playing screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from yoyopod.ui.lvgl_binding import LvglDisplayBackend
from yoyopod.ui.screens.lvgl_lifecycle import (
    ensure_retained_view_built,
    mark_retained_view_built,
    mark_retained_view_destroyed,
    should_build_retained_view,
)
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.music.now_playing import NowPlayingScreen


@dataclass(slots=True)
class LvglNowPlayingView:
    """Own the LVGL object lifecycle for NowPlayingScreen."""

    scene_key: ClassVar[str] = "now_playing"
    screen: "NowPlayingScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        """Create the native now-playing scene once."""

        if not should_build_retained_view(self):
            return
        self.backend.binding.now_playing_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        """Push the current playback controller state into the native scene."""

        if not ensure_retained_view_built(self):
            return

        state = self.screen.current_state()
        footer = self.screen.get_footer_text(
            is_playing=state.is_playing,
            state_label=state.state_label,
        )
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.now_playing_sync(
            title_text=state.title,
            artist_text=state.artist,
            state_text=self.screen._display_state_text(state.state_label),
            footer=footer,
            progress_permille=max(0, min(1000, int(state.progress * 1000))),
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=LISTEN.accent,
        )

    def destroy(self) -> None:
        """Tear down the native now-playing scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.now_playing_destroy()
        mark_retained_view_destroyed(self)

    @staticmethod
    def _battery_percent(context: "AppContext | None") -> int:
        if context is None:
            return 100
        return max(0, min(100, int(context.power.battery_percent)))

    @staticmethod
    def _voip_state(context: "AppContext | None") -> int:
        if context is None or not context.voip.configured:
            return 0
        return 1 if context.voip.ready else 2
