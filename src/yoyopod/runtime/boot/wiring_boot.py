"""Runtime coordinator and callback wiring during startup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod.coordinators import (
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class WiringBoot:
    """Bind runtime coordinators and manager callbacks."""

    def __init__(self, app: "YoyoPodApp", *, logger: Any) -> None:
        self.app = app
        self.logger = logger

    def refresh_talk_summary(self) -> None:
        """Refresh Talk summary data exposed through the shared app context."""
        if self.app.context is None or self.app.call_history_store is None:
            return

        self.app.context.update_call_summary(
            missed_calls=self.app.call_history_store.missed_count(),
            recent_calls=self.app.call_history_store.recent_preview(),
        )
        if self.app.voip_manager is not None:
            self.app.context.update_voice_note_summary(
                unread_voice_notes=self.app.voip_manager.unread_voice_note_count(),
                latest_voice_note_by_contact=self.app.voip_manager.latest_voice_note_summary(),
            )

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""
        self.logger.info("Setting up VoIP callbacks...")

        if not self.app.voip_manager:
            self.logger.warning("  VoIPManager not available, skipping callbacks")
            return

        self.ensure_coordinators()
        assert self.app.call_coordinator is not None
        self.app.voip_manager.on_incoming_call(self.app.call_coordinator.publish_incoming_call)
        self.app.voip_manager.on_call_state_change(
            self.app.call_coordinator.publish_call_state_events
        )
        self.app.voip_manager.on_registration_change(
            self.app.call_coordinator.publish_registration_change
        )
        self.app.voip_manager.on_availability_change(
            self.app.call_coordinator.publish_availability_change
        )
        self.app.voip_manager.on_message_summary_change(
            self.app.event_wiring.voice_note_events.handle_voice_note_summary_changed
        )
        self.app.voip_manager.on_message_received(
            self.app.event_wiring.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_delivery_change(
            self.app.event_wiring.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_failure(
            self.app.event_wiring.voice_note_events.handle_voice_note_failure
        )
        self.refresh_talk_summary()
        self.app.event_wiring.voice_note_events.sync_active_voice_note_context()
        self.logger.info("  VoIP callbacks registered")

    def setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        self.logger.info("Setting up music callbacks...")

        if not self.app.music_backend:
            self.logger.warning("  MusicBackend not available, skipping callbacks")
            return

        self.ensure_coordinators()
        assert self.app.playback_coordinator is not None
        self.app.music_backend.on_track_change(self.app.playback_coordinator.publish_track_change)
        self.app.music_backend.on_playback_state_change(
            self.app.playback_coordinator.publish_playback_state_change
        )
        if self.app.audio_volume_controller is not None:
            self.app.music_backend.on_connection_change(
                self.app.audio_volume_controller.sync_output_volume_on_music_connect
            )
        self.app.music_backend.on_connection_change(
            self.app.playback_coordinator.publish_availability_change
        )
        self.logger.info("  Music callbacks registered")

    def bind_coordinator_events(self) -> None:
        """Bind coordinator-level event handlers to the EventBus."""
        self.logger.info("Setting up event subscriptions...")
        self.ensure_coordinators()
        assert self.app.call_coordinator is not None
        assert self.app.playback_coordinator is not None
        assert self.app.power_coordinator is not None
        self.app.call_coordinator.bind(self.app.event_bus)
        self.app.playback_coordinator.bind(self.app.event_bus)
        self.app.power_coordinator.bind(self.app.event_bus)
        self.logger.info("  Event subscriptions registered")

    def setup_event_subscriptions(self) -> None:
        """Backward-compatible alias for coordinator event binding."""
        self.bind_coordinator_events()

    def ensure_coordinators(self) -> None:
        """Build coordinator helpers around the initialized runtime."""
        if self.app.coordinator_runtime is not None:
            return

        assert self.app.music_fsm is not None
        assert self.app.call_fsm is not None
        assert self.app.call_interruption_policy is not None
        assert self.app.context is not None
        self.app.coordinator_runtime = CoordinatorRuntime(
            music_fsm=self.app.music_fsm,
            call_fsm=self.app.call_fsm,
            call_interruption_policy=self.app.call_interruption_policy,
            screen_manager=self.app.screen_manager,
            music_backend=self.app.music_backend,
            power_manager=self.app.power_manager,
            config_manager=self.app.config_manager,
            context=self.app.context,
            ui_state=self.app._ui_state,
            voip_ready=self.app._voip_registered,
        )
        self.app.screen_coordinator = ScreenCoordinator(self.app.coordinator_runtime)
        self.app.call_coordinator = CallCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            auto_resume_after_call=self.app.auto_resume_after_call,
            call_history_store=self.app.call_history_store,
            initial_voip_registered=self.app._voip_registered,
        )
        self.app.playback_coordinator = PlaybackCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            local_music_service=self.app.local_music_service,
        )
        self.app.power_coordinator = PowerCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            context=self.app.context,
            cloud_manager=self.app.cloud_manager,
        )
        if self.app.screen_manager is not None:
            self.app.screen_manager.on_screen_changed = self.app._handle_screen_changed
            current_screen = self.app.screen_manager.get_current_screen()
            current_route_name = current_screen.route_name if current_screen is not None else None
            self.app._handle_screen_changed(current_route_name)
