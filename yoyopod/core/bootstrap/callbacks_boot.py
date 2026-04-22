"""Boot-time backend callback wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class CallbacksBoot:
    """Register runtime backend callbacks."""

    def __init__(self, app: "YoyoPodApp", *, logger: Any) -> None:
        self.app = app
        self.logger = logger

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""

        self.logger.info("Setting up VoIP callbacks...")

        if not self.app.voip_manager:
            self.logger.warning("  VoIPManager not available, skipping callbacks")
            return

        call_runtime = self.app.call_runtime
        if call_runtime is None:
            self.logger.warning("  Call runtime not available, skipping VoIP callbacks")
            return

        self.app.voip_manager.on_incoming_call(call_runtime.handle_incoming_call)
        self.app.voip_manager.on_call_state_change(
            call_runtime.handle_call_state_change
        )
        self.app.voip_manager.on_registration_change(
            call_runtime.handle_registration_change
        )
        self.app.voip_manager.on_availability_change(
            call_runtime.handle_availability_change
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

        music_runtime = self.app.music_runtime
        if music_runtime is None:
            self.logger.warning("  Music runtime not available, skipping music callbacks")
            return

        self.app.music_backend.on_track_change(
            lambda track: self.app.scheduler.run_on_main(
                lambda: music_runtime.handle_track_change(track)
            )
        )
        self.app.music_backend.on_playback_state_change(
            lambda playback_state: self.app.scheduler.run_on_main(
                lambda: music_runtime.handle_playback_state_change(playback_state)
            )
        )
        if self.app.audio_volume_controller is not None:
            self.app.music_backend.on_connection_change(
                lambda available, reason: self.app.scheduler.run_on_main(
                    lambda: self.app.audio_volume_controller.sync_output_volume_on_music_connect(
                        available,
                        reason,
                    )
                )
            )
        self.app.music_backend.on_connection_change(
            lambda available, reason: self.app.scheduler.run_on_main(
                lambda: music_runtime.handle_availability_change(
                    available,
                    reason,
                )
            )
        )
        self.logger.info("  Music callbacks registered")
