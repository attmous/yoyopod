"""
YoyoPod - Unified VoIP + Local Music Application.

Thin application shell that composes focused runtime services.
"""

from __future__ import annotations

import threading
import time
from queue import SimpleQueue
from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

from yoyopod.core import AppContext
from yoyopod.audio import (
    AudioVolumeController,
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
from yoyopod.core import EventBus
from yoyopod.core import (
    RecoveryAttemptCompletedEvent,
    ScreenChangedEvent,
    UserActivityEvent,
)
from yoyopod.device import AudioDeviceCatalog
from yoyopod.people import PeopleManager
from yoyopod.core import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopod.network import NetworkManager
from yoyopod.power import (
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
from yoyopod.runtime.event_wiring import RuntimeEventWiring
from yoyopod.ui.input import InteractionProfile
from yoyopod.cloud import CloudManager
from yoyopod.communication import CallHistoryStore, VoIPManager

if TYPE_CHECKING:
    from yoyopod.ui.display import Display
    from yoyopod.ui.input import InputManager
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
        self.people_directory: Optional[PeopleManager] = None

        # Manager components
        self.voip_manager: Optional[VoIPManager] = None
        self.music_backend: Optional[MpvBackend] = None
        self.local_music_service: Optional[LocalMusicService] = None
        self.output_volume: Optional[OutputVolumeController] = None
        self.audio_volume_controller: Optional[AudioVolumeController] = None
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
        self._pending_safety_main_thread_callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()

        # Runtime services
        self.screen_power_service = ScreenPowerService(self)
        self.recovery_service = RecoverySupervisor(self)
        self.power_runtime = PowerRuntimeService(self)
        self.shutdown_service = ShutdownLifecycleService(self)
        self.runtime_loop = RuntimeLoopService(self)
        self.event_wiring = RuntimeEventWiring(self)
        self.boot_service = RuntimeBootService(self)
        self.event_wiring.register()

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
        return self.boot_service.resolve_screen_timeout_seconds()

    def _resolve_active_brightness(self) -> float:
        return self.boot_service.resolve_active_brightness()

    def _configure_screen_power(self, initial_now: float | None = None) -> None:
        self.screen_power_service.configure_screen_power(initial_now)

    def _refresh_talk_summary(self) -> None:
        self.boot_service.refresh_talk_summary()

    def _init_core_components(self) -> bool:
        return self.boot_service.init_core_components()

    def _init_managers(self) -> bool:
        return self.boot_service.init_managers()

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

    def _setup_music_callbacks(self) -> None:
        self.boot_service.setup_music_callbacks()

    def _setup_event_subscriptions(self) -> None:
        self.boot_service.setup_event_subscriptions()

    def _pending_main_thread_callback_count(self) -> int | None:
        """Return the combined generic and safety callback backlog."""

        callback_backlog = _queue_depth(self._pending_main_thread_callbacks)
        safety_backlog = _queue_depth(self._pending_safety_main_thread_callbacks)
        if callback_backlog is None and safety_backlog is None:
            return None
        return max(0, callback_backlog or 0) + max(0, safety_backlog or 0)

    def _pump_lvgl_backend(self, now: float | None = None) -> None:
        self.runtime_loop.pump_lvgl_backend(now)

    def _iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        self.runtime_loop.iterate_voip_backend_if_due(now)

    def _handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        self.event_wiring.handle_screen_changed_event(event)

    def _queue_user_activity_event(self, action: Any, _data: Any | None = None) -> None:
        self.screen_power_service.queue_user_activity_event(action, _data)

    def _handle_user_activity_event(self, event: UserActivityEvent) -> None:
        self.event_wiring.handle_user_activity_event(event)

    def _handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        self.event_wiring.handle_recovery_attempt_completed_event(event)

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

    def get_status(self, *, refresh_output_volume: bool = False) -> dict[str, Any]:
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
            "volume": (
                self.audio_volume_controller.get_output_volume(
                    refresh_system=refresh_output_volume
                )
                if self.audio_volume_controller is not None
                else (
                    self.context.media.playback.volume
                    if self.context is not None
                    else None
                )
            ),
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
            "battery_percent": self.context.power.battery_percent if self.context else None,
            "battery_charging": self.context.power.battery_charging if self.context else None,
            "external_power": self.context.power.external_power if self.context else None,
            "missed_calls": self.context.talk.missed_calls if self.context else 0,
            "recent_calls": self.context.talk.recent_calls if self.context else [],
            "screen_awake": self.context.screen.awake if self.context else self._screen_awake,
            "screen_idle_seconds": self.context.screen.idle_seconds if self.context else None,
            "screen_on_seconds": self.context.screen.on_seconds if self.context else None,
            "app_uptime_seconds": self.context.screen.app_uptime_seconds if self.context else None,
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
