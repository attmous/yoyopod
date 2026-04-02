"""Whisplay-native action hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.audio.mopidy_client import MopidyClient
    from yoyopy.voip import VoIPManager


@dataclass(frozen=True, slots=True)
class HubCard:
    """One primary Whisplay root action."""

    title: str
    subtitle: str


class HubScreen(Screen):
    """Carousel root screen for one-button Whisplay navigation."""

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
        """Refresh light-weight summaries when the hub becomes active."""
        super().enter()
        self._refresh_playlist_count()

    def _refresh_playlist_count(self) -> None:
        """Refresh the cached playlist count for the root hub card."""
        if self.mopidy_client is None or not self.mopidy_client.is_connected:
            self._playlist_count = None
            return

        try:
            playlists = self.mopidy_client.get_playlists(fetch_track_counts=False)
        except Exception:
            self._playlist_count = None
            return
        self._playlist_count = len(playlists)

    def _cards(self) -> list[HubCard]:
        """Build the live card list for rendering and selection."""
        return [
            HubCard(title="Now Playing", subtitle=self._music_subtitle()),
            HubCard(title="Playlists", subtitle=self._playlist_subtitle()),
            HubCard(title="Calls", subtitle=self._calls_subtitle()),
        ]

    def _music_subtitle(self) -> str:
        """Return the compact music status subtitle."""
        if self.mopidy_client is None:
            return "Music unavailable"
        if not self.mopidy_client.is_connected:
            return "Music offline"

        track = self.mopidy_client.get_current_track()
        playback_state = self.mopidy_client.get_playback_state()
        if track is None:
            if playback_state == "paused":
                return "Paused"
            return "No track loaded"

        artist = self._truncate(track.get_artist_string(), 14)
        if playback_state == "playing":
            return self._truncate(f"Playing {artist}", 22)
        if playback_state == "paused":
            return self._truncate(f"Paused {artist}", 22)
        return self._truncate(f"Ready {artist}", 22)

    def _playlist_subtitle(self) -> str:
        """Return the compact playlist status subtitle."""
        if self.mopidy_client is None:
            return "Music unavailable"
        if not self.mopidy_client.is_connected:
            return "Mopidy offline"
        if self._playlist_count is None:
            return "Open playlist browser"
        if self._playlist_count == 1:
            return "1 playlist ready"
        return f"{self._playlist_count} playlists ready"

    def _calls_subtitle(self) -> str:
        """Return the compact VoIP status subtitle."""
        if self.voip_manager is None:
            return "VoIP unavailable"

        status = self.voip_manager.get_status()
        if not status.get("running", False):
            return "Recovering..."
        if status.get("registered", False):
            return "VoIP ready"

        registration_state = status.get("registration_state", "none")
        if registration_state == "progress":
            return "Connecting..."
        if registration_state == "failed":
            return "Registration failed"
        return "VoIP unavailable"

    def render(self) -> None:
        """Render the Whisplay-first root carousel."""
        cards = self._cards()
        self.selected_index %= len(cards)
        selected_card = cards[self.selected_index]

        self.display.clear(self.display.COLOR_BLACK)

        current_time = datetime.now().strftime("%H:%M")
        battery = self.context.battery_percent if self.context else 100
        signal = self.context.signal_strength if self.context else 4
        self.display.status_bar(
            time_str=current_time,
            battery_percent=battery,
            signal_strength=signal,
        )

        title = "YoyoPod"
        title_size = 18
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 12
        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_GRAY,
            font_size=title_size,
        )

        card_left = 18
        card_top = title_y + title_height + 12
        card_right = self.display.WIDTH - 18
        card_bottom = self.display.HEIGHT - 44
        self.display.rectangle(
            card_left,
            card_top,
            card_right,
            card_bottom,
            fill=self.display.COLOR_DARK_GRAY,
            outline=self.display.COLOR_CYAN,
            width=2,
        )

        accent_top = card_top + 14
        accent_bottom = accent_top + 52
        accent_left = card_left + 16
        accent_right = accent_left + 52
        self.display.rectangle(
            accent_left,
            accent_top,
            accent_right,
            accent_bottom,
            fill=self.display.COLOR_CYAN,
        )

        self.display.text(
            self._card_icon(selected_card.title),
            accent_left + 14,
            accent_top + 12,
            color=self.display.COLOR_BLACK,
            font_size=24,
        )

        card_title = selected_card.title.upper()
        card_title_size = 22
        card_title_width, card_title_height = self.display.get_text_size(
            card_title,
            card_title_size,
        )
        card_title_x = (self.display.WIDTH - card_title_width) // 2
        card_title_y = accent_bottom + 20
        self.display.text(
            card_title,
            card_title_x,
            card_title_y,
            color=self.display.COLOR_WHITE,
            font_size=card_title_size,
        )

        subtitle = self._truncate(selected_card.subtitle, 32)
        subtitle_size = 14
        subtitle_width, subtitle_height = self.display.get_text_size(subtitle, subtitle_size)
        subtitle_x = (self.display.WIDTH - subtitle_width) // 2
        subtitle_y = card_title_y + card_title_height + 14
        self.display.text(
            subtitle,
            subtitle_x,
            subtitle_y,
            color=self.display.COLOR_GRAY,
            font_size=subtitle_size,
        )

        position_text = f"{self.selected_index + 1}/{len(cards)}"
        position_width, _ = self.display.get_text_size(position_text, 11)
        self.display.text(
            position_text,
            self.display.WIDTH - position_width - 18,
            title_y + 2,
            color=self.display.COLOR_GRAY,
            font_size=11,
        )

        dots_y = card_bottom - 22
        dots_width = 14 * len(cards)
        dots_x = (self.display.WIDTH - dots_width) // 2
        for index in range(len(cards)):
            color = self.display.COLOR_CYAN if index == self.selected_index else self.display.COLOR_GRAY
            self.display.circle(dots_x + (index * 14), dots_y, 3, fill=color)

        help_text = "Tap next | Double open"
        help_size = 10
        help_width, _ = self.display.get_text_size(help_text, help_size)
        help_x = (self.display.WIDTH - help_width) // 2
        self.display.text(
            help_text,
            help_x,
            self.display.HEIGHT - 15,
            color=self.display.COLOR_GRAY,
            font_size=help_size,
        )

        self.display.update()

    @staticmethod
    def _card_icon(title: str) -> str:
        """Return a minimal text icon for the selected hub card."""
        return {
            "Now Playing": "N",
            "Playlists": "P",
            "Calls": "C",
        }.get(title, "?")

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate a string for compact root-card rendering."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def on_advance(self, data=None) -> None:
        """Cycle to the next root card."""
        self.selected_index = (self.selected_index + 1) % len(self._cards())

    def on_select(self, data=None) -> None:
        """Open the selected root card."""
        card = self._cards()[self.selected_index]
        self.request_route("select", payload=card.title)

    def on_back(self, data=None) -> None:
        """Root hold gesture is a no-op."""
        return
