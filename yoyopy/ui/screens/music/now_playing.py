"""NowPlayingScreen - Display currently playing track."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class NowPlayingScreen(Screen):
    """
    Now Playing screen for audio playback.

    Displays current track information, playback controls,
    and progress indicator.

    Button mapping:
    - Button A: Toggle play/pause
    - Button B: Go back to menu
    - Button X: Previous track
    - Button Y: Next track
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        mopidy_client=None  # Optional MopidyClient for Spotify streaming
    ) -> None:
        """
        Initialize now playing screen.

        Args:
            display: Display controller
            context: Application context
            mopidy_client: Optional MopidyClient for streaming
        """
        super().__init__(display, context, "NowPlaying")
        self.mopidy_client = mopidy_client

    def render(self) -> None:
        """Render the now playing screen."""
        # Get track info from Mopidy or context
        if self.mopidy_client:
            if not self.mopidy_client.is_connected:
                track_title = "Music Offline"
                artist = "Reconnecting..."
                progress = 0.0
                is_playing = False
            else:
                # Get track from Mopidy
                mopidy_track = self.mopidy_client.get_current_track()
                if mopidy_track:
                    track_title = mopidy_track.name
                    artist = mopidy_track.get_artist_string()
                    # Calculate progress from position and track length
                    if mopidy_track.length > 0:
                        position_ms = self.mopidy_client.get_time_position()
                        progress = position_ms / mopidy_track.length
                    else:
                        progress = 0.0
                    is_playing = self.mopidy_client.get_playback_state() == "playing"
                else:
                    track_title = "No Track"
                    artist = "Unknown Artist"
                    progress = 0.0
                    is_playing = False
        else:
            # Fallback to context for local tracks
            track = self.context.get_current_track() if self.context else None
            track_title = track.title if track else "No Track"
            artist = track.artist if track else "Unknown Artist"
            progress = self.context.get_playback_progress() if self.context else 0.0
            is_playing = self.context.playback.is_playing if self.context else False

        # Clear display
        self.display.clear(self.display.COLOR_BLACK)

        # Draw status bar
        current_time = datetime.now().strftime("%H:%M")
        battery = self.context.battery_percent if self.context else 100
        signal = self.context.signal_strength if self.context else 4

        self.display.status_bar(
            time_str=current_time,
            battery_percent=battery,
            signal_strength=signal
        )

        # Draw "Now Playing" label
        label_y = self.display.STATUS_BAR_HEIGHT + 15
        self.display.text(
            "NOW PLAYING",
            20,
            label_y,
            color=self.display.COLOR_GRAY,
            font_size=12
        )

        # Draw album art placeholder (square)
        art_size = 100
        art_x = (self.display.WIDTH - art_size) // 2
        art_y = label_y + 30

        # Gradient-like effect with multiple rectangles
        for i in range(0, art_size // 2, 20):
            gray_value = 40 + i
            color = (gray_value, gray_value, gray_value)
            self.display.rectangle(
                art_x + i, art_y + i,
                art_x + art_size - i, art_y + art_size - i,
                fill=color
            )

        # Draw music note icon (simple representation)
        note_x = art_x + art_size // 2 - 10
        note_y = art_y + art_size // 2 - 15
        self.display.circle(
            note_x, note_y + 20,
            8,
            fill=self.display.COLOR_CYAN
        )
        self.display.rectangle(
            note_x + 7, note_y,
            note_x + 10, note_y + 20,
            fill=self.display.COLOR_CYAN
        )

        # Draw track title
        title_y = art_y + art_size + 20
        title_size = 18

        # Truncate if too long (adjust for portrait vs landscape)
        max_title_length = 15 if self.display.is_portrait() else 20
        display_title = track_title[:max_title_length]
        if len(track_title) > max_title_length:
            display_title += "..."

        title_width, _ = self.display.get_text_size(display_title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2

        self.display.text(
            display_title,
            title_x,
            title_y,
            color=self.display.COLOR_WHITE,
            font_size=title_size
        )

        # Draw artist name
        artist_y = title_y + 25
        artist_size = 14

        max_artist_length = 18 if self.display.is_portrait() else 25
        display_artist = artist[:max_artist_length]
        if len(artist) > max_artist_length:
            display_artist += "..."

        artist_width, _ = self.display.get_text_size(display_artist, artist_size)
        artist_x = (self.display.WIDTH - artist_width) // 2

        self.display.text(
            display_artist,
            artist_x,
            artist_y,
            color=self.display.COLOR_GRAY,
            font_size=artist_size
        )

        # Draw progress bar
        progress_y = self.display.HEIGHT - 35
        progress_width = self.display.WIDTH - 40
        progress_height = 6
        progress_x = 20

        # Background
        self.display.rectangle(
            progress_x, progress_y,
            progress_x + progress_width, progress_y + progress_height,
            fill=self.display.COLOR_DARK_GRAY
        )

        # Progress
        filled_width = int(progress_width * progress)
        if filled_width > 0:
            self.display.rectangle(
                progress_x, progress_y,
                progress_x + filled_width, progress_y + progress_height,
                fill=self.display.COLOR_CYAN
            )

        # Draw play/pause indicator
        control_y = self.display.HEIGHT - 20
        if is_playing:
            # Play symbol (simple triangle)
            play_x = self.display.WIDTH // 2 - 5
            self.display.text(
                "▶",
                play_x,
                control_y,
                color=self.display.COLOR_GREEN,
                font_size=12
            )
        else:
            # Pause symbol
            pause_x = self.display.WIDTH // 2 - 5
            self.display.rectangle(
                pause_x, control_y,
                pause_x + 3, control_y + 10,
                fill=self.display.COLOR_YELLOW
            )
            self.display.rectangle(
                pause_x + 7, control_y,
                pause_x + 10, control_y + 10,
                fill=self.display.COLOR_YELLOW
            )

        if self.is_one_button_mode():
            help_text = "Tap next | Double play | Hold back"
            help_width, _ = self.display.get_text_size(help_text, 9)
            self.display.text(
                help_text,
                (self.display.WIDTH - help_width) // 2,
                self.display.HEIGHT - 10,
                color=self.display.COLOR_GRAY,
                font_size=9
            )

        # Update display
        self.display.update()

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
        elif self.context:
            self.context.toggle_playback()

    def _previous_track(self) -> None:
        """Go to the previous track."""
        if self.mopidy_client:
            if not self.mopidy_client.is_connected:
                return
            self.mopidy_client.previous_track()
        elif self.context:
            self.context.previous_track()

    def _next_track(self) -> None:
        """Go to the next track."""
        if self.mopidy_client:
            if not self.mopidy_client.is_connected:
                return
            self.mopidy_client.next_track()
        elif self.context:
            self.context.next_track()

    def on_select(self, data=None) -> None:
        """Toggle play/pause."""
        self._toggle_playback()

    def on_play_pause(self, data=None) -> None:
        """Toggle play/pause from a dedicated media action."""
        self._toggle_playback()

    def on_back(self, data=None) -> None:
        """Go back to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance to the next track for one-button navigation."""
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
