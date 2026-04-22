"""
Playback-event coordination for YoyoPod.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from yoyopod.audio.music import LocalMusicService
from yoyopod.audio.music.models import Track
from yoyopod.coordinators.registry import AppRuntimeState, CoordinatorRuntime
from yoyopod.coordinators.screen import ScreenCoordinator
from yoyopod.core import EventBus
from yoyopod.core import (
    MusicAvailabilityChangedEvent,
    PlaybackStateChangedEvent,
    TrackChangedEvent,
)


@dataclass(frozen=True, slots=True)
class PlaybackSnapshot:
    """Coordinator-owned read-only playback state for UI consumers."""

    is_connected: bool
    track: Track | None
    playback_state: str
    time_position: float = 0.0


class PlaybackCoordinator:
    """Own playback event publishing, state sync, and screen refresh behavior."""

    def __init__(
        self,
        runtime: CoordinatorRuntime,
        screen_coordinator: ScreenCoordinator,
        local_music_service: LocalMusicService | None = None,
    ) -> None:
        self.runtime = runtime
        self.screen_coordinator = screen_coordinator
        self.local_music_service = local_music_service
        self._event_bus: EventBus | None = None
        self._bound = False

    def bind(self, event_bus: EventBus) -> None:
        """Bind typed event subscriptions once."""
        if self._bound:
            return

        self._event_bus = event_bus
        event_bus.subscribe(TrackChangedEvent, self._on_track_changed_event)
        event_bus.subscribe(PlaybackStateChangedEvent, self._on_playback_state_changed_event)
        event_bus.subscribe(MusicAvailabilityChangedEvent, self._on_availability_changed_event)
        self._bound = True

    def publish_track_change(self, track: Track | None) -> None:
        """Publish a music track change from the poller thread."""
        if self._event_bus is None:
            raise RuntimeError("PlaybackCoordinator is not bound to an EventBus")

        self._event_bus.publish(TrackChangedEvent(track=track))

    def publish_playback_state_change(self, playback_state: str) -> None:
        """Publish a playback-state change from the poller thread."""
        if self._event_bus is None:
            raise RuntimeError("PlaybackCoordinator is not bound to an EventBus")

        self._event_bus.publish(PlaybackStateChangedEvent(state=playback_state))

    def publish_availability_change(self, available: bool, reason: str = "") -> None:
        """Publish music-backend connectivity changes from worker threads."""
        if self._event_bus is None:
            raise RuntimeError("PlaybackCoordinator is not bound to an EventBus")

        self._event_bus.publish(MusicAvailabilityChangedEvent(available=available, reason=reason))

    def update_now_playing_if_needed(self) -> None:
        """Refresh the now-playing screen for periodic progress updates."""
        self.screen_coordinator.update_now_playing_if_needed()

    def get_playback_snapshot(self) -> PlaybackSnapshot:
        """Return the latest playback state through a narrow UI-safe snapshot."""
        music_backend = self.runtime.music_backend
        if music_backend is not None:
            is_connected = bool(music_backend.is_connected)
            if not is_connected:
                return PlaybackSnapshot(
                    is_connected=False,
                    track=None,
                    playback_state="stopped",
                    time_position=0.0,
                )

            return PlaybackSnapshot(
                is_connected=True,
                track=music_backend.get_current_track(),
                playback_state=music_backend.get_playback_state(),
                time_position=float(music_backend.get_time_position()),
            )

        context = self.runtime.context
        track = context.get_current_track() if context is not None else None
        playback_state = "stopped"
        if context is not None and context.media.playback.is_playing:
            playback_state = "playing"
        elif context is not None and context.media.playback.is_paused:
            playback_state = "paused"

        time_position = 0.0
        if track is not None and context is not None and track.length > 0:
            time_position = context.get_playback_progress() * track.length

        return PlaybackSnapshot(
            is_connected=True,
            track=track,
            playback_state=playback_state,
            time_position=time_position,
        )

    def get_playlist_count(self) -> int | None:
        """Return the current local playlist count for Listen entry points."""
        if self.local_music_service is None or not self.local_music_service.is_available:
            return None

        try:
            return self.local_music_service.playlist_count()
        except Exception as exc:
            logger.debug("Failed to read local playlist count: {}", exc)
            return None

    def toggle_playback(self) -> None:
        """Toggle playback through the backend or runtime fallback."""
        music_backend = self.runtime.music_backend
        if music_backend is not None:
            if not music_backend.is_connected:
                return
            if music_backend.get_playback_state() == "playing":
                music_backend.pause()
            else:
                music_backend.play()
            return

        if self.runtime.context is not None:
            self.runtime.context.toggle_playback()

    def previous_track(self) -> None:
        """Move to the previous track through the backend or runtime fallback."""
        music_backend = self.runtime.music_backend
        if music_backend is not None:
            if music_backend.is_connected:
                music_backend.previous_track()
            return

        if self.runtime.context is not None:
            self.runtime.context.previous_track()

    def next_track(self) -> None:
        """Move to the next track through the backend or runtime fallback."""
        music_backend = self.runtime.music_backend
        if music_backend is not None:
            if music_backend.is_connected:
                music_backend.next_track()
            return

        if self.runtime.context is not None:
            self.runtime.context.next_track()

    def on_enter_playing_with_voip(self) -> None:
        """Log entry into the playing-with-VoIP-ready state."""
        logger.info("Music playback resumed")

    def _on_track_changed_event(self, event: TrackChangedEvent) -> None:
        self.handle_track_change(event.track)

    def _on_playback_state_changed_event(self, event: PlaybackStateChangedEvent) -> None:
        self.handle_playback_state_change(event.state)

    def _on_availability_changed_event(self, event: MusicAvailabilityChangedEvent) -> None:
        self.handle_availability_change(event.available, event.reason)

    def handle_track_change(self, track: Track | None) -> None:
        """Handle track changes and refresh the active screen when needed."""
        if track:
            logger.info(f"Track changed: {track.name} - {track.get_artist_string()}")
            if self.local_music_service is not None:
                self.local_music_service.record_recent_track(track)
        else:
            logger.info("Playback stopped")
            if not self.runtime.call_fsm.is_active:
                self.runtime.music_fsm.transition("stop")
                self.runtime.sync_app_state("track_stopped")

        self.screen_coordinator.refresh_now_playing_screen()

    def handle_playback_state_change(self, playback_state: str) -> None:
        """Sync the playback FSM with music-backend state when not in a call."""
        logger.info(f"Playback state changed: {playback_state}")

        if self.runtime.call_fsm.is_active:
            logger.debug("In call, state machine managed by call logic")
            return

        if playback_state == "playing":
            self.runtime.music_fsm.transition("play")
        elif playback_state == "paused":
            self.runtime.music_fsm.transition("pause")
        elif playback_state == "stopped":
            self.runtime.music_fsm.transition("stop")

        state_change = self.runtime.sync_app_state(f"playback_{playback_state}")
        if state_change.entered(AppRuntimeState.MUSIC):
            logger.info("Music now playing")
        self.screen_coordinator.refresh_now_playing_screen()

    def handle_availability_change(self, available: bool, reason: str) -> None:
        """Keep playback state aligned with music-backend connectivity."""
        if available:
            logger.info(f"Music backend connected ({reason or 'ready'})")
            self.screen_coordinator.refresh_now_playing_screen()
            return

        logger.warning(f"Music backend unavailable ({reason or 'unknown'})")
        self.runtime.call_interruption_policy.clear()
        self.runtime.music_fsm.transition("stop")
        self.runtime.sync_app_state(f"music_{reason or 'unavailable'}")
        self.screen_coordinator.refresh_now_playing_screen()
