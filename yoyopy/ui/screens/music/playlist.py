"""Graffiti Buddy playlist browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    INK,
    LISTEN,
    MUTED,
    SURFACE,
    audio_source_label,
    draw_empty_state,
    draw_list_item,
    render_footer,
    render_header,
    rounded_panel,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class PlaylistScreen(Screen):
    """Playlist browser for configured Listen sources."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        mopidy_client=None,
    ) -> None:
        super().__init__(display, context, "PlaylistBrowser")
        self.mopidy_client = mopidy_client
        self.playlists = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 4
        self.loading = False
        self.error_message: str | None = None

    def enter(self) -> None:
        """Refresh playlists when the screen becomes active."""
        super().enter()
        self.fetch_playlists()

    def fetch_playlists(self) -> None:
        """Fetch playlists from Mopidy."""
        if not self.mopidy_client:
            self.error_message = "No music backend"
            logger.error("Cannot fetch playlists: no Mopidy client")
            return

        if not self.mopidy_client.is_connected:
            self.error_message = "Music offline"
            logger.error("Cannot fetch playlists: Mopidy is offline")
            return

        self.loading = True
        self.render()

        try:
            self.playlists = self.mopidy_client.get_playlists(fetch_track_counts=True)
            self.error_message = None
            logger.info(f"Fetched {len(self.playlists)} playlists")
        except Exception as exc:
            self.error_message = f"Oops: {str(exc)[:24]}"
            logger.error(f"Failed to fetch playlists: {exc}")
        finally:
            self.loading = False
            self.render()

    def render(self) -> None:
        """Render the source-themed playlist browser."""
        source_label = audio_source_label(getattr(self.context, "current_audio_source", "local"))
        page_text = None
        if self.playlists:
            page_text = f"{self.selected_index + 1}/{len(self.playlists)}"

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Listen",
            subtitle=f"{source_label} playlists",
            icon="playlist",
            page_text=page_text,
            show_time=False,
        )

        if self.loading:
            draw_empty_state(
                self.display,
                mode="listen",
                title="Loading playlists",
                subtitle="Hold on while your lists come in.",
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
                title="No playlists yet",
                subtitle="Add playlists to see them here.",
                icon="playlist",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="listen")
            self.display.update()
            return

        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

        panel_top = content_top + 6
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=24,
        )

        item_height = 52
        for row in range(self.max_visible_items):
            playlist_index = self.scroll_offset + row
            if playlist_index >= len(self.playlists):
                break

            playlist = self.playlists[playlist_index]
            y1 = panel_top + 10 + (row * item_height)
            y2 = y1 + 42
            badge = f"{playlist.track_count}" if getattr(playlist, "track_count", 0) else None
            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=text_fit(self.display, playlist.name, self.display.WIDTH - 92, 15),
                subtitle=f"{playlist.track_count} tracks" if getattr(playlist, "track_count", 0) else source_label,
                mode="listen",
                selected=playlist_index == self.selected_index,
                badge=badge,
            )

        help_text = "Tap next | Double load | Hold back" if self.is_one_button_mode() else "A load | B back | X/Y move"
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

        if not self.mopidy_client:
            logger.error("Cannot load playlist: no Mopidy client")
            return

        playlist = self.playlists[self.selected_index]
        logger.info(f"Loading playlist: {playlist.name}")

        try:
            if self.mopidy_client.load_playlist(playlist.uri):
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
