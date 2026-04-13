"""Graffiti Buddy root hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.navigation.lvgl import LvglHubView
from yoyopy.ui.screens.theme import (
    BACKGROUND,
    FOOTER_BAR,
    INK,
    MUTED_DIM,
    draw_icon,
    format_battery_compact,
    mix,
    render_backdrop,
    render_status_bar,
    rounded_panel,
    text_fit,
    theme_for,
)

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.audio import LocalMusicService
    from yoyopy.audio.music.backend import MusicBackend
    from yoyopy.voip import VoIPManager
    from yoyopy.ui.screens import ScreenView


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
    ) -> None:
        super().__init__(display, context, "ActionHub")
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
        """Tear down any active LVGL view when leaving the hub."""
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

        self._lvgl_view = LvglHubView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _refresh_playlist_count(self) -> None:
        """Refresh the cached playlist count for the Listen card."""
        if self.local_music_service is None or not self.local_music_service.is_available:
            self._playlist_count = None
            return

        try:
            self._playlist_count = self.local_music_service.playlist_count()
        except Exception:
            self._playlist_count = None

    def _cards(self) -> list[HubCard]:
        """Build the live root-card list."""
        return [
            HubCard("Listen", self._listen_subtitle(), "listen", "listen"),
            HubCard("Talk", self._talk_subtitle(), "talk", "talk"),
            HubCard("Ask", "Safe questions", "ask", "ask"),
            HubCard("Setup", self._setup_subtitle(), "setup", "setup"),
        ]

    def _listen_subtitle(self) -> str:
        """Return the compact Listen card subtitle."""
        if self.music_backend is None:
            return "Music offline"
        if not self.music_backend.is_connected:
            return "Reconnect"

        track = self.music_backend.get_current_track()
        playback_state = self.music_backend.get_playback_state()
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
        if self.context is not None and getattr(self.context, "missed_calls", 0) > 0:
            missed_calls = int(self.context.missed_calls)
            label = "call" if missed_calls == 1 else "calls"
            return f"{missed_calls} missed {label}"

        if self.voip_manager is None:
            return "Unavailable"

        status = self.voip_manager.get_status()
        if not status.get("sip_identity"):
            return "Not set up"
        if not status.get("running", False):
            return "Recovering"
        if status.get("registered", False):
            return "Calls ready"
        if status.get("registration_state") == "progress":
            return "Connecting"
        return "Offline"

    def _setup_subtitle(self) -> str:
        """Return the compact Setup card subtitle."""
        return format_battery_compact(self.context)

    @staticmethod
    def _tile_fill_color(mode: str) -> tuple[int, int, int]:
        """Return the main hero-tile fill for the selected hub card."""
        theme = theme_for(mode)
        return mix(theme.accent, theme.hero_end, 0.35)

    @staticmethod
    def _tile_glow_color(mode: str) -> tuple[int, int, int]:
        """Return a soft mode glow behind the hero tile."""
        theme = theme_for(mode)
        return mix(theme.accent, BACKGROUND, 0.72)

    def render(self) -> None:
        """Render the selected root card."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        cards = self._cards()
        self.selected_index %= len(cards)
        selected_card = cards[self.selected_index]
        render_backdrop(self.display, selected_card.mode)
        render_status_bar(self.display, self.context, show_time=True)

        tile_size = 96
        tile_left = (self.display.WIDTH - tile_size) // 2
        tile_top = self.display.STATUS_BAR_HEIGHT + 30
        glow_padding = 10

        rounded_panel(
            self.display,
            tile_left - glow_padding,
            tile_top - glow_padding,
            tile_left + tile_size + glow_padding,
            tile_top + tile_size + glow_padding,
            fill=self._tile_glow_color(selected_card.mode),
            outline=None,
            radius=24,
            shadow=False,
        )

        rounded_panel(
            self.display,
            tile_left,
            tile_top,
            tile_left + tile_size,
            tile_top + tile_size,
            fill=self._tile_fill_color(selected_card.mode),
            outline=None,
            radius=16,
            shadow=True,
        )

        draw_icon(
            self.display,
            selected_card.icon,
            tile_left + 20,
            tile_top + 20,
            56,
            INK,
        )

        title_y = tile_top + tile_size + 24
        title_text = selected_card.title
        title_width, title_height = self.display.get_text_size(title_text, 22)
        self.display.text(
            title_text,
            (self.display.WIDTH - title_width) // 2,
            title_y,
            color=INK,
            font_size=22,
        )

        dots_y = title_y + title_height + 30
        dot_gap = 10
        dots_width = ((len(cards) - 1) * dot_gap) + 4
        dots_x = (self.display.WIDTH - dots_width) // 2
        inactive_dot = mix(INK, BACKGROUND, 0.8)
        for index in range(len(cards)):
            dot_color = INK if index == self.selected_index else inactive_dot
            self.display.circle(dots_x + (index * dot_gap), dots_y, 2, fill=dot_color)

        footer_top = self.display.HEIGHT - 32
        self.display.rectangle(0, footer_top, self.display.WIDTH, self.display.HEIGHT, fill=FOOTER_BAR)
        footer_text = "Tap = Next \u00b7 2\u00d7 = Open \u00b7 Hold = Ask"
        footer_width, footer_height = self.display.get_text_size(footer_text, 10)
        self.display.text(
            footer_text,
            (self.display.WIDTH - footer_width) // 2,
            footer_top + ((32 - footer_height) // 2) - 1,
            color=MUTED_DIM,
            font_size=10,
        )
        self.display.update()

    def on_advance(self, data=None) -> None:
        """Cycle to the next card (one-button navigation)."""
        self.selected_index = (self.selected_index + 1) % len(self._cards())

    def on_down(self, data=None) -> None:
        """Move to the next card (4-button: Y = down/next)."""
        self.selected_index = (self.selected_index + 1) % len(self._cards())

    def on_up(self, data=None) -> None:
        """Move to the previous card (4-button: X = up/prev)."""
        self.selected_index = (self.selected_index - 1) % len(self._cards())

    def on_select(self, data=None) -> None:
        """Open the selected root card."""
        self.request_route("select", payload=self._cards()[self.selected_index].title)

    def on_back(self, data=None) -> None:
        """Open Ask in quick-command mode (hold-to-ask shortcut)."""
        if self.screen_manager is not None:
            ask_screen = self.screen_manager.screens.get("ask")
            if ask_screen is not None and hasattr(ask_screen, "set_quick_command"):
                ask_screen.set_quick_command(True)
        self.request_route("hold_ask")
