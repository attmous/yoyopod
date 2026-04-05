"""Graffiti Buddy now-playing screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import INK, LISTEN, MUTED, SURFACE, draw_icon, render_footer, render_header, rounded_panel, text_fit

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class NowPlayingScreen(Screen):
    """Current playback screen styled for the new Listen mode."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        mopidy_client=None,
    ) -> None:
        super().__init__(display, context, "NowPlaying")
        self.mopidy_client = mopidy_client

    def render(self) -> None:
        """Render the now-playing view."""
        track_title, artist, progress, state_label, _is_playing = self._track_snapshot()

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Listen",
            show_time=False,
            show_mode_chip=False,
        )

        panel_top = content_top + 8
        panel_bottom = self.display.HEIGHT - 30
        rounded_panel(
            self.display,
            14,
            panel_top,
            self.display.WIDTH - 14,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=26,
            shadow=True,
        )

        draw_icon(self.display, "listen", (self.display.WIDTH // 2) - 24, panel_top + 16, 48, LISTEN.accent)

        state_width, _ = self.display.get_text_size(state_label, 10)
        rounded_panel(
            self.display,
            (self.display.WIDTH - state_width - 22) // 2,
            panel_top + 68,
            (self.display.WIDTH + state_width + 22) // 2,
            panel_top + 90,
            fill=LISTEN.accent_dim,
            outline=None,
            radius=12,
        )
        self.display.text(state_label, (self.display.WIDTH - state_width) // 2, panel_top + 74, color=LISTEN.accent, font_size=10)

        title_y = panel_top + 112
        display_title = text_fit(self.display, track_title, self.display.WIDTH - 56, 20)
        title_width, title_height = self.display.get_text_size(display_title, 20)
        self.display.text(display_title, (self.display.WIDTH - title_width) // 2, title_y, color=INK, font_size=20)

        artist_text = text_fit(self.display, artist, self.display.WIDTH - 64, 12)
        artist_width, _ = self.display.get_text_size(artist_text, 12)
        self.display.text(artist_text, (self.display.WIDTH - artist_width) // 2, title_y + title_height + 10, color=MUTED, font_size=12)

        progress_x = 28
        progress_y = panel_bottom - 44
        progress_width = self.display.WIDTH - 56
        self.display.rectangle(progress_x, progress_y, progress_x + progress_width, progress_y + 8, fill=(22, 25, 32))
        fill_width = max(0, min(progress_width, int(progress_width * progress)))
        if fill_width > 0:
            self.display.rectangle(progress_x, progress_y, progress_x + fill_width, progress_y + 8, fill=LISTEN.accent)

        hint = "Tap skip / Play / Hold back" if self.is_one_button_mode() else "A play | B back | X/Y tracks"
        render_footer(self.display, hint, mode="listen")
        self.display.update()

    def _track_snapshot(self) -> tuple[str, str, float, str, bool]:
        """Return current track, artist, progress and state label."""
        if self.mopidy_client:
            if not self.mopidy_client.is_connected:
                return ("Music Offline", "Trying to reconnect", 0.0, "OFFLINE", False)

            mopidy_track = self.mopidy_client.get_current_track()
            playback_state = self.mopidy_client.get_playback_state()
            if mopidy_track:
                progress = 0.0
                if mopidy_track.length > 0:
                    progress = self.mopidy_client.get_time_position() / mopidy_track.length
                state_label = "PLAYING" if playback_state == "playing" else "PAUSED" if playback_state == "paused" else "READY"
                return (
                    mopidy_track.name,
                    mopidy_track.get_artist_string() or "Unknown artist",
                    progress,
                    state_label,
                    playback_state == "playing",
                )

            return ("No Track Yet", "Pick a playlist to begin", 0.0, "READY", False)

        track = self.context.get_current_track() if self.context else None
        if track is None:
            return ("No Track Yet", "Pick a playlist to begin", 0.0, "READY", False)

        return (
            track.title,
            track.artist,
            self.context.get_playback_progress() if self.context else 0.0,
            "PLAYING" if self.context and self.context.playback.is_playing else "PAUSED",
            bool(self.context and self.context.playback.is_playing),
        )

    def _toggle_playback(self) -> None:
        """Toggle playback via Mopidy or the local app context."""
        if self.mopidy_client:
            if not self.mopidy_client.is_connected:
                return
            state = self.mopidy_client.get_playback_state()
            if state == "playing":
                self.mopidy_client.pause()
            else:
                self.mopidy_client.play()
            return

        if self.context:
            self.context.toggle_playback()

    def _previous_track(self) -> None:
        """Go to the previous track."""
        if self.mopidy_client:
            if self.mopidy_client.is_connected:
                self.mopidy_client.previous_track()
            return
        if self.context:
            self.context.previous_track()

    def _next_track(self) -> None:
        """Go to the next track."""
        if self.mopidy_client:
            if self.mopidy_client.is_connected:
                self.mopidy_client.next_track()
            return
        if self.context:
            self.context.next_track()

    def on_select(self, data=None) -> None:
        """Toggle play/pause."""
        self._toggle_playback()

    def on_play_pause(self, data=None) -> None:
        """Toggle play/pause from a dedicated action."""
        self._toggle_playback()

    def on_back(self, data=None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance to the next track in one-button mode."""
        self._next_track()

    def on_up(self, data=None) -> None:
        """Go to the previous track."""
        self._previous_track()

    def on_prev_track(self, data=None) -> None:
        """Go to the previous track from a dedicated media action."""
        self._previous_track()

    def on_down(self, data=None) -> None:
        """Go to the next track."""
        self._next_track()

    def on_next_track(self, data=None) -> None:
        """Go to the next track from a dedicated media action."""
        self._next_track()
