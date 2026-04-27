"""Screen construction and registration during startup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod.backends.voice import (
    CloudWorkerSpeechToTextBackend,
    CloudWorkerTextToSpeechBackend,
)
from yoyopod.integrations.voice import (
    VoiceCommandExecutor,
    VoiceManager,
    VoiceRuntimeCoordinator,
    VoiceSettings,
    VoiceSettingsResolver,
)
from yoyopod.ui.input import InteractionProfile

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class ScreensBoot:
    """Build screen objects and resolve initial navigation state."""

    def __init__(self, app: "YoyoPodApp", *, logger: Any) -> None:
        self.app = app
        self.logger = logger

    def setup_screens(self) -> bool:
        """Create and register all screens."""
        self.logger.info("Setting up screens...")

        try:
            assert self.app.display is not None
            assert self.app.context is not None
            assert self.app.screen_manager is not None
            from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
            from yoyopod.ui.screens.music.playlist import PlaylistScreen
            from yoyopod.ui.screens.music.recent import RecentTracksScreen
            from yoyopod.ui.screens.navigation.ask import AskScreen
            from yoyopod.ui.screens.navigation.home import HomeScreen
            from yoyopod.ui.screens.navigation.hub import HubScreen
            from yoyopod.ui.screens.navigation.listen import ListenScreen
            from yoyopod.ui.screens.navigation.menu import MenuScreen
            from yoyopod.ui.screens.system.power import PowerScreen
            from yoyopod.ui.screens.voip.call_history import CallHistoryScreen
            from yoyopod.ui.screens.voip.contact_list import ContactListScreen
            from yoyopod.ui.screens.voip.in_call import InCallScreen
            from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen
            from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen
            from yoyopod.ui.screens.voip.quick_call import CallScreen
            from yoyopod.ui.screens.voip.talk_contact import TalkContactScreen
            from yoyopod.ui.screens.voip.voice_note import VoiceNoteScreen

            display = self.app.display
            context = self.app.context
            screen_manager = self.app.screen_manager
            volume_controller = self.app.audio_volume_controller
            if volume_controller is None:
                raise RuntimeError("Audio volume controller is not initialized")
            menu_items = ["Listen", "Talk", "Ask", "Setup"]
            self.app.hub_screen = HubScreen(display, context, app=self.app)
            self.app.menu_screen = MenuScreen(display, context, items=menu_items, app=self.app)
            self.app.home_screen = HomeScreen(display, context, app=self.app)
            self.app.listen_screen = ListenScreen(display, context, app=self.app)
            voice_cfg = (
                self.app.config_manager.get_voice_settings()
                if self.app.config_manager is not None
                else None
            )
            worker_cfg = getattr(voice_cfg, "worker", None) if voice_cfg is not None else None
            voice_worker_client = getattr(self.app, "voice_worker_client", None)
            voice_service_factory = None
            if (
                voice_cfg is not None
                and getattr(voice_cfg.assistant, "mode", "local") == "cloud"
                and voice_worker_client is not None
            ):

                def voice_service_factory(settings: VoiceSettings) -> VoiceManager:
                    stt_backend = (
                        CloudWorkerSpeechToTextBackend(client=voice_worker_client)
                        if settings.stt_backend == "cloud-worker"
                        else None
                    )
                    tts_backend = (
                        CloudWorkerTextToSpeechBackend(client=voice_worker_client)
                        if settings.tts_backend == "cloud-worker"
                        else None
                    )
                    return VoiceManager(
                        settings=settings,
                        stt_backend=stt_backend,
                        tts_backend=tts_backend,
                    )

            voice_settings_defaults = VoiceSettings()

            def ask_screen_summary() -> str:
                ask_screen = getattr(self.app, "ask_screen", None)
                summary_provider = getattr(ask_screen, "_screen_summary", None)
                if callable(summary_provider):
                    return str(summary_provider())
                return "You are on Ask. Ask a question, or go back to exit."

            self.app.voice_runtime = VoiceRuntimeCoordinator(
                context=context,
                settings_resolver=VoiceSettingsResolver(
                    context=context,
                    config_manager=self.app.config_manager,
                    settings_provider=lambda: VoiceSettings(
                        mode=(
                            getattr(voice_cfg.assistant, "mode", "local")
                            if voice_cfg is not None
                            else "local"
                        ),
                        commands_enabled=(
                            self.app.context.voice.commands_enabled
                            if self.app.context is not None
                            else True
                        ),
                        ai_requests_enabled=(
                            self.app.context.voice.ai_requests_enabled
                            if self.app.context is not None
                            else True
                        ),
                        screen_read_enabled=(
                            self.app.context.voice.screen_read_enabled
                            if self.app.context is not None
                            else False
                        ),
                        stt_enabled=(
                            self.app.context.voice.stt_enabled
                            if self.app.context is not None
                            else True
                        ),
                        tts_enabled=(
                            self.app.context.voice.tts_enabled
                            if self.app.context is not None
                            else True
                        ),
                        mic_muted=(
                            self.app.context.voice.mic_muted
                            if self.app.context is not None
                            else False
                        ),
                        output_volume=volume_controller.get_output_volume()
                        or (
                            self.app.context.voice.output_volume
                            if self.app.context is not None
                            else 50
                        ),
                        stt_backend=(
                            voice_cfg.assistant.stt_backend if voice_cfg is not None else "vosk"
                        ),
                        tts_backend=(
                            voice_cfg.assistant.tts_backend
                            if voice_cfg is not None
                            else "espeak-ng"
                        ),
                        vosk_model_path=(
                            voice_cfg.assistant.vosk_model_path
                            if voice_cfg is not None
                            else "models/vosk-model-small-en-us"
                        ),
                        vosk_model_keep_loaded=(
                            voice_cfg.assistant.vosk_model_keep_loaded
                            if voice_cfg is not None
                            else True
                        ),
                        speaker_device_id=(
                            self.app.context.voice.speaker_device_id
                            if self.app.context is not None
                            and self.app.context.voice.speaker_device_id is not None
                            else (
                                voice_cfg.audio.speaker_device_id.strip() or None
                                if voice_cfg is not None
                                else None
                            )
                        ),
                        capture_device_id=(
                            self.app.context.voice.capture_device_id
                            if self.app.context is not None
                            and self.app.context.voice.capture_device_id is not None
                            else (
                                voice_cfg.audio.capture_device_id.strip() or None
                                if voice_cfg is not None
                                else None
                            )
                        ),
                        sample_rate_hz=(
                            voice_cfg.assistant.sample_rate_hz if voice_cfg is not None else 16000
                        ),
                        record_seconds=(
                            voice_cfg.assistant.record_seconds if voice_cfg is not None else 4
                        ),
                        tts_rate_wpm=(
                            voice_cfg.assistant.tts_rate_wpm if voice_cfg is not None else 155
                        ),
                        tts_voice=voice_cfg.assistant.tts_voice if voice_cfg is not None else "en",
                        cloud_worker_enabled=(
                            getattr(worker_cfg, "enabled", False)
                            if worker_cfg is not None
                            else False
                        ),
                        cloud_worker_domain=(
                            getattr(worker_cfg, "domain", "voice")
                            if worker_cfg is not None
                            else "voice"
                        ),
                        cloud_worker_provider=(
                            getattr(worker_cfg, "provider", "mock")
                            if worker_cfg is not None
                            else "mock"
                        ),
                        cloud_worker_request_timeout_seconds=(
                            getattr(worker_cfg, "request_timeout_seconds", 12.0)
                            if worker_cfg is not None
                            else 12.0
                        ),
                        cloud_worker_max_audio_seconds=(
                            getattr(worker_cfg, "max_audio_seconds", 30.0)
                            if worker_cfg is not None
                            else 30.0
                        ),
                        cloud_worker_stt_model=(
                            getattr(worker_cfg, "stt_model", "gpt-4o-mini-transcribe")
                            if worker_cfg is not None
                            else "gpt-4o-mini-transcribe"
                        ),
                        cloud_worker_tts_model=(
                            getattr(worker_cfg, "tts_model", "gpt-4o-mini-tts")
                            if worker_cfg is not None
                            else "gpt-4o-mini-tts"
                        ),
                        cloud_worker_tts_voice=(
                            getattr(
                                worker_cfg,
                                "tts_voice",
                                voice_settings_defaults.cloud_worker_tts_voice,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_tts_voice
                        ),
                        cloud_worker_tts_instructions=(
                            getattr(
                                worker_cfg,
                                "tts_instructions",
                                voice_settings_defaults.cloud_worker_tts_instructions,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_tts_instructions
                        ),
                        cloud_worker_ask_model=(
                            getattr(
                                worker_cfg,
                                "ask_model",
                                voice_settings_defaults.cloud_worker_ask_model,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_ask_model
                        ),
                        cloud_worker_ask_timeout_seconds=(
                            getattr(
                                worker_cfg,
                                "ask_timeout_seconds",
                                voice_settings_defaults.cloud_worker_ask_timeout_seconds,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_ask_timeout_seconds
                        ),
                        cloud_worker_ask_max_history_turns=(
                            getattr(
                                worker_cfg,
                                "ask_max_history_turns",
                                voice_settings_defaults.cloud_worker_ask_max_history_turns,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_ask_max_history_turns
                        ),
                        cloud_worker_ask_max_response_chars=(
                            getattr(
                                worker_cfg,
                                "ask_max_response_chars",
                                voice_settings_defaults.cloud_worker_ask_max_response_chars,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_ask_max_response_chars
                        ),
                        cloud_worker_ask_instructions=(
                            getattr(
                                worker_cfg,
                                "ask_instructions",
                                voice_settings_defaults.cloud_worker_ask_instructions,
                            )
                            if worker_cfg is not None
                            else voice_settings_defaults.cloud_worker_ask_instructions
                        ),
                        local_feedback_enabled=(
                            getattr(worker_cfg, "local_feedback_enabled", True)
                            if worker_cfg is not None
                            else True
                        ),
                    ),
                ),
                command_executor=VoiceCommandExecutor(
                    context=context,
                    config_manager=self.app.config_manager,
                    people_directory=self.app.people_directory,
                    voip_manager=self.app.voip_manager,
                    volume_up_action=volume_controller.volume_up,
                    volume_down_action=volume_controller.volume_down,
                    mute_action=(
                        self.app.voip_manager.mute if self.app.voip_manager is not None else None
                    ),
                    unmute_action=(
                        self.app.voip_manager.unmute if self.app.voip_manager is not None else None
                    ),
                    play_music_action=(
                        self.app.local_music_service.shuffle_all
                        if self.app.local_music_service is not None
                        else None
                    ),
                    screen_summary_provider=ask_screen_summary,
                ),
                voice_service_factory=voice_service_factory,
                ask_client=voice_worker_client,
            )
            self.app.ask_screen = AskScreen(
                display,
                context,
                app=self.app,
            )
            self.app.power_screen = PowerScreen(
                display,
                context,
                app=self.app,
            )
            self.app.now_playing_screen = NowPlayingScreen(
                display,
                context,
                app=self.app,
            )
            self.app.playlist_screen = PlaylistScreen(display, context, app=self.app)
            self.app.recent_tracks_screen = RecentTracksScreen(display, context, app=self.app)
            self.app.call_screen = CallScreen(
                display,
                context,
                app=self.app,
            )
            self.app.call_history_screen = CallHistoryScreen(
                display,
                context,
                app=self.app,
            )
            self.app.talk_contact_screen = TalkContactScreen(
                display,
                context,
                app=self.app,
            )
            self.app.contact_list_screen = ContactListScreen(
                display,
                context,
                app=self.app,
            )
            self.app.voice_note_screen = VoiceNoteScreen(
                display,
                context,
                app=self.app,
            )
            self.app.incoming_call_screen = IncomingCallScreen(
                display,
                context,
                app=self.app,
                caller_address="",
                caller_name="Unknown",
            )
            self.app.outgoing_call_screen = OutgoingCallScreen(
                display,
                context,
                app=self.app,
                callee_address="",
                callee_name="Unknown",
            )
            self.app.in_call_screen = InCallScreen(
                display,
                context,
                app=self.app,
            )

            screen_manager.register_screen("hub", self.app.hub_screen)
            screen_manager.register_screen("home", self.app.home_screen)
            screen_manager.register_screen("menu", self.app.menu_screen)
            screen_manager.register_screen("listen", self.app.listen_screen)
            screen_manager.register_screen("ask", self.app.ask_screen)
            screen_manager.register_screen("power", self.app.power_screen)
            screen_manager.register_screen("now_playing", self.app.now_playing_screen)
            screen_manager.register_screen("playlists", self.app.playlist_screen)
            screen_manager.register_screen("recent_tracks", self.app.recent_tracks_screen)
            screen_manager.register_screen("call", self.app.call_screen)
            screen_manager.register_screen("talk_contact", self.app.talk_contact_screen)
            screen_manager.register_screen("call_history", self.app.call_history_screen)
            screen_manager.register_screen("contacts", self.app.contact_list_screen)
            screen_manager.register_screen("voice_note", self.app.voice_note_screen)
            screen_manager.register_screen("incoming_call", self.app.incoming_call_screen)
            screen_manager.register_screen("outgoing_call", self.app.outgoing_call_screen)
            screen_manager.register_screen("in_call", self.app.in_call_screen)
            self.logger.info("    - Whisplay root: hub")

            self.logger.info("  All screens registered")
            self.logger.info("    - Listen flow: listen, playlists, recent_tracks, now_playing")
            self.logger.info("    - Ask flow: ask")
            self.logger.info("    - Power screen: power")
            self.logger.info(
                "    - VoIP screens: call, talk_contact, call_history, contacts, voice_note, incoming_call, outgoing_call, in_call"
            )
            self.logger.info("    - Navigation: home, menu")

            initial_screen = self.get_initial_screen_name()
            screen_manager.push_screen(initial_screen)
            self.logger.info(f"  Initial route resolved to {initial_screen}")
            self.logger.info(f"  Initial screen confirmed as {initial_screen}")
            self.logger.info("  Initial screen set")
            return True
        except Exception:
            self.logger.exception("Failed to setup screens")
            return False

    def get_interaction_profile(self) -> InteractionProfile:
        """Return the active hardware interaction profile."""
        if self.app.input_manager is not None:
            return self.app.input_manager.interaction_profile
        if self.app.context is not None:
            return self.app.context.interaction_profile
        return InteractionProfile.STANDARD

    def get_initial_screen_name(self) -> str:
        """Return the root screen for the active interaction profile."""
        if self.get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return "hub"
        return "menu"
