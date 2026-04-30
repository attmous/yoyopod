"""Canonical application object for YoYoPod."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.core.audio_volume import AudioVolumeController
from yoyopod.backends.music import MpvBackend
from yoyopod.config import ConfigManager, MediaConfig, YoyoPodConfig
from yoyopod.core.app_context import AppContext
from yoyopod.core.background import BackgroundExecutor
from yoyopod.core.bus import Bus
from yoyopod.core.audio_volume import OutputVolumeController
from yoyopod.core.events import LifecycleEvent
from yoyopod.core.hardware import AudioDeviceCatalog
from yoyopod.core.logbuffer import LogBuffer
from yoyopod.core.overlays import CrossScreenOverlayRuntime
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.services import Services
from yoyopod.core.states import States
from yoyopod.core.app_state import AppStateRuntime
from yoyopod.integrations.call import (
    CallFSM,
    CallInterruptionPolicy,
    VoIPManager,
)
from yoyopod.integrations.call.runtime import CallRuntime
from yoyopod.integrations.cloud.manager import CloudManager
from yoyopod.integrations.contacts.directory import PeopleManager
from yoyopod.integrations.music import LocalMusicService, MusicFSM, RecentTrackHistoryStore
from yoyopod.integrations.music.runtime import MusicRuntime
from yoyopod.integrations.network import NetworkManager
from yoyopod.integrations.power import (
    PendingShutdown,
    PowerAlert,
    PowerManager,
    PowerRuntimeService,
)
from yoyopod.core.bootstrap import RuntimeBootService
from yoyopod.core.event_subscriptions import RuntimeEventSubscriptions
from yoyopod.core.loop import RuntimeLoopService
from yoyopod.core.status import RuntimeMetricsStore
from yoyopod.core.recovery import RecoveryState, RuntimeRecoveryService
from yoyopod.core.workers import WorkerSupervisor
from yoyopod.integrations.call import VoiceNoteEventHandler
from yoyopod.integrations.network import NetworkEventHandler
from yoyopod.integrations.display import ScreenPowerService
from yoyopod.integrations.voice.runtime import VoiceRuntimeCoordinator
from yoyopod.integrations.voice.worker_client import VoiceWorkerClient
from yoyopod.core.shutdown import ShutdownLifecycleService
from yoyopod.core.status import RuntimeStatusService

if TYPE_CHECKING:
    from yoyopod.ui.display import Display
    from yoyopod.ui.input import InputManager
    from yoyopod.ui.lvgl_binding import LvglDisplayBackend, LvglInputBridge
    from yoyopod.ui.screens.manager import ScreenManager
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


@dataclass(slots=True)
class _RegisteredIntegration:
    """One scaffold integration registration owned by the core application."""

    name: str
    setup: Callable[["YoyoPodApp"], None]
    teardown: Callable[["YoyoPodApp"], None] | None = None


class YoyoPodApp:
    """Canonical app object that owns both the scaffold spine and live runtime shell."""

    _RECOVERY_MAX_DELAY_SECONDS = 30.0

    def __init__(
        self,
        config_dir: str = "config",
        simulate: bool = False,
        *,
        strict_bus: bool = False,
        log_buffer_size: int = 256,
    ) -> None:
        self.config_dir = config_dir
        self.simulate = simulate

        # Frozen scaffold primitives
        self.main_thread_id = threading.get_ident()
        self.log_buffer: LogBuffer[dict[str, object]] = LogBuffer(maxlen=log_buffer_size)
        self.bus = Bus(main_thread_id=self.main_thread_id, strict=strict_bus)
        self.scheduler = MainThreadScheduler(main_thread_id=self.main_thread_id)
        self.background = BackgroundExecutor(self.scheduler, diagnostics_log=self.log_buffer)
        self.services = Services(self.bus, diagnostics_log=self.log_buffer)
        self.states = States(self.bus)
        self.config: object | None = None
        self.integrations: dict[str, object] = {}
        self.running = False
        self._setup_complete = False
        # Test-only scaffold seam used by focused core/integration tests.
        self._registered_integrations: list[_RegisteredIntegration] = []
        self._tick_durations_ms: deque[float] = deque(maxlen=100)
        self._tick_queue_depths: deque[int] = deque(maxlen=100)
        self._ui_tick_callback: Callable[[], None] | None = None
        self._legacy_setup_complete = False

        # Legacy runtime shell state still being collapsed into the frozen layout
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
        self.call_history_store: object | None = None
        self.recent_track_store: Optional[RecentTrackHistoryStore] = None
        self.audio_device_catalog: Optional[AudioDeviceCatalog] = None
        self.voice_runtime: Optional[VoiceRuntimeCoordinator] = None
        self.voice_worker_client: VoiceWorkerClient | None = None
        self.rust_ui_host: object | None = None

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

        # Cloud / backend runtime
        self.cloud_manager: Optional[CloudManager] = None

        # Extracted coordinators
        self.app_state_runtime: Optional[AppStateRuntime] = None
        self.call_runtime: Optional[CallRuntime] = None
        self.music_runtime: Optional[MusicRuntime] = None

        # Runtime state tracked across services
        self._voip_recovery = RecoveryState()
        self._music_recovery = RecoveryState()
        self._network_recovery = RecoveryState()
        self._next_power_poll_at = 0.0
        self._power_available: bool | None = None
        self._power_alert: PowerAlert | None = None
        self._pending_shutdown: PendingShutdown | None = None
        self._power_hooks_registered = False
        self._shutdown_completed = False
        self._stopping = False
        self._app_started_at = 0.0
        self._last_user_activity_at = 0.0
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
        self._next_voip_iterate_at = 0.0
        self._voip_iterate_interval_seconds = 0.02

        self.runtime_metrics = RuntimeMetricsStore()
        self.cross_screen_overlays = CrossScreenOverlayRuntime()
        self.worker_supervisor = WorkerSupervisor(scheduler=self.scheduler, bus=self.bus)

        # Runtime services
        self.screen_power_service = ScreenPowerService(self)
        self.cross_screen_overlays.register(self.screen_power_service)
        self.recovery_service = RuntimeRecoveryService(self)
        self.power_runtime = PowerRuntimeService(self)
        self.shutdown_service = ShutdownLifecycleService(self)
        self.voice_note_events = VoiceNoteEventHandler(self)
        self.network_events = NetworkEventHandler(self)
        self.runtime_loop = RuntimeLoopService(self)
        self.boot_service = RuntimeBootService(self)
        self.status_service = RuntimeStatusService(self)
        self.event_subscriptions = RuntimeEventSubscriptions(self)
        self.event_subscriptions.register()

        logger.info("=" * 60)
        logger.info("YoYoPod Application Initializing")
        logger.info("=" * 60)

    @property
    def voip_registered(self) -> bool:
        """Expose the current VoIP registration state for compatibility."""

        if self.call_runtime is not None:
            return self.call_runtime.voip_registered
        return self._voip_registered

    @voip_registered.setter
    def voip_registered(self, value: bool) -> None:
        """Store VoIP registration state before or after coordinators are initialized."""

        self._voip_registered = value
        if self.call_runtime is not None:
            self.call_runtime.voip_registered = value

    def set_ui_tick_callback(self, callback: Callable[[], None] | None) -> None:
        """Replace the optional scaffold UI tick callback."""

        self._ui_tick_callback = callback

    def register_integration(
        self,
        name: str,
        *,
        setup: Callable[["YoyoPodApp"], None],
        teardown: Callable[["YoyoPodApp"], None] | None = None,
    ) -> None:
        """Register one test-only scaffold integration for explicit setup/teardown."""

        if self._setup_complete:
            raise RuntimeError(f"Cannot register integration {name!r} after setup()")
        self._registered_integrations.append(
            _RegisteredIntegration(name=name, setup=setup, teardown=teardown)
        )

    def setup(self) -> bool:
        """Initialize scaffold registrations or the live runtime, depending on use."""

        if self._registered_integrations:
            # Focused scaffold tests use explicit registrations; production boot
            # should flow through RuntimeBootService instead.
            if self._setup_complete:
                return True
            for integration in self._registered_integrations:
                self.bus.publish(LifecycleEvent(phase="setup_start", detail=integration.name))
                integration.setup(self)
                self.bus.publish(LifecycleEvent(phase="setup_complete", detail=integration.name))
            self._setup_complete = True
            return True

        result = self.boot_service.setup()
        if result:
            self._legacy_setup_complete = True
            self.config = self.app_settings
        return result

    def start(self) -> None:
        """Mark the scaffold application as running and queue lifecycle events."""

        self.running = True
        self.bus.publish(LifecycleEvent(phase="starting"))
        self.bus.publish(LifecycleEvent(phase="ready"))

    def stop(self, disable_watchdog: bool = True) -> None:
        """Stop scaffold integrations or the live runtime, depending on initialized state."""

        if self._stopped:
            return

        self.bus.publish(LifecycleEvent(phase="stopping"))
        self.worker_supervisor.stop_all(grace_seconds=1.0)
        self._teardown_registered_integrations()

        if self._legacy_setup_complete or self._has_runtime_resources():
            self.shutdown_service.stop(disable_watchdog=disable_watchdog)
        else:
            self.running = False
            self._stopped = True

        self.running = False
        self._stopped = True
        self.bus.publish(LifecycleEvent(phase="stopped"))
        # Drain main-thread queues BEFORE closing the background pools so that
        # completion callbacks running on the scheduler (e.g. cloud
        # _complete_fetch_remote_config -> _maybe_bootstrap_local_contacts ->
        # _start_worker) can submit follow-up background work without hitting
        # a closed executor. After background.shutdown() we drain again to
        # absorb any done-callbacks fired by cancel_futures.
        self.scheduler.drain()
        self.bus.drain()
        self.background.shutdown()
        self.scheduler.drain()
        self.bus.drain()

    def tick(self) -> int:
        """Advance one scheduler-plus-bus turn and optionally tick the scaffold UI."""

        started_at = time.perf_counter()
        queue_depth = self.scheduler.pending_count() + self.bus.pending_count()
        processed = self.scheduler.drain()
        processed += self.bus.drain()
        if self._ui_tick_callback is not None:
            self._ui_tick_callback()
        self._tick_durations_ms.append((time.perf_counter() - started_at) * 1000.0)
        self._tick_queue_depths.append(queue_depth)
        return processed

    def tick_stats_snapshot(self) -> dict[str, float | int]:
        """Return a compact summary of recent tick durations and queue depths."""

        durations = list(self._tick_durations_ms)
        queue_depths = list(self._tick_queue_depths)
        return {
            "sample_count": len(durations),
            "drain_ms_p50": _percentile(durations, 0.50),
            "drain_ms_p99": _percentile(durations, 0.99),
            "queue_depth_max": max(queue_depths, default=0),
        }

    def run(
        self,
        *,
        sleep_seconds: float = 0.01,
        max_iterations: int | None = None,
    ) -> int | None:
        """Run the scaffold loop or the live runtime loop, depending on initialized state."""

        if max_iterations is None and self._legacy_setup_complete:
            self.runtime_loop.run()
            return None

        iterations = 0
        total_processed = 0
        if not self.running:
            self.start()

        while self.running:
            total_processed += self.tick()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(sleep_seconds)

        return total_processed

    def _pending_main_thread_callback_count(self) -> int | None:
        """Return the queued main-thread scheduler backlog."""

        return self.scheduler.pending_count()

    def note_input_activity(
        self,
        action: object,
        _data: Any | None = None,
        *,
        captured_at: float | None = None,
    ) -> None:
        """Record raw or semantic input activity before the coordinator drains it."""

        self.runtime_metrics.note_input_activity(action, _data, captured_at=captured_at)

    def note_handled_input(
        self,
        *,
        action_name: str | None,
        handled_at: float,
    ) -> None:
        """Record semantic user activity after the coordinator handles it."""

        self.runtime_metrics.note_handled_input(
            action_name=action_name,
            handled_at=handled_at,
        )

    def note_visible_refresh(self, *, refreshed_at: float) -> None:
        """Record that a visible screen refresh happened on the coordinator thread."""

        self.runtime_metrics.note_visible_refresh(refreshed_at=refreshed_at)

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

        self.runtime_metrics.record_responsiveness_capture(
            captured_at=captured_at,
            reason=reason,
            suspected_scope=suspected_scope,
            summary=summary,
            artifacts=artifacts,
        )

    def get_status(self, *, refresh_output_volume: bool = False) -> dict[str, Any]:
        """Return the current application status."""

        return self.status_service.get_status(refresh_output_volume=refresh_output_volume)

    def _teardown_registered_integrations(self) -> None:
        for integration in reversed(self._registered_integrations):
            if integration.teardown is None:
                continue
            self.bus.publish(LifecycleEvent(phase="teardown_start", detail=integration.name))
            integration.teardown(self)
            self.bus.publish(LifecycleEvent(phase="teardown_complete", detail=integration.name))

    def _has_runtime_resources(self) -> bool:
        return any(
            resource is not None
            for resource in (
                self.display,
                self.context,
                self.config_manager,
                self.screen_manager,
                self.input_manager,
                self.voip_manager,
                self.music_backend,
                self.local_music_service,
                self.power_manager,
                self.network_manager,
                self.cloud_manager,
            )
        )


def _percentile(values: list[float], ratio: float) -> float:
    """Return one percentile from a non-empty list of values."""

    if not values:
        return 0.0

    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * ratio))
    return ordered[index]
