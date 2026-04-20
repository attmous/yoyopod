"""LVGL-backed view for list-style music browsers."""

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
from yoyopod.ui.screens.lvgl_scene_keys import LIST_SCENE_KEY
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.music.playlist import PlaylistScreen


@dataclass(slots=True)
class LvglPlaylistView:
    """Own the LVGL object lifecycle for PlaylistScreen."""

    scene_key: ClassVar[str] = LIST_SCENE_KEY
    screen: "PlaylistScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        """Create the native playlist scene once."""

        if not should_build_retained_view(self):
            return
        self.backend.binding.playlist_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        """Push the current playlist controller state into the native scene."""

        if not ensure_retained_view_built(self):
            return

        title_text = self.screen.get_title_text() if hasattr(self.screen, "get_title_text") else "Playlists"
        footer = self.screen.get_footer_text() if hasattr(self.screen, "get_footer_text") else (
            "Tap next / Load" if self.screen.is_one_button_mode() else "A load | B back | X/Y move"
        )
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        visible_items, visible_badges, selected_visible_index = self.screen.get_visible_window()
        visible_subtitles = (
            self.screen.get_visible_subtitles()
            if hasattr(self.screen, "get_visible_subtitles")
            else ["" for _ in visible_items]
        )
        visible_icon_keys = (
            self.screen.get_visible_icon_keys()
            if hasattr(self.screen, "get_visible_icon_keys")
            else ["playlist" for _ in visible_items]
        )

        empty_title, empty_subtitle = self._empty_state_copy()

        self.backend.binding.playlist_sync(
            title_text=title_text,
            page_text=None,
            footer=footer,
            items=visible_items,
            subtitles=visible_subtitles,
            badges=visible_badges,
            icon_keys=visible_icon_keys,
            selected_visible_index=selected_visible_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=LISTEN.accent,
            empty_title=empty_title,
            empty_subtitle=empty_subtitle,
            empty_icon_key="playlist",
        )

    def destroy(self) -> None:
        """Tear down the native playlist scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.playlist_destroy()
        mark_retained_view_destroyed(self)

    def _empty_state_copy(self) -> tuple[str, str]:
        if hasattr(self.screen, "get_empty_state_copy"):
            return self.screen.get_empty_state_copy()
        if self.screen.loading:
            return ("Loading playlists", "Hold on while your lists come in.")
        if self.screen.error_message:
            return ("Music hiccup", self.screen.error_message)
        return ("No playlists", "Add playlists to see them here.")

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
