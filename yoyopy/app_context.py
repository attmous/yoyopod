"""
Application context for YoyoPod.

Maintains shared state across the application including
current playlist, playback status, volume, and user settings.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pathlib import Path
from loguru import logger

from yoyopy.ui.input.hal import InteractionProfile

if TYPE_CHECKING:
    from yoyopy.audio.audio_manager import AudioManager


@dataclass
class Track:
    """Represents a single audio track."""
    title: str
    artist: str
    duration: float = 0.0  # Duration in seconds
    file_path: Optional[Path] = None
    stream_url: Optional[str] = None
    album: Optional[str] = None
    artwork_url: Optional[str] = None


@dataclass
class Playlist:
    """Represents a playlist of tracks."""
    name: str
    tracks: List[Track] = field(default_factory=list)
    current_index: int = 0

    def current_track(self) -> Optional[Track]:
        """Get the currently playing track."""
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def next_track(self) -> Optional[Track]:
        """Move to next track and return it."""
        if self.current_index < len(self.tracks) - 1:
            self.current_index += 1
            return self.current_track()
        return None

    def previous_track(self) -> Optional[Track]:
        """Move to previous track and return it."""
        if self.current_index > 0:
            self.current_index -= 1
            return self.current_track()
        return None

    def has_next(self) -> bool:
        """Check if there's a next track."""
        return self.current_index < len(self.tracks) - 1

    def has_previous(self) -> bool:
        """Check if there's a previous track."""
        return self.current_index > 0


@dataclass
class PlaybackState:
    """Current playback state."""
    is_playing: bool = False
    is_paused: bool = False
    is_stopped: bool = True
    position: float = 0.0  # Current position in seconds
    volume: int = 50  # Volume 0-100
    is_muted: bool = False


class AppContext:
    """
    Central application context.

    Maintains all shared state including playback, playlists,
    user settings, and system status.
    """

    def __init__(
        self,
        audio_manager: Optional['AudioManager'] = None,
        interaction_profile: InteractionProfile = InteractionProfile.STANDARD,
    ) -> None:
        """
        Initialize application context.

        Args:
            audio_manager: Optional AudioManager instance for actual playback
        """
        # Playback state
        self.playback = PlaybackState()

        # Audio manager (optional, for actual audio playback)
        self.audio_manager = audio_manager
        self.interaction_profile = interaction_profile

        # Current playlist
        self.current_playlist: Optional[Playlist] = None

        # Available playlists
        self.playlists: Dict[str, Playlist] = {}

        # User settings
        self.settings = {
            "brightness": 100,
            "auto_sleep_minutes": 30,
            "parental_controls_enabled": False,
            "max_volume": 80,  # Parental control default
        }

        # System status
        self.battery_percent: int = 100
        self.signal_strength: int = 4  # 0-4 bars
        self.is_connected: bool = False
        self.connection_type: str = "none"  # wifi, 4g, none

        # Navigation history for back button
        self.navigation_history: List[str] = []

        logger.info("AppContext initialized")

    def set_playlist(self, playlist: Playlist) -> None:
        """
        Set the current playlist.

        Args:
            playlist: Playlist to set as current
        """
        self.current_playlist = playlist
        logger.info(f"Playlist set: {playlist.name} ({len(playlist.tracks)} tracks)")

    def get_current_track(self) -> Optional[Track]:
        """Get the currently playing/selected track."""
        if self.current_playlist:
            return self.current_playlist.current_track()
        return None

    def play(self) -> bool:
        """
        Start playback.

        Returns:
            True if playback started, False otherwise
        """
        if not self.current_playlist or not self.current_playlist.current_track():
            logger.warning("Cannot play: no track selected")
            return False

        self.playback.is_playing = True
        self.playback.is_paused = False
        self.playback.is_stopped = False
        logger.info(f"Playing: {self.get_current_track().title}")
        return True

    def pause(self) -> None:
        """Pause playback."""
        if self.playback.is_playing:
            self.playback.is_playing = False
            self.playback.is_paused = True
            logger.info("Playback paused")

    def resume(self) -> None:
        """Resume playback."""
        if self.playback.is_paused:
            self.playback.is_playing = True
            self.playback.is_paused = False
            logger.info("Playback resumed")

    def stop(self) -> None:
        """Stop playback."""
        self.playback.is_playing = False
        self.playback.is_paused = False
        self.playback.is_stopped = True
        self.playback.position = 0.0
        logger.info("Playback stopped")

    def toggle_playback(self) -> bool:
        """
        Toggle between play and pause.

        Returns:
            True if now playing, False if paused
        """
        if self.playback.is_playing:
            self.pause()
            return False
        elif self.playback.is_paused or self.playback.is_stopped:
            if self.playback.is_stopped:
                self.play()
            else:
                self.resume()
            return True
        return False

    def set_volume(self, volume: int) -> None:
        """
        Set playback volume.

        Args:
            volume: Volume level (0-100)
        """
        max_volume = self.settings.get("max_volume", 100)
        volume = max(0, min(volume, max_volume))
        self.playback.volume = volume

        # Sync with audio manager if available
        if self.audio_manager:
            self.audio_manager.volume = volume

        logger.debug(f"Volume set to {volume}")

    def volume_up(self, step: int = 5) -> int:
        """
        Increase volume.

        Args:
            step: Amount to increase (default 5)

        Returns:
            New volume level
        """
        new_volume = self.playback.volume + step
        self.set_volume(new_volume)
        return self.playback.volume

    def volume_down(self, step: int = 5) -> int:
        """
        Decrease volume.

        Args:
            step: Amount to decrease (default 5)

        Returns:
            New volume level
        """
        new_volume = self.playback.volume - step
        self.set_volume(new_volume)
        return self.playback.volume

    def next_track(self) -> Optional[Track]:
        """Skip to next track."""
        if self.current_playlist:
            track = self.current_playlist.next_track()
            if track:
                logger.info(f"Next track: {track.title}")
                if self.playback.is_playing:
                    self.play()
            return track
        return None

    def previous_track(self) -> Optional[Track]:
        """Go to previous track."""
        if self.current_playlist:
            track = self.current_playlist.previous_track()
            if track:
                logger.info(f"Previous track: {track.title}")
                if self.playback.is_playing:
                    self.play()
            return track
        return None

    def create_demo_playlist(self) -> Playlist:
        """Create a demo playlist for testing."""
        demo_tracks = [
            Track(
                title="The Adventure Begins",
                artist="Story Time Stories",
                duration=180.0,
            ),
            Track(
                title="Journey to the Mountains",
                artist="Story Time Stories",
                duration=240.0,
            ),
            Track(
                title="The Magic Forest",
                artist="Bedtime Tales",
                duration=200.0,
            ),
            Track(
                title="Ocean Waves & Dreams",
                artist="Relaxing Sounds",
                duration=300.0,
            ),
        ]

        playlist = Playlist(name="Demo Playlist", tracks=demo_tracks)
        self.playlists["demo"] = playlist
        logger.info(f"Created demo playlist with {len(demo_tracks)} tracks")
        return playlist

    def get_playback_progress(self) -> float:
        """
        Get current playback progress as percentage.

        Returns:
            Progress from 0.0 to 1.0
        """
        track = self.get_current_track()
        if track and track.duration > 0:
            return min(1.0, self.playback.position / track.duration)
        return 0.0

    def update_system_status(
        self,
        battery: Optional[int] = None,
        signal: Optional[int] = None,
        connected: Optional[bool] = None
    ) -> None:
        """
        Update system status information.

        Args:
            battery: Battery percentage (0-100)
            signal: Signal strength (0-4)
            connected: Connection status
        """
        if battery is not None:
            self.battery_percent = max(0, min(100, battery))
        if signal is not None:
            self.signal_strength = max(0, min(4, signal))
        if connected is not None:
            self.is_connected = connected
