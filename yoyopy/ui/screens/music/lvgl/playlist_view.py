"""LVGL-backed view for list-style music browsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.music.playlist import PlaylistScreen


@dataclass(slots=True)
class LvglPlaylistView:
    """Own the LVGL object lifecycle for PlaylistScreen."""

    screen: "PlaylistScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        """Create the native playlist scene once."""

        if self._built or self.backend.binding is None:
            return
        self.backend.binding.playlist_build()
        self._built = True

    def sync(self) -> None:
        """Push the current playlist controller state into the native scene."""

        if not self._built or self.backend.binding is None:
            return

        title_text = self.screen.get_title_text() if hasattr(self.screen, "get_title_text") else "Playlists"
        footer = self.screen.get_footer_text() if hasattr(self.screen, "get_footer_text") else (
            "Tap next / Load" if self.screen.is_one_button_mode() else "A load | B back | X/Y move"
        )
        context = self.screen.context

        visible_items, visible_badges, selected_visible_index = self.screen.get_visible_window()

        empty_title, empty_subtitle = self._empty_state_copy()

        self.backend.binding.playlist_sync(
            title_text=title_text,
            page_text=None,
            footer=footer,
            items=visible_items,
            badges=visible_badges,
            selected_visible_index=selected_visible_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
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
        self._built = False

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
        return max(0, min(100, int(getattr(context, "battery_percent", 100))))

    @staticmethod
    def _voip_state(context: "AppContext | None") -> int:
        if context is None or not getattr(context, "voip_configured", False):
            return 0
        return 1 if getattr(context, "voip_ready", False) else 2
