"""Tangara-inspired local library menu for Listen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from yoyopod.audio.music import LocalLibraryItem, LocalMusicService
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.navigation.lvgl import LvglListenView
from yoyopod.ui.screens.theme import (
    draw_list_item,
    render_footer,
    render_header,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens import ScreenView


class ListenScreen(Screen):
    """Local music landing screen for Playlists, Recent, and Shuffle."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        music_service: Optional[LocalMusicService] = None,
    ) -> None:
        super().__init__(display, context, "Listen")
        self.music_service = music_service
        self.items: list[LocalLibraryItem] = []
        self.selected_index = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh the local library menu when entering Listen."""
        super().enter()
        self._load_items()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL Listen view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglListenView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _load_items(self) -> None:
        """Load the fixed local-first Listen menu items."""
        if self.music_service is not None:
            self.items = self.music_service.menu_items()
        else:
            self.items = [
                LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
                LocalLibraryItem("recent", "Recent", "Played lately"),
                LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
            ]
        if self.items:
            self.selected_index = min(self.selected_index, len(self.items) - 1)
        else:
            self.selected_index = 0

    def render(self) -> None:
        """Render the local library menu."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Your Music",
            subtitle="Local library",
            show_time=False,
            show_mode_chip=False,
        )

        list_top = content_top + 8
        item_height = 76
        for index, item in enumerate(self.items):
            y1 = list_top + (index * item_height)
            y2 = y1 + 68
            if y2 > self.display.HEIGHT - 38:
                break

            draw_list_item(
                self.display,
                x1=18,
                y1=y1,
                x2=self.display.WIDTH - 18,
                y2=y2,
                title=item.title,
                subtitle=item.subtitle,
                mode="listen",
                selected=index == self.selected_index,
                icon=self._item_icon_key(item.key),
            )

        help_text = (
            "Tap = Next  ·  2× Tap = Open  ·  Hold = Back"
            if self.is_one_button_mode()
            else "A open | B back | X/Y move"
        )
        render_footer(self.display, help_text, mode="listen")
        self.display.update()

    @staticmethod
    def _item_icon_key(key: str) -> str:
        """Return the icon key used for each Listen landing row."""

        if key == "playlists":
            return "playlist"
        if key == "recent":
            return "music_note"
        return "listen"

    def on_select(self, data=None) -> None:
        """Open the selected local library action."""
        if not self.items:
            return

        selected = self.items[self.selected_index]
        if selected.key == "playlists":
            self.request_route("open_playlists")
            return
        if selected.key == "recent":
            self.request_route("open_recent")
            return
        if selected.key == "shuffle" and self.music_service is not None:
            if self.music_service.shuffle_all():
                self.request_route("shuffle_started")
            return

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance through the local music menu with wraparound."""
        if not self.items:
            return
        self.selected_index = (self.selected_index + 1) % len(self.items)

    def on_up(self, data=None) -> None:
        """Move selection up."""
        if not self.items:
            return
        self.selected_index = (self.selected_index - 1) % len(self.items)

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.on_advance()
