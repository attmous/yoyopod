"""Graffiti Buddy root hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    ASK,
    INK,
    LISTEN,
    MUTED,
    SETUP,
    TALK,
    draw_icon,
    format_battery_compact,
    render_footer,
    render_status_bar,
    render_backdrop,
    rounded_panel,
    theme_for,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.audio.mopidy_client import MopidyClient
    from yoyopy.voip import VoIPManager


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

    def enter(self) -> None:
        """Refresh lightweight summaries when the hub becomes active."""
        super().enter()
        self._refresh_playlist_count()

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
            HubCard("Ask", "Safe future mode", "ask", "ask"),
            HubCard("Setup", self._setup_subtitle(), "setup", "setup"),
        ]

    def _listen_subtitle(self) -> str:
        """Return the compact Listen card subtitle."""
        if self.mopidy_client is None:
            return "Music offline"
        if not self.mopidy_client.is_connected:
            return "Reconnect music"

        current_source = getattr(self.context, "current_audio_source", "local").strip().lower()
        source_label = {
            "spotify": "Spotify ready",
            "amazon": "Amazon ready",
            "youtube": "YouTube ready",
            "local": "Local playlists",
        }.get(current_source, "Music ready")

        track = self.mopidy_client.get_current_track()
        playback_state = self.mopidy_client.get_playback_state()
        if track is None:
            if self._playlist_count:
                return f"{source_label} · {self._playlist_count} lists"
            return source_label

        artist = track.get_artist_string() or "Unknown"
        artist = artist.split(",")[0]
        if playback_state == "playing":
            return text_fit(self.display, f"Playing {artist}", 134, 12)
        if playback_state == "paused":
            return text_fit(self.display, f"Paused {artist}", 134, 12)
        return text_fit(self.display, f"Ready {artist}", 134, 12)

    def _talk_subtitle(self) -> str:
        """Return the compact Talk card subtitle."""
        if self.voip_manager is None:
            return "Calls unavailable"

        status = self.voip_manager.get_status()
        if not status.get("sip_identity"):
            return "Voice notes soon"
        if not status.get("running", False):
            return "Recovering calls"
        if status.get("registered", False):
            return "Calls ready"
        if status.get("registration_state") == "progress":
            return "Connecting..."
        return "Calls offline"

    def _setup_subtitle(self) -> str:
        """Return the compact Setup card subtitle."""
        return format_battery_compact(self.context)

    def render(self) -> None:
        """Render the selected root card."""
        cards = self._cards()
        self.selected_index %= len(cards)
        selected_card = cards[self.selected_index]
        theme = render_backdrop(self.display, selected_card.mode)
        render_status_bar(self.display, self.context, show_time=True)

        brand_text = "YOYOPOD"
        brand_width, _ = self.display.get_text_size(brand_text, 10)
        self.display.text(brand_text, (self.display.WIDTH - brand_width) // 2, self.display.STATUS_BAR_HEIGHT + 8, color=MUTED, font_size=10)

        card_left = 14
        card_top = self.display.STATUS_BAR_HEIGHT + 26
        card_right = self.display.WIDTH - 14
        card_bottom = self.display.HEIGHT - 34
        rounded_panel(
            self.display,
            card_left,
            card_top,
            card_right,
            card_bottom,
            fill=(29, 33, 40),
            outline=theme.accent_dim,
            radius=28,
            shadow=True,
        )

        draw_icon(self.display, selected_card.icon, (self.display.WIDTH // 2) - 28, card_top + 18, 56, theme.accent)

        title_y = card_top + 92
        title_text = selected_card.title
        title_width, title_height = self.display.get_text_size(title_text, 28)
        self.display.text(title_text, (self.display.WIDTH - title_width) // 2, title_y, color=theme.accent, font_size=28)

        subtitle = text_fit(self.display, selected_card.subtitle, self.display.WIDTH - 58, 13)
        subtitle_width, _ = self.display.get_text_size(subtitle, 13)
        self.display.text(subtitle, (self.display.WIDTH - subtitle_width) // 2, title_y + title_height + 10, color=INK, font_size=13)

        chip_width, _ = self.display.get_text_size("Double open", 11)
        rounded_panel(
            self.display,
            (self.display.WIDTH - chip_width - 24) // 2,
            title_y + title_height + 42,
            (self.display.WIDTH + chip_width + 24) // 2,
            title_y + title_height + 66,
            fill=theme.accent_dim,
            outline=None,
            radius=12,
        )
        self.display.text("Double open", (self.display.WIDTH - chip_width) // 2, title_y + title_height + 48, color=theme.accent, font_size=11)

        strip_y = card_bottom - 52
        strip_width = self.display.WIDTH - 54
        strip_x = (self.display.WIDTH - strip_width) // 2
        rounded_panel(
            self.display,
            strip_x,
            strip_y,
            strip_x + strip_width,
            strip_y + 28,
            fill=(23, 26, 33),
            outline=None,
            radius=14,
        )
        for index, card in enumerate(cards):
            palette = theme_for(card.mode)
            item_x = strip_x + 14 + (index * ((strip_width - 28) // len(cards)))
            text = card.title[:5]
            color = palette.accent if index == self.selected_index else palette.accent_dim
            self.display.text(text, item_x, strip_y + 8, color=color, font_size=11)

        dots_y = card_bottom - 14
        dots_width = 16 * len(cards)
        dots_x = (self.display.WIDTH - dots_width) // 2
        for index, card in enumerate(cards):
            palette = theme_for(card.mode)
            color = palette.accent if index == self.selected_index else palette.accent_dim
            self.display.circle(dots_x + (index * 16), dots_y, 3, fill=color)

        render_footer(self.display, "Tap next | Double open", mode=selected_card.mode)
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
