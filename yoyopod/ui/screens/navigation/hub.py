"""Graffiti Buddy root hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from yoyopod.ui.display import Display
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.navigation.lvgl import LvglHubView
from yoyopod.ui.screens.theme import (
    BACKGROUND,
    format_battery_compact,
    mix,
    text_fit,
    theme_for,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.backends.music import MusicBackend
    from yoyopod.integrations.music import LocalMusicService
    from yoyopod.integrations.call import VoIPManager
    from yoyopod.ui.screens.view import ScreenView


@dataclass(frozen=True, slots=True)
class HubCard:
    """One primary root action."""

    title: str
    subtitle: str
    mode: str
    icon: str


class HubScreen(Screen):
    """Carousel-style root screen for the one-button Whisplay flow."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        music_backend: Optional["MusicBackend"] = None,
        local_music_service: Optional["LocalMusicService"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "ActionHub", app=app)
        self.music_backend = music_backend
        self.local_music_service = local_music_service
        self.voip_manager = voip_manager
        self.selected_index = 0
        self._playlist_count: int | None = None
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh lightweight summaries when the hub becomes active."""
        super().enter()
        self._refresh_playlist_count()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL Hub view alive across transitions."""
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

        self._lvgl_view = LvglHubView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _refresh_playlist_count(self) -> None:
        """Refresh the cached playlist count for the Listen card."""
        music_service = self._resolve_music_service()
        if music_service is None or not music_service.is_available:
            self._playlist_count = None
            return

        try:
            self._playlist_count = music_service.playlist_count()
        except Exception:
            self._playlist_count = None

    def cards(self) -> list[HubCard]:
        """Build the live root-card list."""
        return [
            HubCard("Listen", self._listen_subtitle(), "listen", "listen"),
            HubCard("Talk", self._talk_subtitle(), "talk", "talk"),
            HubCard("Ask", "Safe questions", "ask", "ask"),
            HubCard("Setup", self._setup_subtitle(), "setup", "setup"),
        ]

    def _listen_subtitle(self) -> str:
        """Return the compact Listen card subtitle."""
        music_backend = self._resolve_music_backend()
        if music_backend is None:
            return "Music offline"
        if not music_backend.is_connected:
            return "Reconnect"

        track = music_backend.get_current_track()
        playback_state = music_backend.get_playback_state()
        if track is None:
            if self._playlist_count:
                label = "playlist" if self._playlist_count == 1 else "playlists"
                return f"{self._playlist_count} {label}"
            return "On-device music"

        artist = track.get_artist_string() or "Unknown"
        artist = artist.split(",")[0]
        if playback_state == "playing":
            return text_fit(self.display, f"Playing {artist}", 134, 12)
        if playback_state == "paused":
            return "Paused"
        return "On-device music"

    def _talk_subtitle(self) -> str:
        """Return the compact Talk card subtitle."""
        if self.context is not None and self.context.talk.missed_calls > 0:
            missed_calls = self.context.talk.missed_calls
            label = "call" if missed_calls == 1 else "calls"
            return f"{missed_calls} missed {label}"

        if self.context is None:
            return "Unavailable"
        if not self.context.voip.configured:
            return "Not set up"
        if not self.context.voip.running:
            return "Recovering"
        if self.context.voip.ready:
            return "Calls ready"
        if self.context.voip.registration_state == "progress":
            return "Connecting"
        return "Offline"

    def _setup_subtitle(self) -> str:
        """Return the compact Setup card subtitle."""
        return format_battery_compact(self.context)

    @staticmethod
    def tile_fill_color(mode: str) -> tuple[int, int, int]:
        """Return the main hero-tile fill for the selected hub card."""
        theme = theme_for(mode)
        return mix(theme.accent, theme.hero_end, 0.35)

    @staticmethod
    def tile_glow_color(mode: str) -> tuple[int, int, int]:
        """Return a soft mode glow behind the hero tile."""
        theme = theme_for(mode)
        return mix(theme.accent, BACKGROUND, 0.72)

    def render(self) -> None:
        """Render the selected root card."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("HubScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    def on_advance(self, data=None) -> None:
        """Cycle to the next card."""
        self.selected_index = (self.selected_index + 1) % len(self.cards())

    def on_select(self, data=None) -> None:
        """Open the selected root card."""
        self.request_route("select", payload=self.cards()[self.selected_index].title)

    def on_back(self, data=None) -> None:
        """Open Ask in quick-command mode (hold-to-ask shortcut)."""
        if self.screen_manager is not None:
            ask_screen = self.screen_manager.screens.get("ask")
            if ask_screen is not None and hasattr(ask_screen, "set_quick_command"):
                ask_screen.set_quick_command(True)
        self.request_route("hold_ask")

    def _resolve_music_backend(self) -> "MusicBackend | None":
        """Resolve the music backend from the constructor or owning app."""

        if self.music_backend is not None:
            return self.music_backend
        if self.app is None:
            return None
        backend = getattr(self.app, "music_backend", None)
        if backend is not None:
            self.music_backend = backend
        return self.music_backend

    def _resolve_music_service(self) -> "LocalMusicService | None":
        """Resolve the local music service from the constructor or owning app."""

        if self.local_music_service is not None:
            return self.local_music_service
        if self.app is None:
            return None
        getter = getattr(self.app, "get_music_library", None)
        if callable(getter):
            resolved = getter()
            if resolved is not None:
                self.local_music_service = resolved
                return resolved
        service = getattr(self.app, "local_music_service", None)
        if service is not None:
            self.local_music_service = service
        return self.local_music_service
