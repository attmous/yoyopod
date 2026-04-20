"""Graffiti Buddy recent local tracks browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopod.audio import LocalMusicService, RecentTrackEntry
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.music.lvgl import LvglPlaylistView
from yoyopod.ui.screens.theme import (
    draw_empty_state,
    draw_list_item,
    render_footer,
    render_header,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens import ScreenView


class RecentTracksScreen(Screen):
    """Browse and replay recently played local tracks."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        music_service: Optional[LocalMusicService] = None,
    ) -> None:
        super().__init__(display, context, "RecentTracks")
        self.music_service = music_service
        self.tracks: list[RecentTrackEntry] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 3 if display.is_portrait() else 4
        self.error_message: str | None = None
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh recent tracks when the screen becomes active."""
        super().enter()
        self._ensure_lvgl_view()
        self.refresh_tracks()

    def exit(self) -> None:
        """Leave the retained LVGL recent-tracks view alive across transitions."""
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

        self._lvgl_view = LvglPlaylistView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    @staticmethod
    def get_title_text() -> str:
        """Return the compact title used by the LVGL list scene."""

        return "Recent"

    def get_footer_text(self) -> str:
        """Return the list footer hint for the active interaction mode."""

        return "Tap next / Play" if self.is_one_button_mode() else "A play | B back | X/Y move"

    def get_empty_state_copy(self) -> tuple[str, str]:
        """Return the title/subtitle pair for the current empty/error state."""

        if self.error_message:
            return ("Music hiccup", self.error_message)
        return ("No recent tracks", "Play local music to fill this list.")

    def _update_scroll_window(self) -> None:
        """Keep the selected item visible within the current scroll window."""
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

    def refresh_tracks(self) -> None:
        """Refresh recent tracks from the persistent history store."""
        if self.music_service is None:
            self.error_message = "No music backend"
            self.tracks = []
            return

        self.tracks = self.music_service.list_recent_tracks()
        self.error_message = None
        if self.tracks:
            self.selected_index = min(self.selected_index, len(self.tracks) - 1)
        else:
            self.selected_index = 0
        self.render()

    def get_visible_window(self) -> tuple[list[str], list[str], int]:
        """Return visible track titles, empty badges, and selected row index."""
        if not self.tracks:
            return [], [], 0

        self._update_scroll_window()

        visible_titles: list[str] = []
        visible_badges: list[str] = []
        selected_visible_index = 0

        for row in range(self.max_visible_items):
            track_index = self.scroll_offset + row
            if track_index >= len(self.tracks):
                break

            track = self.tracks[track_index]
            visible_titles.append(track.title)
            visible_badges.append("")
            if track_index == self.selected_index:
                selected_visible_index = row

        return visible_titles, visible_badges, selected_visible_index

    def get_visible_subtitles(self) -> list[str]:
        """Return visible subtitles for the shared LVGL scene."""

        if not self.tracks:
            return []

        subtitles: list[str] = []
        for row in range(self.max_visible_items):
            track_index = self.scroll_offset + row
            if track_index >= len(self.tracks):
                break
            subtitles.append(self.tracks[track_index].subtitle)
        return subtitles

    def get_visible_icon_keys(self) -> list[str]:
        """Return visible icon keys for the shared LVGL scene."""

        visible_titles, _, _ = self.get_visible_window()
        return ["music_note" for _ in visible_titles]

    def render(self) -> None:
        """Render the recent-track browser."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Recent",
            show_time=False,
            show_mode_chip=False,
        )

        if self.error_message:
            draw_empty_state(
                self.display,
                mode="listen",
                title="Music hiccup",
                subtitle=self.error_message,
                icon="playlist",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="listen")
            self.display.update()
            return

        if not self.tracks:
            draw_empty_state(
                self.display,
                mode="listen",
                title="No recent tracks",
                subtitle="Play local music to fill this list.",
                icon="playlist",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="listen")
            self.display.update()
            return

        self._update_scroll_window()

        item_height = 52
        list_top = content_top + 8
        for row in range(self.max_visible_items):
            track_index = self.scroll_offset + row
            if track_index >= len(self.tracks):
                break

            track = self.tracks[track_index]
            y1 = list_top + (row * item_height)
            y2 = y1 + 44
            draw_list_item(
                self.display,
                x1=18,
                y1=y1,
                x2=self.display.WIDTH - 18,
                y2=y2,
                title=text_fit(self.display, track.title, self.display.WIDTH - 48, 15),
                subtitle=text_fit(self.display, track.subtitle, self.display.WIDTH - 48, 11),
                mode="listen",
                selected=track_index == self.selected_index,
                icon="music_note",
            )

        help_text = f"{self.get_footer_text()} / Hold back" if self.is_one_button_mode() else self.get_footer_text()
        render_footer(self.display, help_text, mode="listen")
        self.display.update()

    def on_select(self, data=None) -> None:
        """Load and play the selected recent track."""
        if not self.tracks or self.music_service is None:
            return

        track = self.tracks[self.selected_index]
        logger.info(f"Loading recent local track: {track.title}")
        if self.music_service.play_recent_track(track.uri):
            self.request_route("track_loaded")

    def on_back(self, data=None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next recent track with wraparound."""
        if not self.tracks:
            return
        self.selected_index = (self.selected_index + 1) % len(self.tracks)

    def on_up(self, data=None) -> None:
        """Move selection up."""
        if not self.tracks:
            return
        self.selected_index = (self.selected_index - 1) % len(self.tracks)

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.on_advance()
