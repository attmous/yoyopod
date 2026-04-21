"""
YoyoPod - Unified VoIP + Local Music Application.

Thin application shell that composes focused runtime services.
"""

from __future__ import annotations

import threading
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
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)
from yoyopod.coordinators.voice import VoiceRuntimeCoordinator
from yoyopod.core import EventBus
from yoyopod.core.hardware import AudioDeviceCatalog
from yoyopod.integrations.contacts.directory import PeopleManager
from yoyopod.integrations.call import (
    CallFSM,
    CallHistoryStore,
    CallInterruptionPolicy,
    VoIPManager,
)
from yoyopod.integrations.power import PowerManager
from yoyopod.core import MusicFSM
from yoyopod.integrations.network import NetworkManager
from yoyopod.runtime.boot import RuntimeBootService
from yoyopod.runtime.event_subscriptions import RuntimeEventSubscriptions
from yoyopod.runtime.loop import RuntimeLoopService
from yoyopod.runtime.metrics import RuntimeMetricsStore
from yoyopod.runtime.models import PendingShutdown, PowerAlert, RecoveryState
from yoyopod.runtime.network_events import NetworkEventHandler
from yoyopod.runtime.power_service import PowerRuntimeService
from yoyopod.runtime.recovery import RecoverySupervisor
from yoyopod.runtime.screen_power import ScreenPowerService
from yoyopod.runtime.shutdown import ShutdownLifecycleService
from yoyopod.runtime.status import RuntimeStatusService
from yoyopod.runtime.voice_note_events import VoiceNoteEventHandler
from yoyopod.integrations.cloud.manager import CloudManager

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

        # Main-thread event bus and queued callbacks
        self._main_thread_id = threading.get_ident()
        self.event_bus = EventBus(main_thread_id=self._main_thread_id)
        self._pending_main_thread_callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._pending_safety_main_thread_callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self.runtime_metrics = RuntimeMetricsStore()

        # Runtime services
        self.screen_power_service = ScreenPowerService(self)
        self.recovery_service = RecoverySupervisor(self)
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

    @property
    def _last_input_activity_at(self) -> float:
        """Expose the latest raw input timestamp through the legacy app field."""

        return self.runtime_metrics.last_input_activity_at

    @_last_input_activity_at.setter
    def _last_input_activity_at(self, value: float) -> None:
        self.runtime_metrics.last_input_activity_at = value

    @property
    def _last_input_activity_action_name(self) -> str | None:
        """Expose the latest raw input action through the legacy app field."""

        return self.runtime_metrics.last_input_activity_action_name

    @_last_input_activity_action_name.setter
    def _last_input_activity_action_name(self, value: str | None) -> None:
        self.runtime_metrics.last_input_activity_action_name = value

    @property
    def _last_input_handled_at(self) -> float:
        """Expose the latest handled input timestamp through the legacy app field."""

        return self.runtime_metrics.last_input_handled_at

    @_last_input_handled_at.setter
    def _last_input_handled_at(self, value: float) -> None:
        self.runtime_metrics.last_input_handled_at = value

    @property
    def _last_input_handled_action_name(self) -> str | None:
        """Expose the latest handled input action through the legacy app field."""

        return self.runtime_metrics.last_input_handled_action_name

    @_last_input_handled_action_name.setter
    def _last_input_handled_action_name(self, value: str | None) -> None:
        self.runtime_metrics.last_input_handled_action_name = value

    @property
    def _last_responsiveness_capture_at(self) -> float:
        """Expose the latest responsiveness capture timestamp through the legacy field."""

        return self.runtime_metrics.last_responsiveness_capture_at

    @_last_responsiveness_capture_at.setter
    def _last_responsiveness_capture_at(self, value: float) -> None:
        self.runtime_metrics.last_responsiveness_capture_at = value

    @property
    def _last_responsiveness_capture_reason(self) -> str | None:
        """Expose the latest responsiveness capture reason through the legacy field."""

        return self.runtime_metrics.last_responsiveness_capture_reason

    @_last_responsiveness_capture_reason.setter
    def _last_responsiveness_capture_reason(self, value: str | None) -> None:
        self.runtime_metrics.last_responsiveness_capture_reason = value

    @property
    def _last_responsiveness_capture_scope(self) -> str | None:
        """Expose the latest responsiveness capture scope through the legacy field."""

        return self.runtime_metrics.last_responsiveness_capture_scope

    @_last_responsiveness_capture_scope.setter
    def _last_responsiveness_capture_scope(self, value: str | None) -> None:
        self.runtime_metrics.last_responsiveness_capture_scope = value

    @property
    def _last_responsiveness_capture_summary(self) -> str | None:
        """Expose the latest responsiveness capture summary through the legacy field."""

        return self.runtime_metrics.last_responsiveness_capture_summary

    @_last_responsiveness_capture_summary.setter
    def _last_responsiveness_capture_summary(self, value: str | None) -> None:
        self.runtime_metrics.last_responsiveness_capture_summary = value

    @property
    def _last_responsiveness_capture_artifacts(self) -> dict[str, str]:
        """Expose the latest responsiveness capture artifacts through the legacy field."""

        return self.runtime_metrics.last_responsiveness_capture_artifacts

    @_last_responsiveness_capture_artifacts.setter
    def _last_responsiveness_capture_artifacts(self, value: dict[str, str]) -> None:
        self.runtime_metrics.last_responsiveness_capture_artifacts = dict(value)

    def _pending_main_thread_callback_count(self) -> int | None:
        """Return the combined generic and safety callback backlog."""
        return self.runtime_metrics.pending_main_thread_callback_count(
            self._pending_main_thread_callbacks,
            self._pending_safety_main_thread_callbacks,
        )

    def note_input_activity(self, action: object, _data: Any | None = None) -> None:
        """Record raw or semantic input activity before the coordinator drains it."""
        self.runtime_metrics.note_input_activity(action, _data)

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

    def run(self) -> None:
        """Run the main application loop until interrupted."""
        self.runtime_loop.run()

    def stop(self, disable_watchdog: bool = True) -> None:
        """Clean up and stop the application."""
        self.shutdown_service.stop(disable_watchdog=disable_watchdog)

    def get_status(self, *, refresh_output_volume: bool = False) -> dict[str, Any]:
        """Return the current application status."""
        return self.status_service.get_status(refresh_output_volume=refresh_output_volume)
