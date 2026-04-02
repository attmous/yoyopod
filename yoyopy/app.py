"""
YoyoPod - Unified VoIP + Music Streaming Application

Main application bootstrap and lifecycle coordinator.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from loguru import logger

from yoyopy.app_context import AppContext
from yoyopy.audio.mopidy_client import MopidyClient
from yoyopy.config import ConfigManager, YoyoPodConfig
from yoyopy.connectivity import VoIPConfig, VoIPManager
from yoyopy.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    ScreenCoordinator,
)
from yoyopy.event_bus import EventBus
from yoyopy.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputManager, get_input_manager
from yoyopy.ui.screens import (
    CallScreen,
    ContactListScreen,
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
class _MainThreadCallbackEvent:
    """Compatibility event used by existing app queue helpers."""

    description: str
    callback: Callable[[], None]


class YoyoPodApp:
    """
    Main YoyoPod application coordinator.

    Owns startup, lifecycle, and the main loop while delegating call and
    playback orchestration to focused coordinator modules.
    """

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
        self.event_bus.subscribe(_MainThreadCallbackEvent, self._handle_main_thread_callback_event)

        # Extracted coordinators
        self.coordinator_runtime: Optional[CoordinatorRuntime] = None
        self.screen_coordinator: Optional[ScreenCoordinator] = None
        self.call_coordinator: Optional[CallCoordinator] = None
        self.playback_coordinator: Optional[PlaybackCoordinator] = None

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
            self.coordinator_runtime.set_ui_state(AppRuntimeState.MENU, trigger="initial_screen")
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

            self.screen_manager.register_screen("home", self.home_screen)
            self.screen_manager.register_screen("menu", self.menu_screen)
            self.screen_manager.register_screen("now_playing", self.now_playing_screen)
            self.screen_manager.register_screen("playlists", self.playlist_screen)
            self.screen_manager.register_screen("call", self.call_screen)
            self.screen_manager.register_screen("contacts", self.contact_list_screen)
            self.screen_manager.register_screen("incoming_call", self.incoming_call_screen)
            self.screen_manager.register_screen("outgoing_call", self.outgoing_call_screen)
            self.screen_manager.register_screen("in_call", self.in_call_screen)

            logger.info("  ✓ All screens registered")
            logger.info("    - Music screens: now_playing, playlists")
            logger.info("    - VoIP screens: call, contacts, incoming_call, outgoing_call, in_call")
            logger.info("    - Navigation: home, menu")

            self.screen_manager.push_screen("menu")
            self._ui_state = AppRuntimeState.MENU
            logger.info("  ✓ Initial screen set to menu")
            return True
        except Exception as exc:
            logger.error(f"Failed to setup screens: {exc}")
            return False

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
        logger.info("  ✓ Music callbacks registered")

    def _setup_event_subscriptions(self) -> None:
        """Bind extracted coordinators to the event bus."""
        logger.info("Setting up event subscriptions...")
        self._ensure_coordinators()
        self.call_coordinator.bind(self.event_bus)
        self.playback_coordinator.bind(self.event_bus)
        logger.info("  ✓ Event subscriptions registered")

    def _setup_state_callbacks(self) -> None:
        """Legacy no-op retained for compatibility."""
        return None
        logger.info("  ✓ State callbacks registered")

    def _run_on_main_thread(self, description: str, callback: Callable[[], None]) -> None:
        """Queue work onto the coordinator thread."""
        self.event_bus.publish(_MainThreadCallbackEvent(description=description, callback=callback))

    def _process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued callbacks and typed events scheduled by worker threads."""
        return self.event_bus.drain(limit)

    def _handle_main_thread_callback_event(self, event: _MainThreadCallbackEvent) -> None:
        """Execute a compatibility callback event on the coordinator thread."""
        logger.debug(f"Processing main-thread action: {event.description}")
        event.callback()

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

    def _pop_call_screens(self) -> None:
        """Compatibility wrapper for clearing call-related screens."""
        self._ensure_coordinators()
        self.screen_coordinator.pop_call_screens()

    def _update_now_playing_if_needed(self) -> None:
        """Compatibility wrapper for periodic now-playing refreshes."""
        self._ensure_coordinators()
        self.playback_coordinator.update_now_playing_if_needed()

    def _start_ringing(self) -> None:
        """Compatibility wrapper for starting the call ring tone."""
        self._ensure_coordinators()
        self.call_coordinator.start_ringing()

    def _stop_ringing(self) -> None:
        """Compatibility wrapper for stopping the call ring tone."""
        self._ensure_coordinators()
        self.call_coordinator.stop_ringing()

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

                current_time = time.time()
                if current_time - last_screen_update >= screen_update_interval:
                    self._update_now_playing_if_needed()
                    last_screen_update = current_time
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("Shutting down...")
            logger.info("=" * 60)

    def stop(self) -> None:
        """Clean up and stop the application."""
        logger.info("Stopping YoyoPod...")

        self._ensure_coordinators()
        self.call_coordinator.cleanup()

        if self.voip_manager:
            logger.info("  - Stopping VoIP manager")
            self.voip_manager.stop()

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
            "voip_available": self.voip_manager is not None,
            "music_available": self.mopidy_client is not None and self.mopidy_client.is_connected,
        }
