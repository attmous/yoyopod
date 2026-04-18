"""
YoyoPod - Unified VoIP + Local Music Application.

Thin application shell that composes focused runtime services.
"""

from __future__ import annotations

import threading
import time
from queue import SimpleQueue
from typing import Any, Callable, Optional

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod.audio import (
    LocalMusicService,
    MpvBackend,
    OutputVolumeController,
    RecentTrackHistoryStore,
)
from yoyopod.config import ConfigManager, MediaConfig, YoyoPodConfig
from yoyopod.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)
from yoyopod.event_bus import EventBus
from yoyopod.events import (
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkSignalUpdateEvent,
    RecoveryAttemptCompletedEvent,
    ScreenChangedEvent,
    UserActivityEvent,
)
from yoyopod.device import AudioDeviceCatalog
from yoyopod.people import PeopleDirectory
from yoyopod.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopod.network import NetworkManager
from yoyopod.power import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
    PowerManager,
    PowerRuntimeService,
)
from yoyopod.runtime import (
    PendingShutdown,
    PowerAlert,
    RecoveryState,
    RecoverySupervisor,
    RuntimeBootService,
    RuntimeLoopService,
    ScreenPowerService,
    ShutdownLifecycleService,
    VoiceRuntimeCoordinator,
)
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputManager, InteractionProfile
from yoyopod.ui.lvgl_binding import LvglDisplayBackend, LvglInputBridge
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
from yoyopod.cloud import CloudManager
from yoyopod.communication import CallHistoryStore, VoIPManager


def _queue_depth(queue_obj: object) -> int | None:
    """Return a best-effort queue depth for runtime diagnostics."""

    qsize = getattr(queue_obj, "qsize", None)
    if not callable(qsize):
        return None

    try:
        return int(qsize())
    except (NotImplementedError, TypeError, ValueError):
        return None


class YoyoPodApp:
    """
    Main YoyoPod application coordinator.

    The app keeps runtime state and compatibility helpers while delegating boot,
    loop scheduling, recovery, screen power, and shutdown behavior to dedicated
    runtime services.
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
        self.media_settings: Optional[MediaConfig] = None
        self.screen_manager: Optional[ScreenManager] = None
        self.input_manager: Optional[InputManager] = None
        self.people_directory: Optional[PeopleDirectory] = None

        # Manager components
        self.voip_manager: Optional[VoIPManager] = None
        self.music_backend: Optional[MpvBackend] = None
        self.local_music_service: Optional[LocalMusicService] = None
        self.output_volume: Optional[OutputVolumeController] = None
        self.power_manager: Optional[PowerManager] = None
        self.network_manager: Optional[NetworkManager] = None
        self.call_history_store: Optional[CallHistoryStore] = None
        self.recent_track_store: Optional[RecentTrackHistoryStore] = None
        self.audio_device_catalog: Optional[AudioDeviceCatalog] = None
        self.voice_runtime: Optional[VoiceRuntimeCoordinator] = None

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

        # Cloud / backend runtime
        self.cloud_manager: Optional[CloudManager] = None

        # Extracted coordinators
        self.coordinator_runtime: Optional[CoordinatorRuntime] = None
        self.screen_coordinator: Optional[ScreenCoordinator] = None
        self.call_coordinator: Optional[CallCoordinator] = None
        self.playback_coordinator: Optional[PlaybackCoordinator] = None
        self.power_coordinator: Optional[PowerCoordinator] = None

        # Runtime state tracked across services
        self._voip_recovery = RecoveryState()
        self._music_recovery = RecoveryState()
        self._next_power_poll_at = 0.0
        self._power_available: bool | None = None
        self._power_alert: PowerAlert | None = None
        self._pending_shutdown: PendingShutdown | None = None
        self._power_hooks_registered = False
        self._shutdown_completed = False
        self._stopping = False
        self._app_started_at = 0.0
        self._last_user_activity_at = 0.0
        self._last_input_activity_at = 0.0
        self._last_input_activity_action_name: str | None = None
        self._last_input_handled_at = 0.0
        self._last_input_handled_action_name: str | None = None
        self._screen_on_started_at: float | None = 0.0
        self._screen_on_accumulated_seconds = 0.0
        self._screen_timeout_seconds = 0.0
        self._active_brightness = 1.0
        self._screen_awake = True
        self._watchdog_active = False
        self._watchdog_feed_suppressed = False
        self._watchdog_feed_in_flight = False
        self._next_watchdog_feed_at = 0.0
        self._power_refresh_in_flight = False
        self._stopped = False
        self._lvgl_backend: Optional[LvglDisplayBackend] = None
        self._lvgl_input_bridge: Optional[LvglInputBridge] = None
        self._last_lvgl_pump_at = 0.0
        self._last_loop_heartbeat_at = 0.0
        self._last_responsiveness_capture_at = 0.0
        self._last_responsiveness_capture_reason: str | None = None
        self._last_responsiveness_capture_scope: str | None = None
        self._last_responsiveness_capture_summary: str | None = None
        self._last_responsiveness_capture_artifacts: dict[str, str] = {}
        self._next_voip_iterate_at = 0.0
        self._voip_iterate_interval_seconds = 0.02

        # Main-thread event bus and queued callbacks
        self._main_thread_id = threading.get_ident()
        self.event_bus = EventBus(main_thread_id=self._main_thread_id)
        self._pending_main_thread_callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._pending_safety_main_thread_callbacks: SimpleQueue[Callable[[], None]] = (
            SimpleQueue()
        )

        # Runtime services
        self.screen_power_service = ScreenPowerService(self)
        self.recovery_service = RecoverySupervisor(self)
        self.power_runtime = PowerRuntimeService(self)
        self.shutdown_service = ShutdownLifecycleService(self)
        self.runtime_loop = RuntimeLoopService(self)
        self.boot_service = RuntimeBootService(self)

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
        self.event_bus.subscribe(NetworkPppUpEvent, self._handle_network_ppp_up)
        self.event_bus.subscribe(NetworkSignalUpdateEvent, self._handle_network_signal_update)
        self.event_bus.subscribe(NetworkGpsFixEvent, self._handle_network_gps_fix)
        self.event_bus.subscribe(NetworkGpsNoFixEvent, self._handle_network_gps_no_fix)
        self.event_bus.subscribe(NetworkPppDownEvent, self._handle_network_ppp_down)

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
        """Initialize all components and register callbacks."""
        return self.boot_service.setup()

    def _load_configuration(self) -> bool:
        return self.boot_service.load_configuration()

    def _resolve_screen_timeout_seconds(self) -> float:
        return self.screen_power_service.resolve_screen_timeout_seconds()

    def _resolve_active_brightness(self) -> float:
        return self.screen_power_service.resolve_active_brightness()

    def _configure_screen_power(self, initial_now: float | None = None) -> None:
        self.screen_power_service.configure_screen_power(initial_now)

    def _refresh_talk_summary(self) -> None:
        self.boot_service.refresh_talk_summary()

    def _init_core_components(self) -> bool:
        return self.boot_service.init_core_components()

    def _init_managers(self) -> bool:
        return self.boot_service.init_managers()

    def _resolve_default_music_volume(self) -> int:
        """Return the configured startup volume for the music backend."""
        media_cfg = self.media_settings
        raw_volume = media_cfg.music.default_volume if media_cfg else 100
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

    def get_output_volume(self, *, refresh_system: bool = True) -> int | None:
        """Return the current shared output volume."""
        if self.output_volume is not None:
            volume = (
                self.output_volume.get_volume()
                if refresh_system
                else self.output_volume.peek_cached_volume()
            )
            if self.context is not None and volume is not None:
                self.context.playback.volume = volume
                self.context.voice.output_volume = volume
            if volume is not None:
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
        return self.boot_service.setup_screens()

    def _get_interaction_profile(self) -> InteractionProfile:
        return self.boot_service.get_interaction_profile()

    def _get_initial_screen_name(self) -> str:
        return self.boot_service.get_initial_screen_name()

    def _get_initial_ui_state(self) -> AppRuntimeState:
        return self.boot_service.get_initial_ui_state()

    def _setup_voip_callbacks(self) -> None:
        self.boot_service.setup_voip_callbacks()

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

    def _handle_voice_note_activity_changed(self, *_args: Any) -> None:
        """Refresh active draft state after a message or delivery update."""
        self._sync_active_voice_note_context()
        self._refresh_talk_summary()
        self._refresh_talk_related_screen()

    def _handle_voice_note_failure(self, *_args: Any) -> None:
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

    def _setup_music_callbacks(self) -> None:
        self.boot_service.setup_music_callbacks()

    def _setup_event_subscriptions(self) -> None:
        self.boot_service.setup_event_subscriptions()

    def _process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        return self.runtime_loop.process_pending_main_thread_actions(limit)

    def _queue_main_thread_callback(
        self,
        callback: Callable[[], None],
        *,
        safety: bool = False,
    ) -> None:
        self.runtime_loop.queue_main_thread_callback(callback, safety=safety)

    def _pending_main_thread_callback_count(self) -> int | None:
        """Return the combined generic and safety callback backlog."""

        callback_backlog = _queue_depth(self._pending_main_thread_callbacks)
        safety_backlog = _queue_depth(self._pending_safety_main_thread_callbacks)
        if callback_backlog is None and safety_backlog is None:
            return None
        return max(0, callback_backlog or 0) + max(0, safety_backlog or 0)

    def _queue_lvgl_input_action(self, action: Any, _data: Optional[Any] = None) -> None:
        self.runtime_loop.queue_lvgl_input_action(action, _data)

    def _pump_lvgl_backend(self, now: float | None = None) -> None:
        self.runtime_loop.pump_lvgl_backend(now)

    def _iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        self.runtime_loop.iterate_voip_backend_if_due(now)

    def _handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        self.screen_power_service.handle_screen_changed_event(event)

    def _queue_user_activity_event(self, action: Any, _data: Any | None = None) -> None:
        self.screen_power_service.queue_user_activity_event(action, _data)

    def _handle_user_activity_event(self, event: UserActivityEvent) -> None:
        self.screen_power_service.handle_user_activity_event(event)

    def _handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        self.recovery_service.handle_recovery_attempt_completed_event(event)

    def _handle_low_battery_warning_event(self, event: LowBatteryWarningRaised) -> None:
        self.screen_power_service.handle_low_battery_warning_event(event)

    def _handle_graceful_shutdown_requested_event(
        self,
        event: GracefulShutdownRequested,
    ) -> None:
        self.shutdown_service.handle_graceful_shutdown_requested_event(event)

    def _handle_graceful_shutdown_cancelled_event(
        self,
        event: GracefulShutdownCancelled,
    ) -> None:
        self.shutdown_service.handle_graceful_shutdown_cancelled_event(event)

    def _cellular_connection_type(self) -> str:
        """Return a best-effort cellular connection type for degraded status chrome."""
        if self.network_manager is None or not self.network_manager.config.enabled:
            return "none"

        from yoyopod.network.models import ModemPhase

        state = self.network_manager.modem_state
        if state.phase == ModemPhase.OFF:
            return "none"
        return "4g"

    def _sync_network_context_from_manager(self) -> None:
        """Refresh AppContext network state from the current modem snapshot."""
        if self.context is None or self.network_manager is None:
            return

        state = self.network_manager.modem_state
        signal_bars = state.signal.bars if state.signal is not None else 0
        self.context.update_network_status(
            network_enabled=self.network_manager.config.enabled,
            signal_bars=signal_bars,
            connection_type=self._cellular_connection_type(),
            connected=self.network_manager.is_online,
            gps_has_fix=state.gps is not None,
        )

    def _handle_network_ppp_up(self, event: NetworkPppUpEvent) -> None:
        """Refresh network connectivity state when PPP comes online."""
        if self.cloud_manager is not None:
            self.cloud_manager.note_network_change(connected=True)
        if self.network_manager is not None:
            self._sync_network_context_from_manager()
            return
        if self.context is not None:
            self.context.update_network_status(
                network_enabled=True,
                connected=True,
                connection_type=event.connection_type,
            )

    def _handle_network_signal_update(self, event: NetworkSignalUpdateEvent) -> None:
        """Refresh signal bars when the modem reports new telemetry."""
        if self.network_manager is not None:
            self._sync_network_context_from_manager()
            return
        if self.context is not None:
            connection_type = self.context.connection_type
            if connection_type == "none":
                connection_type = "4g"
            self.context.update_network_status(
                network_enabled=True,
                signal_bars=event.bars,
                connection_type=connection_type,
            )

    def _handle_network_gps_fix(self, event: NetworkGpsFixEvent) -> None:
        """Update GPS fix state in AppContext."""
        if self.network_manager is not None:
            self._sync_network_context_from_manager()
            return
        if self.context is not None:
            connection_type = self.context.connection_type
            if connection_type == "none":
                connection_type = "4g"
            self.context.update_network_status(
                network_enabled=True,
                connection_type=connection_type,
                gps_has_fix=True,
            )

    def _handle_network_gps_no_fix(self, _event: NetworkGpsNoFixEvent) -> None:
        """Clear GPS fix state when a query completes without coordinates."""
        if self.network_manager is not None:
            self._sync_network_context_from_manager()
            return
        if self.context is not None:
            self.context.update_network_status(gps_has_fix=False)

    def _handle_network_ppp_down(self, _event: NetworkPppDownEvent) -> None:
        """Reset network state in AppContext when PPP drops."""
        if self.cloud_manager is not None:
            self.cloud_manager.note_network_change(connected=False)
        if self.network_manager is not None:
            self._sync_network_context_from_manager()
            return
        if self.context is not None:
            self.context.update_network_status(
                network_enabled=True,
                connected=False,
                gps_has_fix=False,
            )

    def _register_power_shutdown_hooks(self) -> None:
        self.shutdown_service.register_power_shutdown_hooks()

    def _save_shutdown_state(self) -> None:
        self.shutdown_service.save_shutdown_state()

    def _ensure_coordinators(self) -> None:
        self.boot_service.ensure_coordinators()

    def _pop_call_screens(self) -> None:
        """Compatibility wrapper for clearing call-related screens."""
        self._ensure_coordinators()
        assert self.screen_coordinator is not None
        self.screen_coordinator.pop_call_screens()

    def _update_now_playing_if_needed(self) -> None:
        """Compatibility wrapper for periodic now-playing refreshes."""
        self._ensure_coordinators()
        assert self.playback_coordinator is not None
        self.playback_coordinator.update_now_playing_if_needed()

    def _update_in_call_if_needed(self) -> None:
        """Refresh the in-call screen from the main loop when it is visible."""
        self._ensure_coordinators()
        assert self.screen_coordinator is not None
        self.screen_coordinator.update_in_call_if_needed()

    def _update_power_screen_if_needed(self) -> None:
        """Refresh the power screen from the main loop when it is visible."""
        self._ensure_coordinators()
        assert self.screen_coordinator is not None
        self.screen_coordinator.update_power_screen_if_needed()

    def _start_ringing(self) -> None:
        """Compatibility wrapper for starting the call ring tone."""
        self._ensure_coordinators()
        assert self.call_coordinator is not None
        self.call_coordinator.start_ringing()

    def _stop_ringing(self) -> None:
        """Compatibility wrapper for stopping the call ring tone."""
        self._ensure_coordinators()
        assert self.call_coordinator is not None
        self.call_coordinator.stop_ringing()

    def _handle_screen_changed(self, screen_name: str | None) -> None:
        """Marshal screen-state sync work onto the coordinator thread."""
        self.event_bus.publish(ScreenChangedEvent(screen_name=screen_name))

    def note_input_activity(self, action: object, _data: Any | None = None) -> None:
        """Record raw or semantic input activity before the coordinator drains it."""

        self._last_input_activity_at = time.monotonic()
        self._last_input_activity_action_name = getattr(action, "value", None)

    def record_responsiveness_capture(
        self,
        *,
        captured_at: float,
        reason: str,
        suspected_scope: str,
        summary: str,
        artifacts: dict[str, str] | None = None,
    ) -> None:
        """Persist the latest automatic hang-evidence capture metadata."""

        self._last_responsiveness_capture_at = captured_at
        self._last_responsiveness_capture_reason = reason
        self._last_responsiveness_capture_scope = suspected_scope
        self._last_responsiveness_capture_summary = summary
        self._last_responsiveness_capture_artifacts = dict(artifacts or {})

    def _sync_screen_changed(self, screen_name: str | None) -> None:
        """Keep the derived base UI state aligned with the active screen."""
        self._ensure_coordinators()
        assert self.coordinator_runtime is not None
        self.coordinator_runtime.sync_ui_state_for_screen(screen_name)

    def _mark_user_activity(
        self,
        *,
        now: float | None = None,
        render_on_wake: bool,
    ) -> None:
        self.screen_power_service.mark_user_activity(
            now=now,
            render_on_wake=render_on_wake,
        )

    def _wake_screen(self, now: float, *, render_current: bool) -> None:
        self.screen_power_service.wake_screen(now, render_current=render_current)

    def _sleep_screen(self, now: float) -> None:
        self.screen_power_service.sleep_screen(now)

    def _update_screen_runtime_metrics(self, now: float) -> None:
        self.screen_power_service.update_screen_runtime_metrics(now)

    def _update_screen_power(self, now: float) -> None:
        self.screen_power_service.update_screen_power(now)

    def _attempt_manager_recovery(self, now: float | None = None) -> None:
        self.recovery_service.attempt_manager_recovery(now)

    def _poll_power_status(self, now: float | None = None, force: bool = False) -> None:
        self.power_runtime.poll_status(now=now, force=force)

    def _set_power_alert(
        self,
        *,
        title: str,
        subtitle: str,
        color: tuple[int, int, int],
        duration_seconds: float,
    ) -> None:
        self.screen_power_service.set_power_alert(
            title=title,
            subtitle=subtitle,
            color=color,
            duration_seconds=duration_seconds,
        )

    def _render_power_overlay(self, title: str, subtitle: str, color: tuple[int, int, int]) -> None:
        self.screen_power_service.render_power_overlay(title, subtitle, color)

    def _update_power_overlays(self, now: float) -> bool:
        return self.screen_power_service.update_power_overlays(now)

    def _process_pending_shutdown(self, now: float) -> None:
        self.shutdown_service.process_pending_shutdown(now)

    def _execute_pending_shutdown(self) -> None:
        self.shutdown_service.execute_pending_shutdown()

    def _start_watchdog(self, now: float | None = None) -> None:
        self.power_runtime.start_watchdog(now=now)

    def _feed_watchdog_if_due(self, now: float) -> None:
        self.power_runtime.feed_watchdog_if_due(now)

    def _disable_watchdog(self) -> None:
        self.power_runtime.disable_watchdog()

    def _suppress_watchdog_feeding(self, reason: str) -> None:
        self.power_runtime.suppress_watchdog_feeding(reason)

    def _attempt_voip_recovery(self, recovery_now: float) -> None:
        self.recovery_service.attempt_voip_recovery(recovery_now)

    def _start_music_backend(self) -> bool:
        return self.recovery_service.start_music_backend()

    def _attempt_music_recovery(self, recovery_now: float) -> None:
        self.recovery_service.attempt_music_recovery(recovery_now)

    def _start_music_recovery_worker(self, recovery_now: float) -> None:
        self.recovery_service.start_music_recovery_worker(recovery_now)

    def _run_music_recovery_attempt(self, recovery_now: float) -> None:
        self.recovery_service.run_music_recovery_attempt(recovery_now)

    def _finalize_recovery_attempt(
        self,
        label: str,
        state: RecoveryState,
        recovered: bool,
        recovery_now: float,
    ) -> None:
        self.recovery_service.finalize_recovery_attempt(
            label=label,
            state=state,
            recovered=recovered,
            recovery_now=recovery_now,
        )

    def run(self) -> None:
        """Run the main application loop until interrupted."""
        self.runtime_loop.run()

    def stop(self, disable_watchdog: bool = True) -> None:
        """Clean up and stop the application."""
        self.shutdown_service.stop(disable_watchdog=disable_watchdog)

    def get_status(self, *, refresh_output_volume: bool = False) -> Dict[str, Any]:
        """Return the current application status."""
        monotonic_now = time.monotonic()
        pending_shutdown_in_seconds = None
        if self._pending_shutdown is not None:
            pending_shutdown_in_seconds = max(
                0.0,
                self._pending_shutdown.execute_at - monotonic_now,
            )

        assert self.coordinator_runtime is not None
        assert self.call_interruption_policy is not None
        current_screen = (
            self.screen_manager.get_current_screen() if self.screen_manager is not None else None
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
            "volume": self.get_output_volume(refresh_system=refresh_output_volume),
            "power_available": power_snapshot.available if power_snapshot is not None else False,
            "current_screen": getattr(current_screen, "route_name", None),
            "screen_stack_depth": (
                len(self.screen_manager.screen_stack) if self.screen_manager is not None else 0
            ),
            "input_manager_running": (
                self.input_manager.running if self.input_manager is not None else False
            ),
            "pending_main_thread_callbacks": self._pending_main_thread_callback_count(),
            "pending_event_bus_events": self.event_bus.pending_count(),
            "input_activity_age_seconds": (
                max(0.0, monotonic_now - self._last_input_activity_at)
                if self._last_input_activity_at > 0.0
                else None
            ),
            "last_input_action": self._last_input_activity_action_name,
            "handled_input_activity_age_seconds": (
                max(0.0, monotonic_now - self._last_input_handled_at)
                if self._last_input_handled_at > 0.0
                else None
            ),
            "last_handled_input_action": self._last_input_handled_action_name,
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
            "lvgl_initialized": bool(
                self._lvgl_backend is not None and self._lvgl_backend.initialized
            ),
            "lvgl_pump_age_seconds": (
                max(0.0, monotonic_now - self._last_lvgl_pump_at)
                if self._last_lvgl_pump_at > 0.0
                else None
            ),
            "loop_heartbeat_age_seconds": (
                max(0.0, monotonic_now - self._last_loop_heartbeat_at)
                if self._last_loop_heartbeat_at > 0.0
                else None
            ),
            "next_voip_iterate_in_seconds": (
                max(0.0, self._next_voip_iterate_at - monotonic_now)
                if (
                    self.voip_manager is not None
                    and self.voip_manager.running
                    and self._next_voip_iterate_at > 0.0
                )
                else None
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
            "watchdog_feed_in_flight": self._watchdog_feed_in_flight,
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
            "power_refresh_in_flight": self._power_refresh_in_flight,
            "responsiveness_watchdog_enabled": bool(
                getattr(
                    getattr(self.app_settings, "diagnostics", None),
                    "responsiveness_watchdog_enabled",
                    False,
                )
            ),
            "responsiveness_capture_dir": (
                getattr(
                    getattr(self.app_settings, "diagnostics", None),
                    "responsiveness_capture_dir",
                    None,
                )
            ),
            "responsiveness_last_capture_age_seconds": (
                max(0.0, monotonic_now - self._last_responsiveness_capture_at)
                if self._last_responsiveness_capture_at > 0.0
                else None
            ),
            "responsiveness_last_capture_reason": self._last_responsiveness_capture_reason,
            "responsiveness_last_capture_scope": self._last_responsiveness_capture_scope,
            "responsiveness_last_capture_summary": self._last_responsiveness_capture_summary,
            "responsiveness_last_capture_artifacts": dict(
                self._last_responsiveness_capture_artifacts
            ),
            **self.runtime_loop.timing_snapshot(now=monotonic_now),
        }
