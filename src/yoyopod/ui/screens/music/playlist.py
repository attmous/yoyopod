"""Graffiti Buddy local playlist browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopod.audio.local_service import LocalMusicService
from yoyopod.ui.display import Display
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.music.lvgl import LvglPlaylistView
from yoyopod.ui.screens.theme import (
    draw_empty_state,
    draw_list_item,
    render_footer,
    render_header,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens import ScreenView


class PlaylistScreen(Screen):
    """Browse local playlists from the on-device music library."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        music_service: Optional[LocalMusicService] = None,
    ) -> None:
        super().__init__(display, context, "PlaylistBrowser")
        self.music_service = music_service
        self.playlists = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 3 if display.is_portrait() else 4
        self.loading = False
        self.error_message: str | None = None
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh playlists when the screen becomes active."""
        super().enter()
        self._ensure_lvgl_view()
        self.fetch_playlists()

    def exit(self) -> None:
        """Leave the retained LVGL playlist view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglPlaylistView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _update_scroll_window(self) -> None:
        """Keep the selected item visible within the current scroll window."""
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

    @staticmethod
    def get_title_text() -> str:
        """Return the compact title used by the LVGL list scene."""

        return "Playlists"

    def get_footer_text(self) -> str:
        """Return the list footer hint for the active interaction mode."""

        return "Tap next / Load" if self.is_one_button_mode() else "A load | B back | X/Y move"

    def get_empty_state_copy(self) -> tuple[str, str]:
        """Return the title/subtitle pair for the current empty/error state."""

        if self.loading:
            return ("Loading playlists", "Hold on while your mixes come in.")
        if self.error_message:
            return ("Music hiccup", self.error_message)
        return ("No playlists", "Add local playlists to see them here.")

    def get_visible_window(self) -> tuple[list[str], list[str], int]:
        """Return visible playlist titles, badges, and the selected row index."""
        if not self.playlists:
            return [], [], 0

        self._update_scroll_window()

        visible_titles: list[str] = []
        visible_badges: list[str] = []
        selected_visible_index = 0

        for row in range(self.max_visible_items):
            playlist_index = self.scroll_offset + row
            if playlist_index >= len(self.playlists):
                break

            playlist = self.playlists[playlist_index]
            badge = f"{playlist.track_count}" if getattr(playlist, "track_count", 0) else ""
            visible_titles.append(playlist.name)
            visible_badges.append(badge)
            if playlist_index == self.selected_index:
                selected_visible_index = row

        return visible_titles, visible_badges, selected_visible_index

    def get_visible_subtitles(self) -> list[str]:
        """Return visible subtitles for the shared LVGL scene."""

        visible_titles, _, _ = self.get_visible_window()
        return ["" for _ in visible_titles]

    def get_visible_icon_keys(self) -> list[str]:
        """Return visible icon keys for the shared LVGL scene."""

        visible_titles, _, _ = self.get_visible_window()
        return ["playlist" for _ in visible_titles]

    def fetch_playlists(self) -> None:
        """Fetch local playlists from the app-facing local music service."""
        if self.music_service is None:
            self.error_message = "No music backend"
            logger.error("Cannot fetch playlists: no local music service")
            return

        if not self.music_service.is_available:
            self.error_message = "Music offline"
            logger.error("Cannot fetch playlists: music backend is offline")
            return

        self.loading = True
        self.render()

        try:
            self.playlists = self.music_service.list_playlists(fetch_track_counts=True)
            self.error_message = None
            logger.info(f"Fetched {len(self.playlists)} local playlists")
        except Exception as exc:
            self.error_message = f"Oops: {str(exc)[:24]}"
            logger.error(f"Failed to fetch local playlists: {exc}")
        finally:
            self.loading = False
            self.render()

    def render(self) -> None:
        """Render the local playlist browser."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Playlists",
            show_time=False,
            show_mode_chip=False,
        )

        if self.loading:
            draw_empty_state(
                self.display,
                mode="listen",
                title="Loading playlists",
                subtitle="Hold on while your mixes come in.",
                icon="playlist",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="listen")
            self.display.update()
            return

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

        if not self.playlists:
            draw_empty_state(
                self.display,
                mode="listen",
                title="No playlists",
                subtitle="Add local playlists to see them here.",
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
            playlist_index = self.scroll_offset + row
            if playlist_index >= len(self.playlists):
                break

            playlist = self.playlists[playlist_index]
            y1 = list_top + (row * item_height)
            y2 = y1 + 44
            badge = f"{playlist.track_count}" if getattr(playlist, "track_count", 0) else None
            draw_list_item(
                self.display,
                x1=18,
                y1=y1,
                x2=self.display.WIDTH - 18,
                y2=y2,
                title=text_fit(self.display, playlist.name, self.display.WIDTH - 92, 15),
                subtitle="",
                mode="listen",
                selected=playlist_index == self.selected_index,
                badge=badge,
                icon="playlist",
            )

        help_text = f"{self.get_footer_text()} / Hold back" if self.is_one_button_mode() else self.get_footer_text()
        render_footer(self.display, help_text, mode="listen")
        self.display.update()

    def select_next(self) -> None:
        """Move to the next playlist."""
        if self.playlists and self.selected_index < len(self.playlists) - 1:
            self.selected_index += 1

    def select_next_wrapped(self) -> None:
        """Move to the next playlist with wraparound."""
        if not self.playlists:
            return
        self.selected_index = (self.selected_index + 1) % len(self.playlists)

    def select_previous(self) -> None:
        """Move to the previous playlist."""
        if self.playlists and self.selected_index > 0:
            self.selected_index -= 1

    def load_selected_playlist(self) -> None:
        """Load and play the selected playlist."""
        if not self.playlists or self.selected_index >= len(self.playlists):
            logger.warning("No playlist selected")
            return

        if self.music_service is None:
            logger.error("Cannot load playlist: no local music service")
            return

        playlist = self.playlists[self.selected_index]
        logger.info(f"Loading local playlist: {playlist.name}")

        try:
            if self.music_service.load_playlist(playlist.uri):
                self.request_route("playlist_loaded")
            else:
                self.error_message = "Load failed"
                self.render()
        except Exception as exc:
            logger.error(f"Error loading playlist: {exc}")
            self.error_message = f"Error: {str(exc)[:20]}"
            self.render()

    def on_select(self, data=None) -> None:
        """Load and play the selected playlist."""
        self.load_selected_playlist()

    def on_back(self, data=None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next playlist in one-button mode."""
        self.select_next_wrapped()

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
