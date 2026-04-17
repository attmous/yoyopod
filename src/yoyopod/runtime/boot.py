"""Boot-time composition helpers for the first runtime extraction pass."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod.audio import (
    LocalMusicService,
    MpvBackend,
    MusicConfig,
    OutputVolumeController,
    RecentTrackHistoryStore,
)
from yoyopod.config import ConfigManager
from yoyopod.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)
from yoyopod.device import AudioDeviceCatalog
from yoyopod.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopod.network import NetworkManager
from yoyopod.people import PeopleDirectory
from yoyopod.power import PowerManager
from yoyopod.runtime.voice import (
    VoiceCommandExecutor,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)
from yoyopod.ui.display import Display
from yoyopod.ui.input import InteractionProfile, get_input_manager
from yoyopod.ui.lvgl_binding import LvglInputBridge
from yoyopod.ui.screens import (
    AskScreen,
    CallHistoryScreen,
    CallScreen,
    ContactListScreen,
    HubScreen,
    HomeScreen,
    InCallScreen,
    IncomingCallScreen,
    ListenScreen,
    MenuScreen,
    NowPlayingScreen,
    OutgoingCallScreen,
    PlaylistScreen,
    PowerScreen,
    RecentTracksScreen,
    ScreenManager,
    TalkContactScreen,
    VoiceNoteScreen,
)
from yoyopod.ui.screens.music.now_playing import (
    build_now_playing_actions,
    build_now_playing_state_provider,
)
from yoyopod.ui.screens.system.power import (
    build_power_screen_actions,
    build_power_screen_state_provider,
)
from yoyopod.ui.screens.voip.voice_note import (
    build_voice_note_actions,
    build_voice_note_state_provider,
)
from yoyopod.voice import VoiceSettings
from yoyopod.communication import CallHistoryStore, VoIPConfig, VoIPManager

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class RuntimeBootService:
    """Own the boot-time composition of the application runtime."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def setup(self) -> bool:
        """Initialize all components and register callbacks."""
        try:
            if not self.load_configuration():
                logger.error("Failed to load configuration")
                return False

            if not self.init_core_components():
                logger.error("Failed to initialize core components")
                return False

            if not self.init_managers():
                logger.error("Failed to initialize managers")
                return False

            if not self.setup_screens():
                logger.error("Failed to setup screens")
                return False

            self.ensure_coordinators()
            assert self.app.coordinator_runtime is not None
            self.app.coordinator_runtime.set_ui_state(self.app._ui_state, trigger="initial_screen")
            self.setup_event_subscriptions()
            self.setup_voip_callbacks()
            self.setup_music_callbacks()
            self.app.shutdown_service.register_power_shutdown_hooks()
            self.app.power_runtime.poll_status(force=True, now=time.monotonic())

            logger.info("YoyoPod setup complete")
            return True
        except Exception:
            logger.exception("Setup failed")
            return False

    def load_configuration(self) -> bool:
        """Load YoyoPod configuration."""
        logger.info("Loading configuration...")

        try:
            self.app.config_manager = ConfigManager(config_dir=self.app.config_dir)
            self.app.app_settings = self.app.config_manager.get_app_settings()
            self.app.media_settings = self.app.config_manager.get_media_settings()
            self.app.people_directory = PeopleDirectory.from_config_manager(self.app.config_manager)
            self.app.call_history_store = CallHistoryStore(
                self.app.config_manager.resolve_runtime_path(
                    self.app.config_manager.get_call_history_file()
                )
            )
            self.app.recent_track_store = RecentTrackHistoryStore(
                self.app.config_manager.resolve_runtime_path(
                    self.app.config_manager.get_recent_tracks_file()
                )
            )
            self.app.audio_device_catalog = AudioDeviceCatalog()
            self.app.audio_device_catalog.refresh_async()

            if self.app.config_manager.app_config_loaded:
                logger.info(
                    "Loaded composed app configuration from canonical config topology under {}",
                    self.app.config_manager.config_dir,
                )
            else:
                logger.info("Using default application configuration")

            if self.app.media_settings is not None:
                self.app.auto_resume_after_call = (
                    self.app.media_settings.music.auto_resume_after_call
                )
            self.app._screen_timeout_seconds = (
                self.app.screen_power_service.resolve_screen_timeout_seconds()
            )
            self.app._active_brightness = self.app.screen_power_service.resolve_active_brightness()
            logger.info(f"  Auto-resume after call: {self.app.auto_resume_after_call}")
            logger.info(f"  Screen timeout: {self.app._screen_timeout_seconds:.1f}s")
            logger.info(f"  Active brightness: {self.app._active_brightness:.2f}")
            return True
        except Exception:
            logger.exception("Failed to load configuration")
            return False

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

    def init_core_components(self) -> bool:
        """Initialize display, context, orchestration models, input, and screen manager."""
        logger.info("Initializing core components...")

        try:
            assert self.app.app_settings is not None
            logger.info("  - Display")
            display_hardware = (
                self.app.app_settings.display.hardware if self.app.app_settings else "auto"
            )
            whisplay_renderer = (
                self.app.app_settings.display.whisplay_renderer
                if self.app.app_settings is not None
                else "pil"
            )
            logger.info(f"    Hardware: {display_hardware}")
            logger.info(f"    Whisplay renderer: {whisplay_renderer}")
            self.app.display = Display(
                hardware=display_hardware,
                simulate=self.app.simulate,
                whisplay_renderer=whisplay_renderer,
                whisplay_lvgl_buffer_lines=self.app.app_settings.display.lvgl_buffer_lines,
            )
            display = self.app.display
            logger.info(f"    Dimensions: {display.WIDTH}x{display.HEIGHT}")
            logger.info(f"    Orientation: {display.ORIENTATION}")
            self.app._lvgl_backend = display.get_ui_backend()
            if self.app._lvgl_backend is not None and self.app._lvgl_backend.initialize():
                display.refresh_backend_kind()
                self.app._last_lvgl_pump_at = time.monotonic()
            else:
                self.app._lvgl_backend = None
                display.refresh_backend_kind()
            logger.info(f"    Active UI backend: {display.backend_kind}")

            display.clear(display.COLOR_BLACK)
            display.text(
                "YoyoPod Starting...",
                10,
                100,
                color=display.COLOR_WHITE,
                font_size=16,
            )
            display.update()
            self.app.screen_power_service.configure_screen_power(initial_now=time.monotonic())

            logger.info("  - AppContext")
            self.app.context = AppContext()
            if self.app.config_manager is not None:
                self.app.context.update_voip_status(
                    configured=bool(
                        self.app.config_manager.get_sip_identity().strip()
                        or self.app.config_manager.get_sip_username().strip()
                    ),
                    ready=False,
                )
            if self.app.context is not None and self.app.config_manager is not None:
                voice_cfg = self.app.config_manager.get_voice_settings()
                speaker_device_id = voice_cfg.audio.speaker_device_id.strip() or None
                capture_device_id = voice_cfg.audio.capture_device_id.strip() or None
                self.app.context.configure_voice(
                    commands_enabled=voice_cfg.assistant.commands_enabled,
                    ai_requests_enabled=voice_cfg.assistant.ai_requests_enabled,
                    screen_read_enabled=voice_cfg.assistant.screen_read_enabled,
                    stt_enabled=voice_cfg.assistant.stt_enabled,
                    tts_enabled=voice_cfg.assistant.tts_enabled,
                    speaker_device_id=speaker_device_id,
                    capture_device_id=capture_device_id,
                )
                self.refresh_talk_summary()
            self.app.screen_power_service.update_screen_runtime_metrics(time.monotonic())

            logger.info("  - Orchestration Models")
            self.app.music_fsm = MusicFSM()
            self.app.call_fsm = CallFSM()
            self.app.call_interruption_policy = CallInterruptionPolicy()

            logger.info("  - InputManager")
            self.app.input_manager = get_input_manager(
                display_adapter=display.get_adapter(),
                input_settings=self.app.app_settings.input,
                simulate=self.app.simulate,
            )
            if self.app.input_manager:
                self.app.context.interaction_profile = self.app.input_manager.interaction_profile
                self.app.input_manager.on_activity(self.app.note_input_activity)
                self.app.input_manager.on_activity(
                    self.app.screen_power_service.queue_user_activity_event
                )
                if self.app._lvgl_backend is not None:
                    self.app._lvgl_input_bridge = LvglInputBridge(self.app._lvgl_backend)
                    self.app.input_manager.on_activity(
                        self.app.runtime_loop.queue_lvgl_input_action
                    )
                self.app.input_manager.start()
                logger.info("    Input system initialized")
            else:
                logger.info("    No input hardware available")

            logger.info("  - ScreenManager")
            action_scheduler = (
                self.app.runtime_loop.queue_main_thread_callback
                if getattr(display, "backend_kind", "pil") == "lvgl"
                else None
            )
            self.app.screen_manager = ScreenManager(
                display,
                self.app.input_manager,
                action_scheduler=action_scheduler,
            )
            return True
        except Exception:
            logger.exception("Failed to initialize core components")
            return False

    def init_managers(self) -> bool:
        """Initialize VoIP and music managers."""
        logger.info("Initializing managers...")

        assert self.app.display is not None
        assert self.app.config_manager is not None
        display = self.app.display
        config_manager = self.app.config_manager

        display.clear(display.COLOR_BLACK)
        display.text(
            "Connecting VoIP...",
            10,
            80,
            color=display.COLOR_WHITE,
            font_size=16,
        )
        display.text(
            "Starting Music...",
            10,
            110,
            color=display.COLOR_WHITE,
            font_size=16,
        )
        display.update()

        try:
            logger.info("  - VoIPManager")
            voip_config = VoIPConfig.from_config_manager(config_manager)
            self.app.voip_manager = VoIPManager(
                voip_config,
                people_directory=self.app.people_directory,
            )
            self.app._voip_iterate_interval_seconds = max(
                0.01,
                float(voip_config.iterate_interval_ms) / 1000.0,
            )
            if self.app.voip_manager.start():
                logger.info("    VoIP started successfully")
            else:
                logger.warning("    VoIP failed to start (music-only mode)")
            if self.app.context is not None and self.app.config_manager is not None:
                self.app.context.update_voip_status(
                    configured=bool(
                        config_manager.get_sip_identity().strip()
                        or config_manager.get_sip_username().strip()
                    ),
                    ready=False,
                )

            logger.info("  - MpvBackend")
            music_config = MusicConfig.from_config_manager(config_manager)
            self.app.music_backend = MpvBackend(music_config)
            self.app.local_music_service = LocalMusicService(
                self.app.music_backend,
                music_dir=music_config.music_dir,
                recent_store=self.app.recent_track_store,
            )
            if self.app.output_volume is None:
                self.app.output_volume = OutputVolumeController(self.app.music_backend)
            else:
                self.app.output_volume.attach_music_backend(self.app.music_backend)
            if self.app.music_backend.start():
                logger.info("    Music backend started successfully")
            else:
                logger.warning("    Music backend failed to start (VoIP-only mode)")

            self.app._apply_default_music_volume()

            logger.info("  - PowerManager")
            self.app.power_manager = PowerManager.from_config_manager(config_manager)
            if self.app.power_manager.config.enabled:
                logger.info(
                    "    Poll interval: {:.1f}s",
                    self.app.power_manager.config.poll_interval_seconds,
                )
            else:
                logger.info("    Power backend disabled in config")

            logger.info("  - NetworkManager")
            self.app.network_manager = NetworkManager.from_config_manager(
                config_manager,
                event_bus=self.app.event_bus,
            )
            if self.app.network_manager.config.enabled and not self.app.simulate:
                try:
                    self.app.network_manager.start()
                    self.app._sync_network_context_from_manager()
                except Exception as exc:
                    logger.error("Network manager start failed: {}", exc)
                    if self.app.context is not None:
                        self.app.context.update_network_status(
                            network_enabled=self.app.network_manager.config.enabled,
                            connection_type="none",
                            connected=False,
                            gps_has_fix=False,
                        )
            else:
                logger.info("    Network module disabled in config")
                if self.app.context is not None:
                    self.app.context.update_network_status(
                        network_enabled=self.app.network_manager.config.enabled,
                        connection_type="none",
                        connected=False,
                        gps_has_fix=False,
                    )

            return True
        except Exception:
            logger.exception("Failed to initialize managers")
            return False

    def setup_screens(self) -> bool:
        """Create and register all screens."""
        logger.info("Setting up screens...")

        try:
            assert self.app.display is not None
            assert self.app.context is not None
            assert self.app.screen_manager is not None
            display = self.app.display
            context = self.app.context
            screen_manager = self.app.screen_manager
            menu_items = ["Listen", "Talk", "Ask", "Setup"]
            self.app.hub_screen = HubScreen(
                display,
                context,
                music_backend=self.app.music_backend,
                local_music_service=self.app.local_music_service,
                voip_manager=self.app.voip_manager,
            )
            self.app.menu_screen = MenuScreen(display, context, items=menu_items)
            self.app.home_screen = HomeScreen(display, context)
            self.app.listen_screen = ListenScreen(
                display,
                context,
                music_service=self.app.local_music_service,
            )
            voice_cfg = (
                self.app.config_manager.get_voice_settings()
                if self.app.config_manager is not None
                else None
            )
            self.app.voice_runtime = VoiceRuntimeCoordinator(
                context=context,
                settings_resolver=VoiceSettingsResolver(
                    context=context,
                    config_manager=self.app.config_manager,
                    settings_provider=lambda: VoiceSettings(
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
                        output_volume=self.app.get_output_volume()
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
                    ),
                ),
                command_executor=VoiceCommandExecutor(
                    context=context,
                    config_manager=self.app.config_manager,
                    people_directory=self.app.people_directory,
                    voip_manager=self.app.voip_manager,
                    volume_up_action=self.app.volume_up,
                    volume_down_action=self.app.volume_down,
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
                ),
            )
            self.app.ask_screen = AskScreen(
                display,
                context,
                config_manager=self.app.config_manager,
                people_directory=self.app.people_directory,
                voip_manager=self.app.voip_manager,
                volume_up_action=self.app.volume_up,
                volume_down_action=self.app.volume_down,
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
                voice_runtime=self.app.voice_runtime,
            )
            self.app.power_screen = PowerScreen(
                display,
                context,
                state_provider=build_power_screen_state_provider(
                    power_manager=self.app.power_manager,
                    network_manager=self.app.network_manager,
                    status_provider=self.app.get_status,
                    playback_device_options_provider=(
                        self.app.audio_device_catalog.playback_devices
                        if self.app.audio_device_catalog is not None
                        else None
                    ),
                    capture_device_options_provider=(
                        self.app.audio_device_catalog.capture_devices
                        if self.app.audio_device_catalog is not None
                        else None
                    ),
                ),
                actions=build_power_screen_actions(
                    network_manager=self.app.network_manager,
                    refresh_voice_device_options_action=(
                        self.app.audio_device_catalog.refresh_async
                        if self.app.audio_device_catalog is not None
                        else None
                    ),
                    persist_speaker_device_action=(
                        self.app.config_manager.set_voice_speaker_device_id
                        if self.app.config_manager is not None
                        else None
                    ),
                    persist_capture_device_action=(
                        self.app.config_manager.set_voice_capture_device_id
                        if self.app.config_manager is not None
                        else None
                    ),
                    volume_up_action=self.app.volume_up,
                    volume_down_action=self.app.volume_down,
                    mute_action=(
                        self.app.voip_manager.mute if self.app.voip_manager is not None else None
                    ),
                    unmute_action=(
                        self.app.voip_manager.unmute if self.app.voip_manager is not None else None
                    ),
                ),
            )
            self.app.now_playing_screen = NowPlayingScreen(
                display,
                context,
                state_provider=build_now_playing_state_provider(
                    context=context,
                    music_backend=self.app.music_backend,
                ),
                actions=build_now_playing_actions(
                    context=context,
                    music_backend=self.app.music_backend,
                ),
            )
            self.app.playlist_screen = PlaylistScreen(
                display,
                context,
                music_service=self.app.local_music_service,
            )
            self.app.recent_tracks_screen = RecentTracksScreen(
                display,
                context,
                music_service=self.app.local_music_service,
            )
            self.app.call_screen = CallScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
                people_directory=self.app.people_directory,
                call_history_store=self.app.call_history_store,
            )
            self.app.call_history_screen = CallHistoryScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
                call_history_store=self.app.call_history_store,
            )
            self.app.talk_contact_screen = TalkContactScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
            )
            self.app.contact_list_screen = ContactListScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
                people_directory=self.app.people_directory,
            )
            self.app.voice_note_screen = VoiceNoteScreen(
                display,
                context,
                state_provider=build_voice_note_state_provider(
                    context=context,
                    voip_manager=self.app.voip_manager,
                ),
                actions=build_voice_note_actions(voip_manager=self.app.voip_manager),
            )
            self.app.incoming_call_screen = IncomingCallScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
                caller_address="",
                caller_name="Unknown",
            )
            self.app.outgoing_call_screen = OutgoingCallScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
                callee_address="",
                callee_name="Unknown",
            )
            self.app.in_call_screen = InCallScreen(
                display,
                context,
                voip_manager=self.app.voip_manager,
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
            logger.info("    - Whisplay root: hub")

            logger.info("  All screens registered")
            logger.info("    - Listen flow: listen, playlists, recent_tracks, now_playing")
            logger.info("    - Ask flow: ask")
            logger.info("    - Power screen: power")
            logger.info(
                "    - VoIP screens: call, talk_contact, call_history, contacts, voice_note, incoming_call, outgoing_call, in_call"
            )
            logger.info("    - Navigation: home, menu")

            initial_screen = self.get_initial_screen_name()
            screen_manager.push_screen(initial_screen)
            self.app._ui_state = self.get_initial_ui_state()
            logger.info(f"  Initial route resolved to {initial_screen}")
            logger.info(f"  Initial screen confirmed as {initial_screen}")
            logger.info("  Initial screen set")
            return True
        except Exception:
            logger.exception("Failed to setup screens")
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

    def get_initial_ui_state(self) -> AppRuntimeState:
        """Return the base runtime state for the active interaction profile."""
        if self.get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return AppRuntimeState.HUB
        return AppRuntimeState.MENU

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""
        logger.info("Setting up VoIP callbacks...")

        if not self.app.voip_manager:
            logger.warning("  VoIPManager not available, skipping callbacks")
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
        self.app.voip_manager.on_message_summary_change(self.app._handle_voice_note_summary_changed)
        self.app.voip_manager.on_message_received(self.app._handle_voice_note_activity_changed)
        self.app.voip_manager.on_message_delivery_change(
            self.app._handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_failure(self.app._handle_voice_note_failure)
        self.refresh_talk_summary()
        self.app._sync_active_voice_note_context()
        logger.info("  VoIP callbacks registered")

    def setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        logger.info("Setting up music callbacks...")

        if not self.app.music_backend:
            logger.warning("  MusicBackend not available, skipping callbacks")
            return

        self.ensure_coordinators()
        assert self.app.playback_coordinator is not None
        self.app.music_backend.on_track_change(self.app.playback_coordinator.publish_track_change)
        self.app.music_backend.on_playback_state_change(
            self.app.playback_coordinator.publish_playback_state_change
        )
        self.app.music_backend.on_connection_change(self.app._sync_output_volume_on_music_connect)
        self.app.music_backend.on_connection_change(
            self.app.playback_coordinator.publish_availability_change
        )
        logger.info("  Music callbacks registered")

    def setup_event_subscriptions(self) -> None:
        """Bind extracted coordinators to the event bus."""
        logger.info("Setting up event subscriptions...")
        self.ensure_coordinators()
        assert self.app.call_coordinator is not None
        assert self.app.playback_coordinator is not None
        assert self.app.power_coordinator is not None
        self.app.call_coordinator.bind(self.app.event_bus)
        self.app.playback_coordinator.bind(self.app.event_bus)
        self.app.power_coordinator.bind(self.app.event_bus)
        logger.info("  Event subscriptions registered")

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
            now_playing_screen=self.app.now_playing_screen,
            call_screen=self.app.call_screen,
            power_screen=self.app.power_screen,
            incoming_call_screen=self.app.incoming_call_screen,
            outgoing_call_screen=self.app.outgoing_call_screen,
            in_call_screen=self.app.in_call_screen,
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
        )
        if self.app.screen_manager is not None:
            self.app.screen_manager.on_screen_changed = self.app._handle_screen_changed
            current_screen = self.app.screen_manager.get_current_screen()
            current_route_name = current_screen.route_name if current_screen is not None else None
            self.app._handle_screen_changed(current_route_name)
