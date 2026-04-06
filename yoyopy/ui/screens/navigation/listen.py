"""Tangara-inspired local library menu for Listen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from yoyopy.audio.local_service import LocalLibraryItem, LocalMusicService
from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.navigation.lvgl import LvglListenView
from yoyopy.ui.screens.theme import (
    LISTEN,
    MUTED,
    SURFACE,
    draw_list_item,
    render_footer,
    render_header,
    rounded_panel,
)

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView


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
        """Tear down any active LVGL view when leaving Listen."""
        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

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
            title="Listen",
            page_text=None,
            show_time=False,
            show_mode_chip=False,
        )

        panel_top = content_top + 4
        panel_bottom = self.display.HEIGHT - 26
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=22,
        )

        list_top = panel_top + 10
        item_height = 46
        for index, item in enumerate(self.items):
            y1 = list_top + (index * item_height)
            y2 = y1 + 40
            if y2 > panel_bottom - 8:
                break

            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=item.title,
                subtitle=item.subtitle,
                mode="listen",
                selected=index == self.selected_index,
            )

        dots_y = panel_bottom - 12
        dots_width = 16 * len(self.items)
        dots_x = (self.display.WIDTH - dots_width) // 2
        for index in range(len(self.items)):
            color = LISTEN.accent if index == self.selected_index else MUTED
            self.display.circle(dots_x + (index * 16), dots_y, 3, fill=color)

        help_text = "Tap next / Open / Hold back" if self.is_one_button_mode() else "A open | B back | X/Y move"
        render_footer(self.display, help_text, mode="listen")
        self.display.update()

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
