"""Graffiti Buddy root hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.navigation.lvgl import LvglHubView
from yoyopy.ui.screens.theme import BACKGROUND, INK, SURFACE, draw_icon, format_battery_compact, mix, render_backdrop, render_footer, render_status_bar, rounded_panel, text_fit, theme_for

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.audio.mopidy_client import MopidyClient
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
        mopidy_client: Optional["MopidyClient"] = None,
        voip_manager: Optional["VoIPManager"] = None,
    ) -> None:
        super().__init__(display, context, "ActionHub")
        self.mopidy_client = mopidy_client
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
        if self.mopidy_client is None or not self.mopidy_client.is_connected:
            self._playlist_count = None
            return

        try:
            self._playlist_count = len(self.mopidy_client.get_playlists(fetch_track_counts=False))
        except Exception:
            self._playlist_count = None

    def _cards(self) -> list[HubCard]:
        """Build the live root-card list."""
        return [
            HubCard("Listen", self._listen_subtitle(), "listen", "listen"),
            HubCard("Talk", self._talk_subtitle(), "talk", "talk"),
            HubCard("Ask", "Coming soon", "ask", "ask"),
            HubCard("Setup", self._setup_subtitle(), "setup", "setup"),
        ]

    def _listen_subtitle(self) -> str:
        """Return the compact Listen card subtitle."""
        if self.mopidy_client is None:
            return "Music offline"
        if not self.mopidy_client.is_connected:
            return "Reconnect"

        current_source = getattr(self.context, "current_audio_source", "local").strip().lower()
        source_label = {
            "spotify": "Spotify",
            "amazon": "Amazon",
            "youtube": "YouTube",
            "local": "Local",
        }.get(current_source, "Music")

        track = self.mopidy_client.get_current_track()
        playback_state = self.mopidy_client.get_playback_state()
        if track is None:
            if self._playlist_count:
                label = "playlist" if self._playlist_count == 1 else "playlists"
                return f"{self._playlist_count} {label}"
            return source_label

        artist = track.get_artist_string() or "Unknown"
        artist = artist.split(",")[0]
        if playback_state == "playing":
            return text_fit(self.display, f"Playing {artist}", 134, 12)
        if playback_state == "paused":
            return "Paused"
        return source_label

    def _talk_subtitle(self) -> str:
        """Return the compact Talk card subtitle."""
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
    def _card_fill_color(mode: str) -> tuple[int, int, int]:
        """Return a low-opacity mode tint for the hub card surface."""
        theme = theme_for(mode)
        return mix(theme.accent, SURFACE, 0.9)

    @staticmethod
    def _icon_halo_fill(mode: str) -> tuple[int, int, int]:
        """Return a darker mode tint for the icon halo."""
        theme = theme_for(mode)
        return mix(theme.accent, BACKGROUND, 0.8)

    @staticmethod
    def _icon_halo_outline(mode: str) -> tuple[int, int, int]:
        """Return a subtle outline for the icon halo."""
        theme = theme_for(mode)
        return mix(theme.accent, BACKGROUND, 0.6)

    def render(self) -> None:
        """Render the selected root card."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        cards = self._cards()
        self.selected_index %= len(cards)
        selected_card = cards[self.selected_index]
        theme = render_backdrop(self.display, selected_card.mode)
        render_status_bar(self.display, self.context, show_time=True)

        card_left = 16
        card_top = self.display.STATUS_BAR_HEIGHT + 24
        card_right = self.display.WIDTH - 16
        card_bottom = self.display.HEIGHT - 30
        rounded_panel(
            self.display,
            card_left,
            card_top,
            card_right,
            card_bottom,
            fill=self._card_fill_color(selected_card.mode),
            outline=theme.accent_dim,
            radius=28,
            shadow=True,
        )

        halo_left = (self.display.WIDTH // 2) - 42
        halo_top = card_top + 18
        halo_right = (self.display.WIDTH // 2) + 42
        halo_bottom = halo_top + 64
        rounded_panel(
            self.display,
            halo_left,
            halo_top,
            halo_right,
            halo_bottom,
            fill=self._icon_halo_fill(selected_card.mode),
            outline=self._icon_halo_outline(selected_card.mode),
            radius=22,
            shadow=False,
        )

        draw_icon(self.display, selected_card.icon, (self.display.WIDTH // 2) - 30, card_top + 24, 60, theme.accent)

        title_y = card_top + 106
        title_text = selected_card.title
        title_width, title_height = self.display.get_text_size(title_text, 28)
        self.display.text(title_text, (self.display.WIDTH - title_width) // 2, title_y, color=theme.accent, font_size=28)

        subtitle = text_fit(self.display, selected_card.subtitle, self.display.WIDTH - 58, 13)
        subtitle_width, _ = self.display.get_text_size(subtitle, 13)
        self.display.text(subtitle, (self.display.WIDTH - subtitle_width) // 2, title_y + title_height + 10, color=INK, font_size=13)

        dots_y = card_bottom - 18
        dots_width = 18 * len(cards)
        dots_x = (self.display.WIDTH - dots_width) // 2
        for index in range(len(cards)):
            dot_color = theme.accent if index == self.selected_index else theme.accent_dim
            radius = 4 if index == self.selected_index else 3
            self.display.circle(dots_x + (index * 18), dots_y, radius, fill=dot_color)

        render_footer(self.display, "Tap next / Double open", mode=selected_card.mode)
        self.display.update()

    def on_advance(self, data=None) -> None:
        """Cycle to the next card."""
        self.selected_index = (self.selected_index + 1) % len(self._cards())

    def on_select(self, data=None) -> None:
        """Open the selected root card."""
        self.request_route("select", payload=self._cards()[self.selected_index].title)

    def on_back(self, data=None) -> None:
        """Back is intentionally a no-op on the root hub."""
        return
