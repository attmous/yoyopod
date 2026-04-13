"""
YoyoPod - Unified VoIP + Local Music Application

Main application bootstrap and lifecycle coordinator.
"""

from __future__ import annotations

import json
import threading
import time
from queue import SimpleQueue
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from loguru import logger

from yoyopy.app_context import AppContext
from yoyopy.audio import LocalMusicService, OutputVolumeController, RecentTrackHistoryStore
from yoyopy.audio.music import MpvBackend, MusicConfig
from yoyopy.config import ConfigManager, YoyoPodConfig
from yoyopy.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)
from yoyopy.event_bus import EventBus
from yoyopy.events import (
    RecoveryAttemptCompletedEvent,
    ScreenChangedEvent,
    UserActivityEvent,
)
from yoyopy.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopy.power import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
    PowerManager,
)
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputManager, InteractionProfile, get_input_manager
from yoyopy.ui.lvgl_binding import LvglDisplayBackend, LvglInputBridge
from yoyopy.ui.screens import (
    AskScreen,
    CallScreen,
    CallHistoryScreen,
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
from yoyopy.voice import VoiceSettings
from yoyopy.voip import CallHistoryStore, VoIPConfig, VoIPManager


@dataclass(slots=True)
class _RecoveryState:
    """Track reconnect backoff for a recoverable subsystem."""

    next_attempt_at: float = 0.0
    delay_seconds: float = 1.0
    in_flight: bool = False

    def reset(self) -> None:
        """Reset backoff after a successful recovery."""
        self.next_attempt_at = 0.0
        self.delay_seconds = 1.0
        self.in_flight = False


@dataclass(slots=True)
class _PowerAlert:
    """Short-lived full-screen power alert overlay."""

    title: str
    subtitle: str
    color: tuple[int, int, int]
    expires_at: float


@dataclass(slots=True)
class _PendingShutdown:
    """Track a delayed low-battery shutdown countdown."""

    reason: str
    requested_at: float
    execute_at: float
    battery_percent: float | None


class YoyoPodApp:
    """
    Main YoyoPod application coordinator.

    Owns startup, lifecycle, and the main loop while delegating call and
    playback orchestration to focused coordinator modules.
    """

    _RECOVERY_MAX_DELAY_SECONDS = 30.0

    def __init__(self, config_dir: str = "config", simulate: bool = False) -> None:
        self.config_dir = config_dir
        self.simulate = simulate

        # Core components
        self.display: Optional[Display] = None
        self.context: Optional[AppContext] = None
        self.config_manager: Optional[ConfigManager] = None
        self.app_settings: Optional[YoyoPodConfig] = None
        self.screen_manager: Optional[ScreenManager] = None
        self.input_manager: Optional[InputManager] = None

        # Manager components
        self.voip_manager: Optional[VoIPManager] = None
        self.music_backend: Optional[MpvBackend] = None
        self.local_music_service: Optional[LocalMusicService] = None
        self.output_volume: Optional[OutputVolumeController] = None
        self.power_manager: Optional[PowerManager] = None
        self.call_history_store: Optional[CallHistoryStore] = None
        self.recent_track_store: Optional[RecentTrackHistoryStore] = None

        # Screen instances
        self.hub_screen: Optional[HubScreen] = None
        self.home_screen: Optional[HomeScreen] = None
        self.menu_screen: Optional[MenuScreen] = None
        self.listen_screen: Optional[ListenScreen] = None
        self.ask_screen: Optional[AskScreen] = None
        self.power_screen: Optional[PowerScreen] = None
        self.now_playing_screen: Optional[NowPlayingScreen] = None
        self.playlist_screen: Optional[PlaylistScreen] = None
        self.recent_tracks_screen: Optional[RecentTracksScreen] = None
        self.call_screen: Optional[CallScreen] = None
        self.talk_contact_screen: Optional[TalkContactScreen] = None
        self.call_history_screen: Optional[CallHistoryScreen] = None
        self.contact_list_screen: Optional[ContactListScreen] = None
        self.voice_note_screen: Optional[VoiceNoteScreen] = None
        self.incoming_call_screen: Optional[IncomingCallScreen] = None
        self.outgoing_call_screen: Optional[OutgoingCallScreen] = None
        self.in_call_screen: Optional[InCallScreen] = None

        # Split orchestration models
        self.music_fsm: Optional[MusicFSM] = None
        self.call_fsm: Optional[CallFSM] = None
        self.call_interruption_policy: Optional[CallInterruptionPolicy] = None

        # Integration state
        self.auto_resume_after_call = True
        self._voip_registered = False
        self._ui_state = AppRuntimeState.IDLE

        # Configuration
        self.config: Dict[str, Any] = {}

        # Main-thread event bus
        self._main_thread_id = threading.get_ident()
        self.event_bus = EventBus(main_thread_id=self._main_thread_id)
        self._pending_main_thread_callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self.event_bus.subscribe(ScreenChangedEvent, self._handle_screen_changed_event)
        self.event_bus.subscribe(UserActivityEvent, self._handle_user_activity_event)
        self.event_bus.subscribe(
            RecoveryAttemptCompletedEvent,
            self._handle_recovery_attempt_completed_event,
        )
        self.event_bus.subscribe(
            LowBatteryWarningRaised,
            self._handle_low_battery_warning_event,
        )
        self.event_bus.subscribe(
            GracefulShutdownRequested,
            self._handle_graceful_shutdown_requested_event,
        )
        self.event_bus.subscribe(
            GracefulShutdownCancelled,
            self._handle_graceful_shutdown_cancelled_event,
        )

        # Extracted coordinators
        self.coordinator_runtime: Optional[CoordinatorRuntime] = None
        self.screen_coordinator: Optional[ScreenCoordinator] = None
        self.call_coordinator: Optional[CallCoordinator] = None
        self.playback_coordinator: Optional[PlaybackCoordinator] = None
        self.power_coordinator: Optional[PowerCoordinator] = None

        # Recovery backoff state
        self._voip_recovery = _RecoveryState()
        self._music_recovery = _RecoveryState()
        self._next_power_poll_at = 0.0
        self._power_available: bool | None = None
        self._power_alert: _PowerAlert | None = None
        self._pending_shutdown: _PendingShutdown | None = None
        self._power_hooks_registered = False
        self._shutdown_completed = False
        self._stopping = False
        self._app_started_at = time.monotonic()
        self._last_user_activity_at = self._app_started_at
        self._screen_on_started_at = self._app_started_at
        self._screen_on_accumulated_seconds = 0.0
        self._screen_timeout_seconds = 0.0
        self._active_brightness = 1.0
        self._screen_awake = True
        self._watchdog_active = False
        self._watchdog_feed_suppressed = False
        self._next_watchdog_feed_at = 0.0
        self._stopped = False
        self._lvgl_backend: Optional[LvglDisplayBackend] = None
        self._lvgl_input_bridge: Optional[LvglInputBridge] = None
        self._last_lvgl_pump_at = 0.0
        self._next_voip_iterate_at = 0.0
        self._voip_iterate_interval_seconds = 0.02

        logger.info("=" * 60)
        logger.info("YoyoPod Application Initializing")
        logger.info("=" * 60)

    @property
    def voip_registered(self) -> bool:
        """Expose the current VoIP registration state for compatibility."""
        if self.call_coordinator is not None:
            return self.call_coordinator.voip_registered
        return self._voip_registered

    @voip_registered.setter
    def voip_registered(self, value: bool) -> None:
        """Store VoIP registration state before or after coordinators are initialized."""
        self._voip_registered = value
        if self.call_coordinator is not None:
            self.call_coordinator.voip_registered = value

    def setup(self) -> bool:
        """
        Initialize all components and register callbacks.

        Returns:
            True if setup successful, False otherwise.
        """
        try:
            if not self._load_configuration():
                logger.error("Failed to load configuration")
                return False

            if not self._init_core_components():
                logger.error("Failed to initialize core components")
                return False

            if not self._init_managers():
                logger.error("Failed to initialize managers")
                return False

            if not self._setup_screens():
                logger.error("Failed to setup screens")
                return False

            self._ensure_coordinators()
            self.coordinator_runtime.set_ui_state(self._ui_state, trigger="initial_screen")
            self._setup_event_subscriptions()
            self._setup_voip_callbacks()
            self._setup_music_callbacks()
            self._register_power_shutdown_hooks()
            self._poll_power_status(force=True, now=time.monotonic())

            logger.info("YoyoPod setup complete")
            return True
        except Exception:
            logger.exception("Setup failed")
            return False

    def _load_configuration(self) -> bool:
        """Load YoyoPod configuration."""
        logger.info("Loading configuration...")

        try:
            self.config_manager = ConfigManager(config_dir=self.config_dir)
            self.app_settings = self.config_manager.get_app_settings()
            self.config = self.config_manager.get_app_config_dict()
            self.call_history_store = CallHistoryStore(
                self.config_manager.config_dir / "call_history.json"
            )
            self.recent_track_store = RecentTrackHistoryStore(
                self.config_manager.config_dir / "recent_tracks.json"
            )

            if self.config_manager.app_config_loaded:
                logger.info(f"Loaded configuration from {self.config_manager.app_config_file}")
            else:
                logger.info("Using default application configuration")

            self.auto_resume_after_call = self.app_settings.audio.auto_resume_after_call
            self._screen_timeout_seconds = self._resolve_screen_timeout_seconds()
            self._active_brightness = self._resolve_active_brightness()
            logger.info(f"  Auto-resume after call: {self.auto_resume_after_call}")
            logger.info(f"  Screen timeout: {self._screen_timeout_seconds:.1f}s")
            logger.info(f"  Active brightness: {self._active_brightness:.2f}")
            return True
        except Exception:
            logger.exception("Failed to load configuration")
            return False

    def _resolve_screen_timeout_seconds(self) -> float:
        """Resolve the effective inactivity timeout used to sleep the screen."""
        if self.app_settings is None:
            return 0.0

        display_timeout = max(0.0, float(self.app_settings.display.backlight_timeout_seconds))
        if display_timeout > 0.0:
            return display_timeout

        return max(0.0, float(self.app_settings.ui.screen_timeout_seconds))

    def _resolve_active_brightness(self) -> float:
        """Resolve the active display brightness as a normalized 0.0-1.0 value."""
        if self.app_settings is None:
            return 1.0

        brightness = max(0, min(100, int(self.app_settings.display.brightness)))
        return brightness / 100.0

    def _configure_screen_power(self, initial_now: float | None = None) -> None:
        """Initialize screen timeout and usage tracking state."""
        now = time.monotonic() if initial_now is None else initial_now
        self._app_started_at = now
        self._last_user_activity_at = now
        self._screen_on_started_at = now
        self._screen_on_accumulated_seconds = 0.0
        self._screen_awake = True

        if self.display is not None:
            self.display.set_backlight(self._active_brightness)

        self._update_screen_runtime_metrics(now)

    def _refresh_talk_summary(self) -> None:
        """Refresh Talk summary data exposed through the shared app context."""

        if self.context is None or self.call_history_store is None:
            return

        self.context.update_call_summary(
            missed_calls=self.call_history_store.missed_count(),
            recent_calls=self.call_history_store.recent_preview(),
        )
        if self.voip_manager is not None:
            self.context.update_voice_note_summary(
                unread_voice_notes=self.voip_manager.unread_voice_note_count(),
                latest_voice_note_by_contact=self.voip_manager.latest_voice_note_summary(),
            )

    def _init_core_components(self) -> bool:
        """Initialize display, context, orchestration models, input, and screen manager."""
        logger.info("Initializing core components...")

        try:
            logger.info("  - Display")
            display_hardware = self.app_settings.display.hardware if self.app_settings else "auto"
            whisplay_renderer = (
                self.app_settings.display.whisplay_renderer
                if self.app_settings is not None
                else "pil"
            )
            logger.info(f"    Hardware: {display_hardware}")
            logger.info(f"    Whisplay renderer: {whisplay_renderer}")
            self.display = Display(
                hardware=display_hardware,
                simulate=self.simulate,
                whisplay_renderer=whisplay_renderer,
                whisplay_lvgl_buffer_lines=self.app_settings.display.lvgl_buffer_lines,
            )
            logger.info(f"    Dimensions: {self.display.WIDTH}x{self.display.HEIGHT}")
            logger.info(f"    Orientation: {self.display.ORIENTATION}")
            self._lvgl_backend = self.display.get_ui_backend()
            if self._lvgl_backend is not None and self._lvgl_backend.initialized:
                self._last_lvgl_pump_at = time.monotonic()
            elif self._lvgl_backend is not None:
                # Backend exists but not yet initialized (e.g. factory skipped init)
                if self._lvgl_backend.initialize():
                    self._last_lvgl_pump_at = time.monotonic()
                else:
                    self._lvgl_backend = None
            self.display.refresh_backend_kind()
            logger.info(f"    Active UI backend: {self.display.backend_kind}")

            self.display.clear(self.display.COLOR_BLACK)
            self.display.text(
                "YoyoPod Starting...",
                10,
                100,
                color=self.display.COLOR_WHITE,
                font_size=16,
            )
            self.display.update()
            self._configure_screen_power(initial_now=time.monotonic())

            logger.info("  - AppContext")
            self.context = AppContext()
            if self.config_manager is not None:
                self.context.update_voip_status(
                    configured=bool(
                        self.config_manager.get_sip_identity().strip()
                        or self.config_manager.get_sip_username().strip()
                    ),
                    ready=False,
                )
            if self.context is not None and self.app_settings is not None:
                voice_cfg = self.app_settings.voice
                self.context.configure_voice(
                    commands_enabled=voice_cfg.commands_enabled,
                    ai_requests_enabled=voice_cfg.ai_requests_enabled,
                    screen_read_enabled=voice_cfg.screen_read_enabled,
                    stt_enabled=voice_cfg.stt_enabled,
                    tts_enabled=voice_cfg.tts_enabled,
                )
                self._refresh_talk_summary()
            self._update_screen_runtime_metrics(time.monotonic())

            logger.info("  - Orchestration Models")
            self.music_fsm = MusicFSM()
            self.call_fsm = CallFSM()
            self.call_interruption_policy = CallInterruptionPolicy()

            logger.info("  - InputManager")
            self.input_manager = get_input_manager(
                display_adapter=self.display.get_adapter(),
                config=self.config,
                simulate=self.simulate,
            )
            if self.input_manager:
                self.context.interaction_profile = self.input_manager.interaction_profile
                self.input_manager.on_activity(self._queue_user_activity_event)
                if self._lvgl_backend is not None:
                    self._lvgl_input_bridge = LvglInputBridge(self._lvgl_backend)
                    self.input_manager.on_activity(self._queue_lvgl_input_action)
                self.input_manager.start()
                logger.info("    ✓ Input system initialized")
            else:
                logger.info("    → No input hardware available")

            logger.info("  - ScreenManager")
            action_scheduler = (
                self._queue_main_thread_callback
                if getattr(self.display, "backend_kind", "pil") == "lvgl"
                else None
            )
            self.screen_manager = ScreenManager(
                self.display,
                self.input_manager,
                action_scheduler=action_scheduler,
            )
            return True
        except Exception:
            logger.exception("Failed to initialize core components")
            return False

    def _init_managers(self) -> bool:
        """Initialize VoIP and music managers."""
        logger.info("Initializing managers...")

        self.display.clear(self.display.COLOR_BLACK)
        self.display.text(
            "Connecting VoIP...", 10, 80, color=self.display.COLOR_WHITE, font_size=16
        )
        self.display.text(
            "Starting Music...",
            10,
            110,
            color=self.display.COLOR_WHITE,
            font_size=16,
        )
        self.display.update()

        try:
            logger.info("  - VoIPManager")
            voip_config = VoIPConfig.from_config_manager(self.config_manager)
            self.voip_manager = VoIPManager(voip_config, config_manager=self.config_manager)
            self._voip_iterate_interval_seconds = max(
                0.01,
                float(voip_config.iterate_interval_ms) / 1000.0,
            )
            if self.voip_manager.start():
                logger.info("    ✓ VoIP started successfully")
            else:
                logger.warning("    ⚠ VoIP failed to start (music-only mode)")
            if self.context is not None and self.config_manager is not None:
                self.context.update_voip_status(
                    configured=bool(
                        self.config_manager.get_sip_identity().strip()
                        or self.config_manager.get_sip_username().strip()
                    ),
                    ready=False,
                )

            logger.info("  - MpvBackend")
            audio_cfg = self.app_settings.audio if self.app_settings else None
            music_config = MusicConfig(
                music_dir=Path(audio_cfg.music_dir) if audio_cfg else Path("/home/pi/Music"),
                mpv_socket=audio_cfg.mpv_socket if audio_cfg and audio_cfg.mpv_socket else "",
                mpv_binary=audio_cfg.mpv_binary if audio_cfg else "mpv",
                alsa_device=audio_cfg.alsa_device if audio_cfg else "default",
            )
            self.music_backend = MpvBackend(music_config)
            self.local_music_service = LocalMusicService(
                self.music_backend,
                music_dir=music_config.music_dir,
                recent_store=self.recent_track_store,
            )
            if self.output_volume is None:
                self.output_volume = OutputVolumeController(self.music_backend)
            else:
                self.output_volume.attach_music_backend(self.music_backend)
            if self.music_backend.start():
                logger.info("    ✓ Music backend started successfully")
            else:
                logger.warning("    ⚠ Music backend failed to start (VoIP-only mode)")

            self._apply_default_music_volume()

            logger.info("  - PowerManager")
            self.power_manager = PowerManager.from_config_manager(self.config_manager)
            if self.power_manager.config.enabled:
                logger.info(
                    "    Poll interval: {:.1f}s",
                    self.power_manager.config.poll_interval_seconds,
                )
            else:
                logger.info("    Power backend disabled in config")

            return True
        except Exception:
            logger.exception("Failed to initialize managers")
            return False

    def _resolve_default_music_volume(self) -> int:
        """Return the configured startup volume for the music backend."""
        audio_cfg = self.app_settings.audio if self.app_settings else None
        raw_volume = audio_cfg.default_volume if audio_cfg else 100
        return max(0, min(100, int(raw_volume)))

    def _apply_default_music_volume(self) -> None:
        """Apply the configured startup volume to ALSA and the live music backend."""
        volume = self._resolve_default_music_volume()

        if self.output_volume is not None:
            if self.output_volume.set_volume(volume):
                resolved = self.output_volume.get_volume()
                if self.context is not None and resolved is not None:
                    self.context.playback.volume = resolved
                    self.context.voice.output_volume = resolved
                logger.info("    Startup output volume set to {}%", resolved or volume)
                return
            logger.warning("    Failed to set startup output volume to {}%", volume)

        if self.context is not None:
            self.context.playback.volume = volume
            self.context.voice.output_volume = volume

        if self.music_backend is None or not self.music_backend.is_connected:
            return

        if self.music_backend.set_volume(volume):
            logger.info("    Startup music volume set to {}%", volume)
        else:
            logger.warning("    Failed to set startup music volume to {}%", volume)

    def get_output_volume(self) -> int | None:
        """Return the current shared output volume."""
        if self.output_volume is not None:
            volume = self.output_volume.get_volume()
            if self.context is not None and volume is not None:
                self.context.playback.volume = volume
                self.context.voice.output_volume = volume
            return volume
        if self.context is not None:
            return self.context.playback.volume
        return None

    def set_output_volume(self, volume: int) -> bool:
        """Set the shared output volume across ALSA and the music backend."""
        target = max(0, min(100, int(volume)))

        applied = False
        if self.output_volume is not None:
            applied = self.output_volume.set_volume(target)
        elif self.music_backend is not None and self.music_backend.is_connected:
            applied = self.music_backend.set_volume(target)

        if self.context is not None:
            resolved = self.get_output_volume()
            self.context.playback.volume = resolved if resolved is not None else target
            self.context.voice.output_volume = resolved if resolved is not None else target

        return applied

    def volume_up(self, step: int = 5) -> int | None:
        """Increase shared output volume."""
        current = self.get_output_volume()
        target = (current if current is not None else 0) + step
        self.set_output_volume(target)
        return self.get_output_volume()

    def volume_down(self, step: int = 5) -> int | None:
        """Decrease shared output volume."""
        current = self.get_output_volume()
        target = (current if current is not None else 0) - step
        self.set_output_volume(target)
        return self.get_output_volume()

    def _sync_output_volume_on_music_connect(self, connected: bool, _reason: str) -> None:
        """Reapply the current shared volume whenever mpv reconnects."""
        if not connected or self.output_volume is None:
            return

        volume = self.output_volume.get_volume()
        if volume is None:
            volume = self._resolve_default_music_volume()

        if self.output_volume.sync_music_backend(volume) and self.context is not None:
            self.context.playback.volume = volume
            self.context.voice.output_volume = volume

    def _setup_screens(self) -> bool:
        """Create and register all screens."""
        logger.info("Setting up screens...")

        try:
            menu_items = [
                "Listen",
                "Talk",
                "Ask",
                "Setup",
            ]
            self.hub_screen = HubScreen(
                self.display,
                self.context,
                music_backend=self.music_backend,
                local_music_service=self.local_music_service,
                voip_manager=self.voip_manager,
            )
            self.menu_screen = MenuScreen(self.display, self.context, items=menu_items)
            self.home_screen = HomeScreen(self.display, self.context)
            self.listen_screen = ListenScreen(
                self.display,
                self.context,
                music_service=self.local_music_service,
            )
            voice_cfg = self.app_settings.voice if self.app_settings is not None else None
            self.ask_screen = AskScreen(
                self.display,
                self.context,
                config_manager=self.config_manager,
                voip_manager=self.voip_manager,
                volume_up_action=self.volume_up,
                volume_down_action=self.volume_down,
                mute_action=self.voip_manager.mute if self.voip_manager is not None else None,
                unmute_action=self.voip_manager.unmute if self.voip_manager is not None else None,
                play_music_action=(
                    self.local_music_service.shuffle_all
                    if self.local_music_service is not None
                    else None
                ),
                voice_settings_provider=lambda: VoiceSettings(
                    commands_enabled=(
                        self.context.voice.commands_enabled if self.context is not None else True
                    ),
                    ai_requests_enabled=(
                        self.context.voice.ai_requests_enabled if self.context is not None else True
                    ),
                    screen_read_enabled=(
                        self.context.voice.screen_read_enabled
                        if self.context is not None
                        else False
                    ),
                    stt_enabled=(
                        self.context.voice.stt_enabled if self.context is not None else True
                    ),
                    tts_enabled=(
                        self.context.voice.tts_enabled if self.context is not None else True
                    ),
                    mic_muted=self.context.voice.mic_muted if self.context is not None else False,
                    output_volume=self.get_output_volume()
                    or (self.context.voice.output_volume if self.context is not None else 50),
                    stt_backend=voice_cfg.stt_backend if voice_cfg is not None else "vosk",
                    tts_backend=voice_cfg.tts_backend if voice_cfg is not None else "espeak-ng",
                    vosk_model_path=(
                        voice_cfg.vosk_model_path
                        if voice_cfg is not None
                        else "models/vosk-model-small-en-us"
                    ),
                    capture_device_id=(
                        self.config_manager.get_capture_device_id()
                        if self.config_manager is not None
                        else None
                    ),
                    sample_rate_hz=voice_cfg.sample_rate_hz if voice_cfg is not None else 16000,
                    record_seconds=voice_cfg.record_seconds if voice_cfg is not None else 4,
                    tts_rate_wpm=voice_cfg.tts_rate_wpm if voice_cfg is not None else 155,
                    tts_voice=voice_cfg.tts_voice if voice_cfg is not None else "en",
                ),
            )
            self.power_screen = PowerScreen(
                self.display,
                self.context,
                power_manager=self.power_manager,
                status_provider=self.get_status,
                volume_up_action=self.volume_up,
                volume_down_action=self.volume_down,
                mute_action=self.voip_manager.mute if self.voip_manager is not None else None,
                unmute_action=self.voip_manager.unmute if self.voip_manager is not None else None,
            )
            self.now_playing_screen = NowPlayingScreen(
                self.display,
                self.context,
                music_backend=self.music_backend,
            )
            self.playlist_screen = PlaylistScreen(
                self.display,
                self.context,
                music_service=self.local_music_service,
            )
            self.recent_tracks_screen = RecentTracksScreen(
                self.display,
                self.context,
                music_service=self.local_music_service,
            )
            self.call_screen = CallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager,
                call_history_store=self.call_history_store,
            )
            self.call_history_screen = CallHistoryScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                call_history_store=self.call_history_store,
            )
            self.talk_contact_screen = TalkContactScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
            )
            self.contact_list_screen = ContactListScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager,
            )
            self.voice_note_screen = VoiceNoteScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
            )
            self.incoming_call_screen = IncomingCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                caller_address="",
                caller_name="Unknown",
            )
            self.outgoing_call_screen = OutgoingCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                callee_address="",
                callee_name="Unknown",
            )
            self.in_call_screen = InCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
            )

            self.screen_manager.register_screen("hub", self.hub_screen)
            self.screen_manager.register_screen("home", self.home_screen)
            self.screen_manager.register_screen("menu", self.menu_screen)
            self.screen_manager.register_screen("listen", self.listen_screen)
            self.screen_manager.register_screen("ask", self.ask_screen)
            self.screen_manager.register_screen("power", self.power_screen)
            self.screen_manager.register_screen("now_playing", self.now_playing_screen)
            self.screen_manager.register_screen("playlists", self.playlist_screen)
            self.screen_manager.register_screen("recent_tracks", self.recent_tracks_screen)
            self.screen_manager.register_screen("call", self.call_screen)
            self.screen_manager.register_screen("talk_contact", self.talk_contact_screen)
            self.screen_manager.register_screen("call_history", self.call_history_screen)
            self.screen_manager.register_screen("contacts", self.contact_list_screen)
            self.screen_manager.register_screen("voice_note", self.voice_note_screen)
            self.screen_manager.register_screen("incoming_call", self.incoming_call_screen)
            self.screen_manager.register_screen("outgoing_call", self.outgoing_call_screen)
            self.screen_manager.register_screen("in_call", self.in_call_screen)
            logger.info("    - Whisplay root: hub")

            logger.info("  ✓ All screens registered")
            logger.info("    - Listen flow: listen, playlists, recent_tracks, now_playing")
            logger.info("    - Ask flow: ask")
            logger.info("    - Power screen: power")
            logger.info(
                "    - VoIP screens: call, talk_contact, call_history, contacts, voice_note, incoming_call, outgoing_call, in_call"
            )
            logger.info("    - Navigation: home, menu")

            initial_screen = self._get_initial_screen_name()
            self.screen_manager.push_screen(initial_screen)
            self._ui_state = self._get_initial_ui_state()
            logger.info(f"  Initial route resolved to {initial_screen}")
            logger.info(f"  Initial screen confirmed as {initial_screen}")
            logger.info("  ✓ Initial screen set to menu")
            return True
        except Exception:
            logger.exception("Failed to setup screens")
            return False

    def _get_interaction_profile(self) -> InteractionProfile:
        """Return the active hardware interaction profile."""
        if self.input_manager is not None:
            return self.input_manager.interaction_profile
        if self.context is not None:
            return self.context.interaction_profile
        return InteractionProfile.STANDARD

    def _get_initial_screen_name(self) -> str:
        """Return the root screen for the active interaction profile."""
        return "hub"

    def _get_initial_ui_state(self) -> AppRuntimeState:
        """Return the base runtime state for the active interaction profile."""
        return AppRuntimeState.HUB

    def _setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""
        logger.info("Setting up VoIP callbacks...")

        if not self.voip_manager:
            logger.warning("  VoIPManager not available, skipping callbacks")
            return

        self._ensure_coordinators()
        self.voip_manager.on_incoming_call(self.call_coordinator.publish_incoming_call)
        self.voip_manager.on_call_state_change(self.call_coordinator.publish_call_state_events)
        self.voip_manager.on_registration_change(self.call_coordinator.publish_registration_change)
        self.voip_manager.on_availability_change(self.call_coordinator.publish_availability_change)
        self.voip_manager.on_message_summary_change(self._handle_voice_note_summary_changed)
        self.voip_manager.on_message_received(self._handle_voice_note_activity_changed)
        self.voip_manager.on_message_delivery_change(self._handle_voice_note_activity_changed)
        self.voip_manager.on_message_failure(self._handle_voice_note_failure)
        self._refresh_talk_summary()
        self._sync_active_voice_note_context()
        logger.info("  VoIP callbacks registered")

    def _handle_voice_note_summary_changed(
        self,
        unread_voice_notes: int,
        latest_voice_note_by_contact: dict[str, dict[str, object]],
    ) -> None:
        """Keep Talk voice-note summary state in sync with the VoIP manager."""

        if self.context is None:
            return
        self.context.update_voice_note_summary(
            unread_voice_notes=unread_voice_notes,
            latest_voice_note_by_contact=latest_voice_note_by_contact,
        )
        self._refresh_talk_related_screen()

    def _handle_voice_note_activity_changed(self, *_args) -> None:
        """Refresh active draft state after a message or delivery update."""

        self._sync_active_voice_note_context()
        self._refresh_talk_summary()
        self._refresh_talk_related_screen()

    def _handle_voice_note_failure(self, *_args) -> None:
        """Refresh draft state after a failed message operation."""

        self._sync_active_voice_note_context()
        self._refresh_talk_related_screen()

    def _sync_active_voice_note_context(self) -> None:
        """Mirror the active voice-note draft into the shared app context."""

        if self.context is None or self.voip_manager is None:
            return
        draft = self.voip_manager.get_active_voice_note()
        if draft is None:
            self.context.update_active_voice_note(send_state="idle")
            return
        self.context.update_active_voice_note(
            send_state=draft.send_state,
            status_text=draft.status_text,
            file_path=draft.file_path,
            duration_ms=draft.duration_ms,
        )

    def _refresh_talk_related_screen(self) -> None:
        """Re-render Talk screens when their message state changes."""

        if self.screen_manager is None:
            return
        current_screen = self.screen_manager.get_current_screen()
        if current_screen is None:
            return
        if current_screen.route_name in {"call", "talk_contact", "voice_note"}:
            self.screen_manager.refresh_current_screen()
        return
        logger.info("  ✓ VoIP callbacks registered")

    def _setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        logger.info("Setting up music callbacks...")

        if not self.music_backend:
            logger.warning("  MusicBackend not available, skipping callbacks")
            return

        self._ensure_coordinators()
        self.music_backend.on_track_change(self.playback_coordinator.publish_track_change)
        self.music_backend.on_playback_state_change(
            self.playback_coordinator.publish_playback_state_change
        )
        self.music_backend.on_connection_change(self._sync_output_volume_on_music_connect)
        self.music_backend.on_connection_change(
            self.playback_coordinator.publish_availability_change
        )
        logger.info("  ✓ Music callbacks registered")

    def _setup_event_subscriptions(self) -> None:
        """Bind extracted coordinators to the event bus."""
        logger.info("Setting up event subscriptions...")
        self._ensure_coordinators()
        self.call_coordinator.bind(self.event_bus)
        self.playback_coordinator.bind(self.event_bus)
        self.power_coordinator.bind(self.event_bus)
        logger.info("  ✓ Event subscriptions registered")

    def _process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued typed events scheduled by worker threads."""
        processed = 0
        while not self._pending_main_thread_callbacks.empty():
            callback = self._pending_main_thread_callbacks.get()
            try:
                callback()
            except Exception as exc:
                logger.error(f"Error handling scheduled main-thread callback: {exc}")
            processed += 1
            if limit is not None and processed >= limit:
                return processed

        remaining_limit = None if limit is None else max(0, limit - processed)
        return processed + self.event_bus.drain(remaining_limit)

    def _queue_main_thread_callback(self, callback: Callable[[], None]) -> None:
        """Schedule a callback to run on the coordinator thread."""
        self._pending_main_thread_callbacks.put(callback)

    def _queue_lvgl_input_action(self, action, _data: Optional[Any] = None) -> None:
        """Queue semantic actions for LVGL from input polling threads."""

        if self._lvgl_input_bridge is None:
            return
        self._lvgl_input_bridge.enqueue_action(action)

    def _pump_lvgl_backend(self, now: float | None = None) -> None:
        """Pump LVGL timers and queued input on the coordinator thread."""

        if self._lvgl_backend is None or not self._lvgl_backend.initialized:
            return

        monotonic_now = time.monotonic() if now is None else now
        if self._last_lvgl_pump_at <= 0.0:
            delta_ms = 0
        else:
            delta_ms = int(max(0.0, monotonic_now - self._last_lvgl_pump_at) * 1000.0)
        self._last_lvgl_pump_at = monotonic_now

        if self._lvgl_input_bridge is not None:
            self._lvgl_input_bridge.process_pending()
        self._lvgl_backend.pump(delta_ms)

    def _iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        """Advance the Liblinphone core on the coordinator thread at its configured cadence."""

        if self.voip_manager is None or not self.voip_manager.running:
            return

        monotonic_now = time.monotonic() if now is None else now
        if self._next_voip_iterate_at <= 0.0:
            self._next_voip_iterate_at = monotonic_now

        if monotonic_now < self._next_voip_iterate_at:
            return

        self.voip_manager.iterate()
        self._next_voip_iterate_at = monotonic_now + self._voip_iterate_interval_seconds

    def _handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        """Apply queued screen-change state sync on the coordinator thread."""
        self._sync_screen_changed(event.screen_name)
        self._mark_user_activity(now=time.monotonic(), render_on_wake=False)

    def _queue_user_activity_event(self, action, data: Any | None = None) -> None:
        """Publish semantic user activity onto the main-thread event bus."""
        action_name = getattr(action, "value", None)
        self.event_bus.publish(UserActivityEvent(action_name=action_name))

    def _handle_user_activity_event(self, event: UserActivityEvent) -> None:
        """Wake the display and reset the inactivity timer on user activity."""
        logger.debug(f"User activity received: {event.action_name or 'unknown'}")
        # Raw physical activity (for example the first Whisplay button press before
        # one-button gesture resolution) should wake the backlight without forcing
        # an immediate redraw of the current screen. The semantic action render that
        # follows should own the visible transition.
        self._mark_user_activity(
            now=time.monotonic(),
            render_on_wake=event.action_name is not None,
        )

    def _handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        """Finalize background recovery attempts on the coordinator thread."""
        if event.manager != "music":
            return

        self._music_recovery.in_flight = False
        if self._stopping:
            return

        if event.recovered and self.music_backend:
            if hasattr(self.music_backend, "polling") and not getattr(
                self.music_backend, "polling"
            ):
                start_polling = getattr(self.music_backend, "start_polling", None)
                if start_polling is not None:
                    start_polling()

        self._finalize_recovery_attempt(
            "Music",
            self._music_recovery,
            event.recovered,
            event.recovery_now,
        )

    def _handle_low_battery_warning_event(self, event: LowBatteryWarningRaised) -> None:
        """Show a temporary low-battery alert when the warning threshold is crossed."""
        logger.warning(
            "Low battery warning: {:.1f}% remaining (threshold {:.1f}%)",
            event.battery_percent,
            event.threshold_percent,
        )
        self._set_power_alert(
            title="Low Battery",
            subtitle=f"{event.battery_percent:.0f}% remaining",
            color=self.display.COLOR_YELLOW if self.display is not None else (255, 255, 0),
            duration_seconds=4.0,
        )

    def _handle_graceful_shutdown_requested_event(
        self,
        event: GracefulShutdownRequested,
    ) -> None:
        """Start a delayed graceful shutdown countdown for critical battery."""
        if self._pending_shutdown is not None:
            return

        requested_at = time.monotonic()
        self._pending_shutdown = _PendingShutdown(
            reason=event.reason,
            requested_at=requested_at,
            execute_at=requested_at + max(0.0, event.delay_seconds),
            battery_percent=event.snapshot.battery.level_percent,
        )
        self._wake_screen(requested_at, render_current=False)
        logger.warning(
            "Critical battery detected; shutdown in {:.1f}s",
            event.delay_seconds,
        )

    def _handle_graceful_shutdown_cancelled_event(
        self,
        event: GracefulShutdownCancelled,
    ) -> None:
        """Cancel a pending battery-triggered shutdown when power returns."""
        if self._pending_shutdown is None:
            return

        logger.info(f"Graceful shutdown cancelled ({event.reason})")
        self._pending_shutdown = None
        self._set_power_alert(
            title="Power Restored",
            subtitle="Shutdown cancelled",
            color=self.display.COLOR_GREEN if self.display is not None else (0, 255, 0),
            duration_seconds=3.0,
        )

    def _register_power_shutdown_hooks(self) -> None:
        """Register built-in shutdown hooks once the power manager is available."""
        if self.power_manager is None or self._power_hooks_registered:
            return

        self.power_manager.register_shutdown_hook(
            "save_shutdown_state",
            self._save_shutdown_state,
        )
        self._power_hooks_registered = True

    def _save_shutdown_state(self) -> None:
        """Persist a small runtime snapshot before graceful poweroff."""
        if self.power_manager is None:
            return

        snapshot_path = Path(self.power_manager.config.shutdown_state_file)
        if not snapshot_path.is_absolute():
            snapshot_path = Path.cwd() / snapshot_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        current_screen = None
        if self.screen_manager is not None and self.screen_manager.get_current_screen() is not None:
            current_screen = self.screen_manager.get_current_screen().route_name

        current_track = None
        if self.context is not None and self.context.get_current_track() is not None:
            track = self.context.get_current_track()
            current_track = {
                "title": track.title,
                "artist": track.artist,
            }

        payload = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "state": (
                self.coordinator_runtime.get_state_name() if self.coordinator_runtime else None
            ),
            "current_screen": current_screen,
            "battery_percent": self.context.battery_percent if self.context else None,
            "battery_charging": self.context.battery_charging if self.context else None,
            "external_power": self.context.external_power if self.context else None,
            "voip_registered": self.voip_registered,
            "music_available": self.music_backend.is_connected if self.music_backend else False,
            "app_uptime_seconds": self.context.app_uptime_seconds if self.context else 0,
            "screen_on_seconds": self.context.screen_on_seconds if self.context else 0,
            "screen_awake": self.context.screen_awake if self.context else True,
            "screen_idle_seconds": self.context.screen_idle_seconds if self.context else 0,
            "playback": {
                "is_playing": self.context.playback.is_playing if self.context else False,
                "is_paused": self.context.playback.is_paused if self.context else False,
                "volume": self.context.playback.volume if self.context else None,
            },
            "track": current_track,
        }

        snapshot_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Saved shutdown state to {snapshot_path}")

    def _ensure_coordinators(self) -> None:
        """Build coordinator helpers around the initialized runtime."""
        if self.coordinator_runtime is not None:
            return

        self.coordinator_runtime = CoordinatorRuntime(
            music_fsm=self.music_fsm,
            call_fsm=self.call_fsm,
            call_interruption_policy=self.call_interruption_policy,
            screen_manager=self.screen_manager,
            music_backend=self.music_backend,
            power_manager=self.power_manager,
            now_playing_screen=self.now_playing_screen,
            call_screen=self.call_screen,
            power_screen=self.power_screen,
            incoming_call_screen=self.incoming_call_screen,
            outgoing_call_screen=self.outgoing_call_screen,
            in_call_screen=self.in_call_screen,
            config=self.config,
            config_manager=self.config_manager,
            context=self.context,
            ui_state=self._ui_state,
            voip_ready=self._voip_registered,
        )
        self.screen_coordinator = ScreenCoordinator(self.coordinator_runtime)
        self.call_coordinator = CallCoordinator(
            runtime=self.coordinator_runtime,
            screen_coordinator=self.screen_coordinator,
            auto_resume_after_call=self.auto_resume_after_call,
            call_history_store=self.call_history_store,
            initial_voip_registered=self._voip_registered,
        )
        self.playback_coordinator = PlaybackCoordinator(
            runtime=self.coordinator_runtime,
            screen_coordinator=self.screen_coordinator,
            local_music_service=self.local_music_service,
        )
        self.power_coordinator = PowerCoordinator(
            runtime=self.coordinator_runtime,
            screen_coordinator=self.screen_coordinator,
            context=self.context,
        )
        if self.screen_manager is not None:
            self.screen_manager.on_screen_changed = self._handle_screen_changed
            current_screen = self.screen_manager.get_current_screen()
            current_route_name = current_screen.route_name if current_screen is not None else None
            self._handle_screen_changed(current_route_name)

    def _pop_call_screens(self) -> None:
        """Compatibility wrapper for clearing call-related screens."""
        self._ensure_coordinators()
        self.screen_coordinator.pop_call_screens()

    def _update_now_playing_if_needed(self) -> None:
        """Compatibility wrapper for periodic now-playing refreshes."""
        self._ensure_coordinators()
        self.playback_coordinator.update_now_playing_if_needed()

    def _update_in_call_if_needed(self) -> None:
        """Refresh the in-call screen from the main loop when it is visible."""
        self._ensure_coordinators()
        self.screen_coordinator.update_in_call_if_needed()

    def _update_power_screen_if_needed(self) -> None:
        """Refresh the power screen from the main loop when it is visible."""
        self._ensure_coordinators()
        self.screen_coordinator.update_power_screen_if_needed()

    def _start_ringing(self) -> None:
        """Compatibility wrapper for starting the call ring tone."""
        self._ensure_coordinators()
        self.call_coordinator.start_ringing()

    def _stop_ringing(self) -> None:
        """Compatibility wrapper for stopping the call ring tone."""
        self._ensure_coordinators()
        self.call_coordinator.stop_ringing()

    def _handle_screen_changed(self, screen_name: str | None) -> None:
        """Marshal screen-state sync work onto the coordinator thread."""
        self.event_bus.publish(ScreenChangedEvent(screen_name=screen_name))

    def _sync_screen_changed(self, screen_name: str | None) -> None:
        """Keep the derived base UI state aligned with the active screen."""
        self._ensure_coordinators()
        self.coordinator_runtime.sync_ui_state_for_screen(screen_name)

    def _mark_user_activity(
        self,
        *,
        now: float | None = None,
        render_on_wake: bool,
    ) -> None:
        """Reset inactivity tracking and wake the screen when needed."""
        activity_now = time.monotonic() if now is None else now
        self._last_user_activity_at = activity_now
        if self._screen_awake:
            self._update_screen_runtime_metrics(activity_now)
            return

        self._wake_screen(activity_now, render_current=render_on_wake)

    def _wake_screen(self, now: float, *, render_current: bool) -> None:
        """Restore active brightness and optionally re-render the current screen."""
        if self._screen_awake:
            self._update_screen_runtime_metrics(now)
            return

        self._screen_awake = True
        self._screen_on_started_at = now
        if self.display is not None:
            self.display.set_backlight(self._active_brightness)

        if render_current and self.screen_manager is not None:
            current_screen = self.screen_manager.get_current_screen()
            if current_screen is not None:
                current_screen.render()

        if self._lvgl_backend is not None and self._lvgl_backend.initialized:
            self._lvgl_backend.force_refresh()

        self._update_screen_runtime_metrics(now)
        logger.debug("Screen woke from inactivity")

    def _sleep_screen(self, now: float) -> None:
        """Turn off the display backlight and retain cumulative screen-on time."""
        if not self._screen_awake:
            self._update_screen_runtime_metrics(now)
            return

        if self._screen_on_started_at is not None:
            self._screen_on_accumulated_seconds += max(0.0, now - self._screen_on_started_at)
        self._screen_on_started_at = None
        self._screen_awake = False
        if self.display is not None:
            self.display.set_backlight(0.0)
        self._update_screen_runtime_metrics(now)
        logger.info("Screen slept after inactivity timeout")

    def _update_screen_runtime_metrics(self, now: float) -> None:
        """Refresh app uptime and screen usage metrics in the shared context."""
        screen_on_seconds = self._screen_on_accumulated_seconds
        if self._screen_awake and self._screen_on_started_at is not None:
            screen_on_seconds += max(0.0, now - self._screen_on_started_at)

        idle_seconds = max(0.0, now - self._last_user_activity_at)
        app_uptime_seconds = max(0.0, now - self._app_started_at)

        if self.context is not None:
            self.context.update_screen_runtime(
                screen_awake=self._screen_awake,
                app_uptime_seconds=app_uptime_seconds,
                screen_on_seconds=screen_on_seconds,
                idle_seconds=idle_seconds,
            )

    def _update_screen_power(self, now: float) -> None:
        """Apply inactivity-based screen timeout policy and refresh runtime metrics."""
        if self._pending_shutdown is not None or self._power_alert is not None:
            self._wake_screen(now, render_current=False)
            return

        self._update_screen_runtime_metrics(now)
        if self._screen_timeout_seconds <= 0 or not self._screen_awake:
            return

        if now - self._last_user_activity_at < self._screen_timeout_seconds:
            return

        self._sleep_screen(now)

    def _attempt_manager_recovery(self, now: float | None = None) -> None:
        """Try to recover VoIP and music when they become unavailable."""
        if self._stopping:
            return

        recovery_now = time.monotonic() if now is None else now
        self._attempt_voip_recovery(recovery_now)
        self._attempt_music_recovery(recovery_now)

    def _poll_power_status(self, now: float | None = None, force: bool = False) -> None:
        """Refresh PiSugar power telemetry on the coordinator thread."""
        if self.power_manager is None:
            return

        poll_now = time.monotonic() if now is None else now
        if not force and poll_now < self._next_power_poll_at:
            return

        self._ensure_coordinators()
        snapshot = self.power_manager.refresh()
        self.power_coordinator.publish_snapshot(snapshot)

        if self._power_available is None or self._power_available != snapshot.available:
            reason = snapshot.error or ("ready" if snapshot.available else "unavailable")
            self._power_available = snapshot.available
            self.power_coordinator.publish_availability_change(snapshot.available, reason)

        interval = max(1.0, self.power_manager.config.poll_interval_seconds)
        self._next_power_poll_at = poll_now + interval

    def _set_power_alert(
        self,
        *,
        title: str,
        subtitle: str,
        color: tuple[int, int, int],
        duration_seconds: float,
    ) -> None:
        """Queue a short-lived fullscreen power alert overlay."""
        self._wake_screen(time.monotonic(), render_current=False)
        self._power_alert = _PowerAlert(
            title=title,
            subtitle=subtitle,
            color=color,
            expires_at=time.monotonic() + max(0.0, duration_seconds),
        )

    def _render_power_overlay(self, title: str, subtitle: str, color: tuple[int, int, int]) -> None:
        """Render a simple fullscreen power-status overlay."""
        if self.display is None:
            return

        self.display.clear(self.display.COLOR_BLACK)
        title_size = 24
        subtitle_size = 14
        title_width, title_height = self.display.get_text_size(title, title_size)
        subtitle_width, _ = self.display.get_text_size(subtitle, subtitle_size)
        title_x = (self.display.WIDTH - title_width) // 2
        subtitle_x = (self.display.WIDTH - subtitle_width) // 2
        title_y = max(self.display.STATUS_BAR_HEIGHT + 30, (self.display.HEIGHT // 2) - 30)
        subtitle_y = title_y + title_height + 18

        self.display.text(title, title_x, title_y, color=color, font_size=title_size)
        self.display.text(
            subtitle,
            subtitle_x,
            subtitle_y,
            color=self.display.COLOR_WHITE,
            font_size=subtitle_size,
        )
        self.display.update()

    def _update_power_overlays(self, now: float) -> bool:
        """Render pending power overlays and return True when one is active."""
        if self._pending_shutdown is not None:
            seconds_remaining = max(0, int(self._pending_shutdown.execute_at - now + 0.999))
            subtitle = "Saving state and powering off"
            if seconds_remaining > 0:
                subtitle = f"Shutdown in {seconds_remaining}s"
            self._render_power_overlay(
                "Critical Battery",
                subtitle,
                self.display.COLOR_RED if self.display is not None else (255, 0, 0),
            )
            return True

        if self._power_alert is None:
            return False

        if now >= self._power_alert.expires_at:
            self._power_alert = None
            if (
                self.screen_manager is not None
                and self.screen_manager.get_current_screen() is not None
            ):
                self.screen_manager.get_current_screen().render()
            return False

        self._render_power_overlay(
            self._power_alert.title,
            self._power_alert.subtitle,
            self._power_alert.color,
        )
        return True

    def _process_pending_shutdown(self, now: float) -> None:
        """Execute a delayed shutdown when its grace period expires."""
        if self._pending_shutdown is None or now < self._pending_shutdown.execute_at:
            return

        self._execute_pending_shutdown()

    def _execute_pending_shutdown(self) -> None:
        """Run graceful-shutdown hooks, stop the app, and request system poweroff."""
        if self._shutdown_completed:
            return

        self._suppress_watchdog_feeding("pending system poweroff")
        self._render_power_overlay(
            "Powering Off",
            "Saving state...",
            self.display.COLOR_RED if self.display is not None else (255, 0, 0),
        )

        if self.power_manager is not None:
            failed_hooks = self.power_manager.run_shutdown_hooks()
            if failed_hooks:
                logger.warning(f"Shutdown hooks failed: {', '.join(failed_hooks)}")

        self.stop(disable_watchdog=False)

        if self.power_manager is not None:
            self.power_manager.request_system_shutdown()

        self._shutdown_completed = True

    def _start_watchdog(self, now: float | None = None) -> None:
        """Enable the PiSugar software watchdog once the app loop is ready."""
        if self.simulate or self.power_manager is None:
            return

        if not self.power_manager.config.watchdog_enabled or self._watchdog_active:
            return

        feed_interval = max(1.0, float(self.power_manager.config.watchdog_feed_interval_seconds))
        timeout_seconds = max(1, int(self.power_manager.config.watchdog_timeout_seconds))
        if feed_interval >= timeout_seconds:
            logger.warning(
                "Power watchdog feed interval ({}) should be less than timeout ({})",
                feed_interval,
                timeout_seconds,
            )

        if not self.power_manager.enable_watchdog():
            logger.warning("Power watchdog could not be enabled")
            return

        watchdog_now = time.monotonic() if now is None else now
        self._watchdog_active = True
        self._watchdog_feed_suppressed = False
        self._next_watchdog_feed_at = watchdog_now + feed_interval
        logger.info(
            "Power watchdog enabled (timeout={}s, feed={}s)",
            timeout_seconds,
            feed_interval,
        )

    def _feed_watchdog_if_due(self, now: float) -> None:
        """Feed the PiSugar software watchdog on the coordinator thread."""
        if not self._watchdog_active or self._watchdog_feed_suppressed:
            return

        if self.power_manager is None or now < self._next_watchdog_feed_at:
            return

        feed_interval = max(1.0, float(self.power_manager.config.watchdog_feed_interval_seconds))
        if self.power_manager.feed_watchdog():
            self._next_watchdog_feed_at = now + feed_interval
            return

        self._next_watchdog_feed_at = now + min(feed_interval, 5.0)

    def _disable_watchdog(self) -> None:
        """Disable the PiSugar watchdog during intentional app shutdowns."""
        if not self._watchdog_active:
            return

        if self.power_manager is not None and self.power_manager.disable_watchdog():
            logger.info("Power watchdog disabled for intentional stop")
        else:
            logger.warning("Failed to disable power watchdog cleanly")

        self._watchdog_active = False
        self._watchdog_feed_suppressed = False
        self._next_watchdog_feed_at = 0.0

    def _suppress_watchdog_feeding(self, reason: str) -> None:
        """Stop feeding the watchdog without disabling it."""
        if not self._watchdog_active or self._watchdog_feed_suppressed:
            return

        self._watchdog_feed_suppressed = True
        logger.info(f"Power watchdog feeding suppressed: {reason}")

    def _attempt_voip_recovery(self, recovery_now: float) -> None:
        """Restart the VoIP backend when it is not running."""
        if self.voip_manager is None:
            return

        if self.voip_manager.running:
            self._voip_recovery.reset()
            return

        if recovery_now < self._voip_recovery.next_attempt_at:
            return

        logger.info("Attempting VoIP recovery")
        self._finalize_recovery_attempt(
            "VoIP",
            self._voip_recovery,
            self.voip_manager.start(),
            recovery_now,
        )

    def _start_music_backend(self) -> bool:
        """Start the current music backend using the available lifecycle API."""
        if self.music_backend is None:
            return False

        start = getattr(self.music_backend, "start", None)
        if start is not None:
            return bool(start())

        connect = getattr(self.music_backend, "connect", None)
        if connect is not None:
            return bool(connect())

        return False

    def _attempt_music_recovery(self, recovery_now: float) -> None:
        """Reconnect the music backend when it becomes unavailable."""
        if self.music_backend is None:
            return

        if self.music_backend.is_connected:
            self._music_recovery.reset()
            return

        if self._music_recovery.in_flight:
            return

        if recovery_now < self._music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self._music_recovery.in_flight = True
        self._start_music_recovery_worker(recovery_now)

    def _start_music_recovery_worker(self, recovery_now: float) -> None:
        worker = threading.Thread(
            target=self._run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def _run_music_recovery_attempt(self, recovery_now: float) -> None:
        recovered = False
        if not self._stopping and self.music_backend is not None:
            recovered = self._start_music_backend()

        self.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="music",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )

    def _finalize_recovery_attempt(
        self,
        label: str,
        state: _RecoveryState,
        recovered: bool,
        recovery_now: float,
    ) -> None:
        """Update reconnect backoff after a recovery attempt."""
        if recovered:
            logger.info(f"{label} recovery succeeded")
            state.reset()
            return

        retry_in = state.delay_seconds
        logger.warning(f"{label} recovery failed, retrying in {retry_in:.0f}s")
        state.next_attempt_at = recovery_now + retry_in
        state.delay_seconds = min(
            state.delay_seconds * 2.0,
            self._RECOVERY_MAX_DELAY_SECONDS,
        )

    def run(self) -> None:
        """Run the main application loop until interrupted."""
        logger.info("=" * 60)
        logger.info("YoyoPod Running")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Coordinator Status:")
        logger.info(f"  Current state: {self.coordinator_runtime.get_state_name()}")
        logger.info("")
        logger.info("VoIP Status:")
        if self.voip_manager:
            status = self.voip_manager.get_status()
            logger.info(f"  Running: {status['running']}")
            logger.info(f"  Registered: {status['registered']}")
            logger.info(f"  SIP Identity: {status.get('sip_identity', 'N/A')}")
        else:
            logger.info("  VoIP not available")
        logger.info("")
        logger.info("Music Status:")
        if self.music_backend and self.music_backend.is_connected:
            logger.info("  Connected: True")
            playback_state = self.music_backend.get_playback_state()
            logger.info(f"  Playback state: {playback_state}")
        else:
            logger.info("  Music backend not connected")
        logger.info("")
        logger.info("Power Status:")
        if self.power_manager:
            power_snapshot = self.power_manager.get_snapshot()
            logger.info(f"  Available: {power_snapshot.available}")
            if power_snapshot.device.model:
                logger.info(f"  Model: {power_snapshot.device.model}")
            if power_snapshot.battery.level_percent is not None:
                logger.info(f"  Battery: {power_snapshot.battery.level_percent:.1f}%")
            if power_snapshot.battery.charging is not None:
                logger.info(f"  Charging: {power_snapshot.battery.charging}")
            if power_snapshot.battery.power_plugged is not None:
                logger.info(f"  External power: {power_snapshot.battery.power_plugged}")
            logger.info(f"  Watchdog enabled: {self.power_manager.config.watchdog_enabled}")
        else:
            logger.info("  Power backend not configured")
        logger.info("")
        logger.info("Display Status:")
        if self.display is not None:
            logger.info(f"  Backend: {self.display.backend_kind}")
            logger.info(f"  Orientation: {self.display.ORIENTATION}")
        else:
            logger.info("  Display not initialized")
        logger.info("")
        logger.info("Integration Settings:")
        logger.info(f"  Auto-resume after call: {self.auto_resume_after_call}")
        logger.info("")
        logger.info("=" * 60)
        logger.info("System Status:")
        logger.info("  - VoIP and music managers are initialized")
        logger.info("  - Callbacks are registered")
        logger.info("  - State transitions will be logged")
        logger.info("  - Full screen integration active")
        logger.info("")
        logger.info("Press Ctrl+C to exit")
        logger.info("=" * 60)

        try:
            last_screen_update = time.time()
            screen_update_interval = 1.0
            self._start_watchdog(now=time.monotonic())

            if self.simulate:
                logger.info("")
                logger.info("Simulation mode: Application running...")
                logger.info("  (Incoming calls and track changes will trigger callbacks)")
                logger.info("")

            while not self._stopping:
                time.sleep(min(0.05, self._voip_iterate_interval_seconds))
                monotonic_now = time.monotonic()
                self._iterate_voip_backend_if_due(monotonic_now)
                self._process_pending_main_thread_actions()
                self._attempt_manager_recovery()
                self._poll_power_status()
                self._pump_lvgl_backend(monotonic_now)
                self._feed_watchdog_if_due(monotonic_now)
                self._process_pending_shutdown(monotonic_now)
                if self._shutdown_completed:
                    break
                self._update_screen_power(monotonic_now)

                current_time = time.time()
                overlay_active = self._update_power_overlays(monotonic_now)
                if overlay_active:
                    last_screen_update = current_time
                    continue

                if not self._screen_awake:
                    last_screen_update = current_time
                    continue

                if current_time - last_screen_update >= screen_update_interval:
                    self._update_now_playing_if_needed()
                    self._update_in_call_if_needed()
                    self._update_power_screen_if_needed()
                    last_screen_update = current_time
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("Shutting down...")
            logger.info("=" * 60)
        finally:
            if not self._shutdown_completed and not self._stopping:
                self.stop()

    def stop(self, disable_watchdog: bool = True) -> None:
        """Clean up and stop the application."""
        if self._stopped:
            return

        logger.info("Stopping YoyoPod...")
        self._stopping = True

        if disable_watchdog:
            self._disable_watchdog()

        self._ensure_coordinators()
        self.call_coordinator.cleanup()

        if self.voip_manager:
            logger.info("  - Stopping VoIP manager")
            self.voip_manager.stop(notify_events=False)

        if self.music_backend:
            logger.info("  - Stopping music backend")
            stop = getattr(self.music_backend, "stop", None)
            if stop is not None:
                stop()
            else:
                stop_polling = getattr(self.music_backend, "stop_polling", None)
                cleanup = getattr(self.music_backend, "cleanup", None)
                if stop_polling is not None:
                    stop_polling()
                if cleanup is not None:
                    cleanup()

        if self.input_manager:
            logger.info("  - Stopping input manager")
            self.input_manager.stop()

        pending_actions = self._process_pending_main_thread_actions()
        if pending_actions:
            logger.info(f"  - Processed {pending_actions} queued app events during shutdown")

        if self.display:
            logger.info("  - Clearing display")
            self.display.set_backlight(self._active_brightness)
            self.display.clear(self.display.COLOR_BLACK)
            self.display.text("Goodbye!", 70, 120, color=self.display.COLOR_CYAN, font_size=20)
            self.display.update()
            time.sleep(1)
            self.display.cleanup()

        logger.info("✓ YoyoPod stopped")

        self._stopped = True

    def get_status(self) -> Dict[str, Any]:
        """Return the current application status."""
        pending_shutdown_in_seconds = None
        if self._pending_shutdown is not None:
            pending_shutdown_in_seconds = max(
                0.0,
                self._pending_shutdown.execute_at - time.monotonic(),
            )

        power_snapshot = (
            self.power_manager.get_snapshot() if self.power_manager is not None else None
        )

        return {
            "state": self.coordinator_runtime.get_state_name(),
            "voip_registered": self.voip_registered,
            "music_was_playing": self.call_interruption_policy.music_interrupted_by_call,
            "auto_resume": self.auto_resume_after_call,
            "voip_available": self.voip_manager is not None and self.voip_manager.running,
            "music_available": self.music_backend is not None and self.music_backend.is_connected,
            "volume": self.get_output_volume(),
            "power_available": power_snapshot.available if power_snapshot is not None else False,
            "battery_percent": self.context.battery_percent if self.context else None,
            "battery_charging": self.context.battery_charging if self.context else None,
            "external_power": self.context.external_power if self.context else None,
            "missed_calls": self.context.missed_calls if self.context else 0,
            "recent_calls": self.context.recent_calls if self.context else [],
            "screen_awake": self.context.screen_awake if self.context else self._screen_awake,
            "screen_idle_seconds": self.context.screen_idle_seconds if self.context else None,
            "screen_on_seconds": self.context.screen_on_seconds if self.context else None,
            "app_uptime_seconds": self.context.app_uptime_seconds if self.context else None,
            "shutdown_pending": self._pending_shutdown is not None,
            "shutdown_reason": self._pending_shutdown.reason if self._pending_shutdown else None,
            "shutdown_in_seconds": pending_shutdown_in_seconds,
            "shutdown_completed": self._shutdown_completed,
            "warning_threshold_percent": (
                self.power_manager.config.low_battery_warning_percent
                if self.power_manager is not None
                else None
            ),
            "critical_shutdown_percent": (
                self.power_manager.config.critical_shutdown_percent
                if self.power_manager is not None
                else None
            ),
            "shutdown_delay_seconds": (
                self.power_manager.config.shutdown_delay_seconds
                if self.power_manager is not None
                else None
            ),
            "screen_timeout_seconds": self._screen_timeout_seconds,
            "display_backend": (
                getattr(self.display, "backend_kind", "pil")
                if self.display is not None
                else "unknown"
            ),
            "power_model": power_snapshot.device.model if power_snapshot is not None else None,
            "power_error": power_snapshot.error if power_snapshot is not None else None,
            "power_voltage_volts": (
                power_snapshot.battery.voltage_volts if power_snapshot is not None else None
            ),
            "power_temperature_celsius": (
                power_snapshot.battery.temperature_celsius if power_snapshot is not None else None
            ),
            "rtc_time": power_snapshot.rtc.time if power_snapshot is not None else None,
            "rtc_alarm_enabled": (
                power_snapshot.rtc.alarm_enabled if power_snapshot is not None else None
            ),
            "rtc_alarm_time": power_snapshot.rtc.alarm_time if power_snapshot is not None else None,
            "watchdog_enabled": (
                self.power_manager.config.watchdog_enabled
                if self.power_manager is not None
                else False
            ),
            "watchdog_active": self._watchdog_active,
            "watchdog_feed_suppressed": self._watchdog_feed_suppressed,
            "watchdog_timeout_seconds": (
                self.power_manager.config.watchdog_timeout_seconds
                if self.power_manager is not None
                else None
            ),
            "watchdog_feed_interval_seconds": (
                self.power_manager.config.watchdog_feed_interval_seconds
                if self.power_manager is not None
                else None
            ),
        }
