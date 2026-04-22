"""Graffiti Buddy recent local tracks browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.music import PlayRecentTrackCommand
from yoyopod.integrations.music import LocalMusicService, RecentTrackEntry
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.music.lvgl import LvglPlaylistView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


class RecentTracksScreen(Screen):
    """Browse and replay recently played local tracks."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        app: Any | None = None,
        music_service: Optional[LocalMusicService] = None,
    ) -> None:
        super().__init__(display, context, "RecentTracks", app=app)
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
        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
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
        music_service = self._resolve_music_service()
        if music_service is None:
            self.error_message = "No music backend"
            self.tracks = []
            return

        self.tracks = music_service.list_recent_tracks()
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
        if lvgl_view is None:
            raise RuntimeError("RecentTracksScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    def on_select(self, data=None) -> None:
        """Load and play the selected recent track."""
        music_service = self._resolve_music_service()
        if not self.tracks or music_service is None:
            return

        track = self.tracks[self.selected_index]
        logger.info(f"Loading recent local track: {track.title}")
        if self._play_recent_track(track.uri, music_service=music_service):
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

    def _resolve_music_service(self) -> LocalMusicService | None:
        """Resolve the local music service from the constructor or owning app."""

        if self.music_service is not None:
            return self.music_service
        if self.app is None:
            return None
        getter = getattr(self.app, "get_music_library", None)
        if callable(getter):
            resolved = getter()
            if isinstance(resolved, LocalMusicService):
                self.music_service = resolved
                return resolved
        fallback = getattr(self.app, "local_music_service", None)
        if isinstance(fallback, LocalMusicService):
            self.music_service = fallback
            return fallback
        return None

    def _play_recent_track(
        self,
        track_uri: str,
        *,
        music_service: LocalMusicService,
    ) -> bool:
        """Replay one recent track through services when available."""

        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            try:
                return bool(
                    services.call(
                        "music",
                        "play_recent_track",
                        PlayRecentTrackCommand(track_uri=track_uri),
                    )
                )
            except Exception:
                return False
        return bool(music_service.play_recent_track(track_uri))
