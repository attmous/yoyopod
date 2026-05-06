"""Live music-runtime orchestration for YoYoPod."""

from __future__ import annotations

from loguru import logger

from yoyopod_cli.pi.support.app_state import AppRuntimeState, AppStateRuntime
from yoyopod_cli.pi.support.music_backend import Track
from yoyopod_cli.pi.support.music_integration import LocalMusicService


class MusicRuntime:
    """Own playback runtime state sync and screen refresh behavior."""

    def __init__(
        self,
        runtime: AppStateRuntime,
        screen_manager: object | None,
        local_music_service: LocalMusicService | None = None,
    ) -> None:
        self.runtime = runtime
        self.screen_manager = screen_manager
        self.local_music_service = local_music_service

    def update_now_playing_if_needed(self) -> None:
        """Refresh the now-playing screen for periodic progress updates."""
        if self.screen_manager is None:
            return
        self.screen_manager.refresh_current_screen_for_visible_tick()

    def on_enter_playing_with_voip(self) -> None:
        """Log entry into the playing-with-VoIP-ready state."""
        logger.info("Music playing with VoIP ready")

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

        if self.screen_manager is not None:
            self.screen_manager.refresh_now_playing_screen()

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
        if state_change.entered(AppRuntimeState.PLAYING_WITH_VOIP):
            logger.info("Music playing with VoIP ready")
        if self.screen_manager is not None:
            self.screen_manager.refresh_now_playing_screen()

    def handle_availability_change(self, available: bool, reason: str) -> None:
        """Keep playback state aligned with music-backend connectivity."""
        if available:
            logger.info(f"Music backend connected ({reason or 'ready'})")
            self._refresh_visible_music_screen()
            return

        logger.warning(f"Music backend unavailable ({reason or 'unknown'})")
        self.runtime.call_interruption_policy.clear()
        self.runtime.music_fsm.transition("stop")
        self.runtime.sync_app_state(f"music_{reason or 'unavailable'}")
        self._refresh_visible_music_screen()

    def _refresh_visible_music_screen(self) -> None:
        """Refresh the visible music screen that depends on backend availability."""

        if self.screen_manager is None:
            return

        current_screen = getattr(self.screen_manager, "current_screen", None)
        current_route = getattr(current_screen, "route_name", None)
        if current_route in {"playlists", "now_playing"} and hasattr(
            self.screen_manager,
            "refresh_current_screen",
        ):
            self.screen_manager.refresh_current_screen()
            return

        self.screen_manager.refresh_now_playing_screen()
