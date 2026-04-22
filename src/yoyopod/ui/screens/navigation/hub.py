"""Graffiti Buddy root hub screen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import LvglScreen
from yoyopod.ui.screens.navigation.lvgl import LvglHubView
from yoyopod.ui.screens.navigation.hub_pil_view import render_hub_pil
from yoyopod.ui.screens.theme import (
    BACKGROUND,
    format_battery_compact,
    mix,
    text_fit,
    theme_for,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.audio.music.models import Track


@dataclass(frozen=True, slots=True)
class HubCard:
    """One primary root action."""

    title: str
    subtitle: str
    mode: str
    icon: str


@dataclass(frozen=True, slots=True)
class WatchFace:
    """Static metadata for a supported watch face."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class HubListenSnapshot:
    """Read-only Listen summary used by the hub subtitle provider."""

    is_connected: bool
    track: "Track | None" = None
    playback_state: str = "stopped"
    playlist_count: int | None = None


def build_hub_listen_subtitle_provider(
    display: Display,
    *,
    snapshot_provider: Callable[[], HubListenSnapshot] | None = None,
) -> Callable[[], str]:
    """Build the compact Listen subtitle provider for the hub."""

    def provider() -> str:
        if snapshot_provider is None:
            return ""

        snapshot = snapshot_provider()
        if not snapshot.is_connected:
            return "Reconnect"

        track = snapshot.track
        if track is None:
            if snapshot.playlist_count:
                label = "playlist" if snapshot.playlist_count == 1 else "playlists"
                return f"{snapshot.playlist_count} {label}"
            return "On-device music"

        artist = track.get_artist_string() or "Unknown"
        artist = artist.split(",")[0]
        if snapshot.playback_state == "playing":
            return text_fit(display, f"Playing {artist}", 134, 12)
        if snapshot.playback_state == "paused":
            return "Paused"
        return "On-device music"

    return provider


class HubScreen(LvglScreen):
    """Carousel-style root screen for the one-button Whisplay flow."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        listen_subtitle_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(display, context, "ActionHub")
        self._listen_subtitle_provider = (
            listen_subtitle_provider or build_hub_listen_subtitle_provider(display)
        )
        self.selected_index = 0
        self.watch_faces = [
            WatchFace(key="minimal_digital", label="Minimal digital"),
            WatchFace(key="analog", label="Analog-style"),
            WatchFace(key="activity", label="Activity-style"),
        ]
        self.active_watch_face_index = 0
        self.watch_picker_active = False
        self.watch_picker_index = 0

    def enter(self) -> None:
        """Refresh lightweight summaries when the hub becomes active."""
        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL Hub view alive across transitions."""
        super().exit()

    def _create_lvgl_view(self, ui_backend: object) -> LvglHubView:
        """Build the retained LVGL view for this screen."""
        return LvglHubView(self, ui_backend)

    def cards(self) -> list[HubCard]:
        """Build the live root-card list."""
        cards = [
            HubCard("Listen", self._listen_subtitle(), "listen", "listen"),
            HubCard("Talk", self._talk_subtitle(), "talk", "talk"),
            HubCard("Ask", "Safe questions", "ask", "ask"),
            HubCard("Setup", self._setup_subtitle(), "setup", "setup"),
        ]
        if self.is_one_button_mode():
            watch_face_name = (
                self.picker_watch_face().label
                if self.watch_picker_active
                else self.active_watch_face().label
            )
            cards.insert(0, HubCard("Watch", watch_face_name, "setup", "clock"))
        return cards

    def selected_card(self) -> HubCard:
        """Return the currently highlighted card with wraparound safety."""
        cards = self.cards()
        self.selected_index %= len(cards)
        return cards[self.selected_index]

    def active_watch_face(self) -> WatchFace:
        """Return the currently selected watch-face metadata."""
        return self.watch_faces[self.active_watch_face_index]

    def picker_watch_face(self) -> WatchFace:
        """Return the preview face while in watch-face picker mode."""
        return self.watch_faces[self.watch_picker_index]

    def watch_timestamp(self) -> datetime:
        """Return the wall-clock timestamp used by watch-face rendering."""
        return datetime.now()

    def watch_battery_percent(self) -> int:
        """Return normalized battery percent for watch-face chrome."""
        if self.context is None:
            return 100
        return max(0, min(100, int(round(self.context.power.battery_percent))))

    def watch_is_charging(self) -> bool:
        """Return True when power telemetry indicates charging."""
        if self.context is None:
            return False
        return bool(self.context.power.battery_charging)

    def _listen_subtitle(self) -> str:
        """Return the compact Listen card subtitle."""
        return self._listen_subtitle_provider()

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
        if self._sync_lvgl_view():
            return
        render_hub_pil(self)

    def on_advance(self, data=None) -> None:
        """Cycle to the next card."""
        if self.watch_picker_active:
            self.watch_picker_index = (self.watch_picker_index + 1) % len(self.watch_faces)
            return
        self.selected_index = (self.selected_index + 1) % len(self.cards())

    def on_select(self, data=None) -> None:
        """Open the selected root card."""
        selected = self.selected_card()
        if selected.title != "Watch":
            self.request_route("select", payload=selected.title)
            return
        if not self.watch_picker_active:
            self.watch_picker_active = True
            self.watch_picker_index = self.active_watch_face_index
            return
        self.active_watch_face_index = self.watch_picker_index
        self.watch_picker_active = False

    def on_back(self, data=None) -> None:
        """Open Ask in quick-command mode (hold-to-ask shortcut)."""
        if self.watch_picker_active:
            self.watch_picker_active = False
            return
        if self.screen_manager is not None:
            ask_screen = self.screen_manager.screens.get("ask")
            if ask_screen is not None and hasattr(ask_screen, "set_quick_command"):
                ask_screen.set_quick_command(True)
        self.request_route("hold_ask")
