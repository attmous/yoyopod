"""
YoyoPod - Unified VoIP + Music Streaming Application

Main application bootstrap and lifecycle coordinator.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger

from yoyopy.app_context import AppContext
from yoyopy.audio.mopidy_client import MopidyClient
from yoyopy.config import ConfigManager, YoyoPodConfig
from yoyopy.voip import VoIPConfig, VoIPManager
from yoyopy.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    ScreenCoordinator,
)
from yoyopy.event_bus import EventBus
from yoyopy.events import RecoveryAttemptCompletedEvent, ScreenChangedEvent
from yoyopy.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputManager, InteractionProfile, get_input_manager
from yoyopy.ui.screens import (
    CallScreen,
    ContactListScreen,
    HubScreen,
    HomeScreen,
    InCallScreen,
    IncomingCallScreen,
    MenuScreen,
    NowPlayingScreen,
    OutgoingCallScreen,
    PlaylistScreen,
    ScreenManager,
)


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
        self.mopidy_client: Optional[MopidyClient] = None

        # Screen instances
        self.hub_screen: Optional[HubScreen] = None
        self.home_screen: Optional[HomeScreen] = None
        self.menu_screen: Optional[MenuScreen] = None
        self.now_playing_screen: Optional[NowPlayingScreen] = None
        self.playlist_screen: Optional[PlaylistScreen] = None
        self.call_screen: Optional[CallScreen] = None
        self.contact_list_screen: Optional[ContactListScreen] = None
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
        self.event_bus.subscribe(ScreenChangedEvent, self._handle_screen_changed_event)
        self.event_bus.subscribe(
            RecoveryAttemptCompletedEvent,
            self._handle_recovery_attempt_completed_event,
        )

        # Extracted coordinators
        self.coordinator_runtime: Optional[CoordinatorRuntime] = None
        self.screen_coordinator: Optional[ScreenCoordinator] = None
        self.call_coordinator: Optional[CallCoordinator] = None
        self.playback_coordinator: Optional[PlaybackCoordinator] = None

        # Recovery backoff state
        self._voip_recovery = _RecoveryState()
        self._mopidy_recovery = _RecoveryState()
        self._stopping = False

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

            logger.info("✓ YoyoPod setup complete")
            return True
        except Exception as exc:
            logger.error(f"Setup failed: {exc}")
            return False

    def _load_configuration(self) -> bool:
        """Load YoyoPod configuration."""
        logger.info("Loading configuration...")

        try:
            self.config_manager = ConfigManager(config_dir=self.config_dir)
            self.app_settings = self.config_manager.get_app_settings()
            self.config = self.config_manager.get_app_config_dict()

            if self.config_manager.app_config_loaded:
                logger.info(f"Loaded configuration from {self.config_manager.app_config_file}")
            else:
                logger.info("Using default application configuration")

            self.auto_resume_after_call = self.app_settings.audio.auto_resume_after_call
            logger.info(f"  Auto-resume after call: {self.auto_resume_after_call}")
            return True
        except Exception as exc:
            logger.error(f"Failed to load configuration: {exc}")
            return False

    def _init_core_components(self) -> bool:
        """Initialize display, context, orchestration models, input, and screen manager."""
        logger.info("Initializing core components...")

        try:
            logger.info("  - Display")
            display_hardware = (
                self.app_settings.display.hardware if self.app_settings else "auto"
            )
            logger.info(f"    Hardware: {display_hardware}")
            self.display = Display(hardware=display_hardware, simulate=self.simulate)
            logger.info(f"    Dimensions: {self.display.WIDTH}x{self.display.HEIGHT}")
            logger.info(f"    Orientation: {self.display.ORIENTATION}")

            self.display.clear(self.display.COLOR_BLACK)
            self.display.text(
                "YoyoPod Starting...",
                10,
                100,
                color=self.display.COLOR_WHITE,
                font_size=16,
            )
            self.display.update()

            logger.info("  - AppContext")
            self.context = AppContext()

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
                self.input_manager.start()
                logger.info("    ✓ Input system initialized")
            else:
                logger.info("    → No input hardware available")

            logger.info("  - ScreenManager")
            self.screen_manager = ScreenManager(self.display, self.input_manager)
            return True
        except Exception as exc:
            logger.error(f"Failed to initialize core components: {exc}")
            return False

    def _init_managers(self) -> bool:
        """Initialize VoIP and Mopidy managers."""
        logger.info("Initializing managers...")

        self.display.clear(self.display.COLOR_BLACK)
        self.display.text("Connecting VoIP...", 10, 80, color=self.display.COLOR_WHITE, font_size=16)
        self.display.text(
            "Connecting Mopidy...",
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
            if self.voip_manager.start():
                logger.info("    ✓ VoIP started successfully")
            else:
                logger.warning("    ⚠ VoIP failed to start (music-only mode)")

            logger.info("  - MopidyClient")
            mopidy_host = (
                self.app_settings.audio.mopidy_host if self.app_settings else "localhost"
            )
            mopidy_port = self.app_settings.audio.mopidy_port if self.app_settings else 6680
            self.mopidy_client = MopidyClient(host=mopidy_host, port=mopidy_port)
            if self.mopidy_client.connect():
                logger.info("    ✓ Mopidy connected successfully")
                self.mopidy_client.start_polling()
            else:
                logger.warning("    ⚠ Mopidy connection failed (VoIP-only mode)")

            return True
        except Exception as exc:
            logger.error(f"Failed to initialize managers: {exc}")
            return False

    def _setup_screens(self) -> bool:
        """Create and register all screens."""
        logger.info("Setting up screens...")

        try:
            menu_items = [
                "Now Playing",
                "Browse Playlists",
                "VoIP Status",
                "Call Contact",
                "Back",
            ]
            self.hub_screen = HubScreen(
                self.display,
                self.context,
                mopidy_client=self.mopidy_client,
                voip_manager=self.voip_manager,
            )
            self.menu_screen = MenuScreen(self.display, self.context, items=menu_items)
            self.home_screen = HomeScreen(self.display, self.context)
            self.now_playing_screen = NowPlayingScreen(
                self.display,
                self.context,
                mopidy_client=self.mopidy_client,
            )
            self.playlist_screen = PlaylistScreen(
                self.display,
                self.context,
                mopidy_client=self.mopidy_client,
            )
            self.call_screen = CallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager,
            )
            self.contact_list_screen = ContactListScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager,
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
            self.screen_manager.register_screen("now_playing", self.now_playing_screen)
            self.screen_manager.register_screen("playlists", self.playlist_screen)
            self.screen_manager.register_screen("call", self.call_screen)
            self.screen_manager.register_screen("contacts", self.contact_list_screen)
            self.screen_manager.register_screen("incoming_call", self.incoming_call_screen)
            self.screen_manager.register_screen("outgoing_call", self.outgoing_call_screen)
            self.screen_manager.register_screen("in_call", self.in_call_screen)
            logger.info("    - Whisplay root: hub")

            logger.info("  ✓ All screens registered")
            logger.info("    - Music screens: now_playing, playlists")
            logger.info("    - VoIP screens: call, contacts, incoming_call, outgoing_call, in_call")
            logger.info("    - Navigation: home, menu")

            initial_screen = self._get_initial_screen_name()
            self.screen_manager.push_screen(initial_screen)
            self._ui_state = self._get_initial_ui_state()
            logger.info(f"  Initial route resolved to {initial_screen}")
            logger.info(f"  Initial screen confirmed as {initial_screen}")
            logger.info("  ✓ Initial screen set to menu")
            return True
        except Exception as exc:
            logger.error(f"Failed to setup screens: {exc}")
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
        if self._get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return "hub"
        return "menu"

    def _get_initial_ui_state(self) -> AppRuntimeState:
        """Return the base runtime state for the active interaction profile."""
        if self._get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return AppRuntimeState.HUB
        return AppRuntimeState.MENU

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
        logger.info("  ✓ VoIP callbacks registered")

    def _setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        logger.info("Setting up music callbacks...")

        if not self.mopidy_client:
            logger.warning("  MopidyClient not available, skipping callbacks")
            return

        self._ensure_coordinators()
        self.mopidy_client.on_track_change(self.playback_coordinator.publish_track_change)
        self.mopidy_client.on_playback_state_change(
            self.playback_coordinator.publish_playback_state_change
        )
        self.mopidy_client.on_connection_change(
            self.playback_coordinator.publish_availability_change
        )
        logger.info("  ✓ Music callbacks registered")

    def _setup_event_subscriptions(self) -> None:
        """Bind extracted coordinators to the event bus."""
        logger.info("Setting up event subscriptions...")
        self._ensure_coordinators()
        self.call_coordinator.bind(self.event_bus)
        self.playback_coordinator.bind(self.event_bus)
        logger.info("  ✓ Event subscriptions registered")

    def _process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued typed events scheduled by worker threads."""
        return self.event_bus.drain(limit)

    def _handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        """Apply queued screen-change state sync on the coordinator thread."""
        self._sync_screen_changed(event.screen_name)

    def _handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        """Finalize background recovery attempts on the coordinator thread."""
        if event.manager != "mopidy":
            return

        self._mopidy_recovery.in_flight = False
        if self._stopping:
            return

        if event.recovered and self.mopidy_client and not self.mopidy_client.polling:
            self.mopidy_client.start_polling()

        self._finalize_recovery_attempt(
            "Mopidy",
            self._mopidy_recovery,
            event.recovered,
            event.recovery_now,
        )

    def _ensure_coordinators(self) -> None:
        """Build coordinator helpers around the initialized runtime."""
        if self.coordinator_runtime is not None:
            return

        self.coordinator_runtime = CoordinatorRuntime(
            music_fsm=self.music_fsm,
            call_fsm=self.call_fsm,
            call_interruption_policy=self.call_interruption_policy,
            screen_manager=self.screen_manager,
            mopidy_client=self.mopidy_client,
            now_playing_screen=self.now_playing_screen,
            call_screen=self.call_screen,
            incoming_call_screen=self.incoming_call_screen,
            outgoing_call_screen=self.outgoing_call_screen,
            in_call_screen=self.in_call_screen,
            config=self.config,
            config_manager=self.config_manager,
            ui_state=self._ui_state,
            voip_ready=self._voip_registered,
        )
        self.screen_coordinator = ScreenCoordinator(self.coordinator_runtime)
        self.call_coordinator = CallCoordinator(
            runtime=self.coordinator_runtime,
            screen_coordinator=self.screen_coordinator,
            auto_resume_after_call=self.auto_resume_after_call,
            initial_voip_registered=self._voip_registered,
        )
        self.playback_coordinator = PlaybackCoordinator(
            runtime=self.coordinator_runtime,
            screen_coordinator=self.screen_coordinator,
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

    def _attempt_manager_recovery(self, now: float | None = None) -> None:
        """Try to recover VoIP and Mopidy when they become unavailable."""
        if self._stopping:
            return

        recovery_now = time.monotonic() if now is None else now
        self._attempt_voip_recovery(recovery_now)
        self._attempt_mopidy_recovery(recovery_now)

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

    def _attempt_mopidy_recovery(self, recovery_now: float) -> None:
        """Reconnect Mopidy when the HTTP client becomes unavailable."""
        if self.mopidy_client is None:
            return

        if self.mopidy_client.is_connected:
            self._mopidy_recovery.reset()
            return

        if self._mopidy_recovery.in_flight:
            return

        if recovery_now < self._mopidy_recovery.next_attempt_at:
            return

        logger.info("Attempting Mopidy recovery")
        self._mopidy_recovery.in_flight = True
        self._start_mopidy_recovery_worker(recovery_now)

    def _start_mopidy_recovery_worker(self, recovery_now: float) -> None:
        """Run blocking Mopidy reconnect attempts off the coordinator thread."""
        worker = threading.Thread(
            target=self._run_mopidy_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="mopidy-recovery",
        )
        worker.start()

    def _run_mopidy_recovery_attempt(self, recovery_now: float) -> None:
        """Execute one Mopidy reconnect attempt and publish the typed result."""
        recovered = False
        if not self._stopping and self.mopidy_client is not None:
            recovered = self.mopidy_client.connect()

        self.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="mopidy",
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
        if self.mopidy_client and self.mopidy_client.is_connected:
            logger.info("  Connected: True")
            playback_state = self.mopidy_client.get_playback_state()
            logger.info(f"  Playback state: {playback_state}")
        else:
            logger.info("  Mopidy not connected")
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

            if self.simulate:
                logger.info("")
                logger.info("Simulation mode: Application running...")
                logger.info("  (Incoming calls and track changes will trigger callbacks)")
                logger.info("")

            while True:
                time.sleep(0.1)
                self._process_pending_main_thread_actions()
                self._attempt_manager_recovery()

                current_time = time.time()
                if current_time - last_screen_update >= screen_update_interval:
                    self._update_now_playing_if_needed()
                    self._update_in_call_if_needed()
                    last_screen_update = current_time
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("Shutting down...")
            logger.info("=" * 60)

    def stop(self) -> None:
        """Clean up and stop the application."""
        logger.info("Stopping YoyoPod...")
        self._stopping = True

        self._ensure_coordinators()
        self.call_coordinator.cleanup()

        if self.voip_manager:
            logger.info("  - Stopping VoIP manager")
            self.voip_manager.stop(notify_events=False)

        if self.mopidy_client:
            logger.info("  - Stopping music polling")
            self.mopidy_client.stop_polling()
            self.mopidy_client.cleanup()

        if self.input_manager:
            logger.info("  - Stopping input manager")
            self.input_manager.stop()

        pending_actions = self._process_pending_main_thread_actions()
        if pending_actions:
            logger.info(f"  - Processed {pending_actions} queued app events during shutdown")

        if self.display:
            logger.info("  - Clearing display")
            self.display.clear(self.display.COLOR_BLACK)
            self.display.text("Goodbye!", 70, 120, color=self.display.COLOR_CYAN, font_size=20)
            self.display.update()
            time.sleep(1)
            self.display.cleanup()

        logger.info("✓ YoyoPod stopped")

    def get_status(self) -> Dict[str, Any]:
        """Return the current application status."""
        return {
            "state": self.coordinator_runtime.get_state_name(),
            "voip_registered": self.voip_registered,
            "music_was_playing": self.call_interruption_policy.music_interrupted_by_call,
            "auto_resume": self.auto_resume_after_call,
            "voip_available": self.voip_manager is not None and self.voip_manager.running,
            "music_available": self.mopidy_client is not None and self.mopidy_client.is_connected,
        }
