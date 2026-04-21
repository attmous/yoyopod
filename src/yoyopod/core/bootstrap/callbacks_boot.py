"""Boot-time callback and coordinator-event wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class CallbacksBoot:
    """Register runtime callbacks and coordinator event subscriptions."""

    def __init__(self, app: "YoyoPodApp", *, logger: Any) -> None:
        self.app = app
        self.logger = logger

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""

        self.logger.info("Setting up VoIP callbacks...")

        if not self.app.voip_manager:
            self.logger.warning("  VoIPManager not available, skipping callbacks")
            return

        call_coordinator = self.app.call_coordinator
        if call_coordinator is None:
            self.logger.warning("  CallCoordinator not available, skipping VoIP callbacks")
            return

        self.app.voip_manager.on_incoming_call(call_coordinator.handle_incoming_call)
        self.app.voip_manager.on_call_state_change(
            call_coordinator.handle_call_state_change
        )
        self.app.voip_manager.on_registration_change(
            call_coordinator.handle_registration_change
        )
        self.app.voip_manager.on_availability_change(
            call_coordinator.handle_availability_change
        )
        self.app.voip_manager.on_message_summary_change(
            self.app.voice_note_events.handle_voice_note_summary_changed
        )
        self.app.voip_manager.on_message_received(
            self.app.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_delivery_change(
            self.app.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_failure(
            self.app.voice_note_events.handle_voice_note_failure
        )
        self.app.voice_note_events.sync_talk_summary_context()
        self.app.voice_note_events.sync_active_voice_note_context()
        self.logger.info("  VoIP callbacks registered")

    def setup_music_callbacks(self) -> None:
        """Register music event callbacks."""

        self.logger.info("Setting up music callbacks...")

        if not self.app.music_backend:
            self.logger.warning("  MusicBackend not available, skipping callbacks")
            return

        playback_coordinator = self.app.playback_coordinator
        if playback_coordinator is None:
            self.logger.warning("  PlaybackCoordinator not available, skipping music callbacks")
            return

        self.app.music_backend.on_track_change(playback_coordinator.handle_track_change)
        self.app.music_backend.on_playback_state_change(
            playback_coordinator.handle_playback_state_change
        )
        if self.app.audio_volume_controller is not None:
            self.app.music_backend.on_connection_change(
                self.app.audio_volume_controller.sync_output_volume_on_music_connect
            )
        self.app.music_backend.on_connection_change(
            playback_coordinator.handle_availability_change
        )
        self.logger.info("  Music callbacks registered")

    def bind_coordinator_events(self) -> None:
        """Bind coordinator-level event handlers to the EventBus."""

        self.logger.info("Setting up event subscriptions...")
        call_coordinator = self.app.call_coordinator
        playback_coordinator = self.app.playback_coordinator
        power_coordinator = self.app.power_coordinator
        if (
            call_coordinator is None
            or playback_coordinator is None
            or power_coordinator is None
        ):
            self.logger.warning("  Coordinators not available, skipping event subscriptions")
            return

        call_coordinator.bind(self.app.event_bus)
        playback_coordinator.bind(self.app.event_bus)
        power_coordinator.bind(self.app.event_bus)
        self.logger.info("  Event subscriptions registered")
