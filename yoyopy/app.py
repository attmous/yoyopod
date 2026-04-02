"""
YoyoPod - Unified VoIP + Music Streaming Application

Main application coordinator that integrates VoIP calling and music streaming
into a seamless iPod-inspired experience.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens import ScreenManager
from yoyopy.ui.input import get_input_manager, InputManager
from yoyopy.ui.screens import (
    HomeScreen,
    MenuScreen,
    NowPlayingScreen,
    PlaylistScreen,
    CallScreen,
    ContactListScreen,
    IncomingCallScreen,
    OutgoingCallScreen,
    InCallScreen
)
from yoyopy.app_context import AppContext
from yoyopy.state_machine import StateMachine, AppState
from yoyopy.connectivity import VoIPManager, VoIPConfig, RegistrationState, CallState
from yoyopy.config import ConfigManager
from yoyopy.audio.mopidy_client import MopidyClient, MopidyTrack


class YoyoPodApp:
    """
    Main YoyoPod application coordinator.

    Integrates VoIP calling, music streaming, state management,
    and UI into a unified application with seamless call interruption
    and music pause/resume capabilities.
    """

    def __init__(
        self,
        config_dir: str = "config",
        simulate: bool = False
    ) -> None:
        """
        Initialize YoyoPod application.

        Args:
            config_dir: Path to configuration directory
            simulate: If True, run in simulation mode (no hardware required)
        """
        self.config_dir = config_dir
        self.simulate = simulate

        # Core components
        self.display: Optional[Display] = None
        self.context: Optional[AppContext] = None
        self.config_manager: Optional[ConfigManager] = None
        self.state_machine: Optional[StateMachine] = None
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

        # Integration state tracking
        self.music_was_playing_before_call = False
        self.auto_resume_after_call = True  # Will be loaded from config
        self.voip_registered = False
        self.handling_incoming_call = False  # Prevent callback spam
        self.ringing_process: Optional[subprocess.Popen] = None  # Ring tone playback process

        # Configuration
        self.config: Dict[str, Any] = {}

        # Coordinate callback work through the main app loop so UI and state
        # changes do not run from background manager threads.
        self._main_thread_id = threading.get_ident()
        self._main_thread_actions: Queue[tuple[str, Callable[[], None]]] = Queue()

        logger.info("=" * 60)
        logger.info("YoyoPod Application Initializing")
        logger.info("=" * 60)

    def setup(self) -> bool:
        """
        Initialize all components and register callbacks.

        Returns:
            True if setup successful, False otherwise
        """
        try:
            # Load configuration first
            if not self._load_configuration():
                logger.error("Failed to load configuration")
                return False

            # Initialize core components
            if not self._init_core_components():
                logger.error("Failed to initialize core components")
                return False

            # Initialize managers
            if not self._init_managers():
                logger.error("Failed to initialize managers")
                return False

            # Setup screens
            if not self._setup_screens():
                logger.error("Failed to setup screens")
                return False

            # Setup callbacks
            self._setup_voip_callbacks()
            self._setup_music_callbacks()
            self._setup_state_callbacks()

            logger.info("✓ YoyoPod setup complete")
            return True

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            return False

    def _load_configuration(self) -> bool:
        """
        Load YoyoPod configuration.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Loading configuration...")

        try:
            # Initialize config manager
            self.config_manager = ConfigManager(config_dir=self.config_dir)

            # Load YoyoPod-specific config (will create default if not exists)
            config_file = Path(self.config_dir) / "yoyopod_config.yaml"

            if config_file.exists():
                import yaml
                with open(config_file, 'r') as f:
                    self.config = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {config_file}")
            else:
                logger.warning(f"Config file not found: {config_file}")
                logger.info("Using default configuration")
                self.config = self._get_default_config()

            # Extract key settings
            self.auto_resume_after_call = self.config.get(
                'audio', {}
            ).get('auto_resume_after_call', True)

            logger.info(f"  Auto-resume after call: {self.auto_resume_after_call}")

            return True

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return False

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get default configuration.

        Returns:
            Default config dictionary
        """
        return {
            'app': {
                'name': 'YoyoPod',
                'version': '1.0.0',
                'simulate': self.simulate
            },
            'audio': {
                'mopidy_host': 'localhost',
                'mopidy_port': 6680,
                'auto_resume_after_call': True,
                'default_volume': 70,
                'ring_output_device': '',
                'speaker_test_path': 'speaker-test'
            },
            'voip': {
                'config_file': 'config/voip_config.yaml',
                'priority_over_music': True,
                'auto_answer': False,
                'ring_duration_seconds': 30
            },
            'ui': {
                'theme': 'dark',
                'show_album_art': True,
                'screen_timeout_seconds': 300
            },
            'logging': {
                'level': 'INFO'
            }
        }

    def _init_core_components(self) -> bool:
        """
        Initialize core components (display, context, state machine).

        Returns:
            True if successful, False otherwise
        """
        logger.info("Initializing core components...")

        try:
            # Initialize display (with HAL support)
            logger.info("  - Display")
            display_hardware = self.config.get('display', {}).get('hardware', 'auto')
            logger.info(f"    Hardware: {display_hardware}")
            self.display = Display(hardware=display_hardware, simulate=self.simulate)
            logger.info(f"    Dimensions: {self.display.WIDTH}×{self.display.HEIGHT}")
            logger.info(f"    Orientation: {self.display.ORIENTATION}")

            self.display.clear(self.display.COLOR_BLACK)
            self.display.text(
                "YoyoPod Starting...",
                10, 100,
                color=self.display.COLOR_WHITE,
                font_size=16
            )
            self.display.update()

            # Initialize app context
            logger.info("  - AppContext")
            self.context = AppContext()

            # Initialize state machine
            logger.info("  - StateMachine")
            self.state_machine = StateMachine(self.context)

            # Initialize input manager with hardware auto-detection
            logger.info("  - InputManager")
            self.input_manager = get_input_manager(
                display_adapter=self.display.get_adapter(),
                config=self.config,
                simulate=self.simulate
            )

            if self.input_manager:
                self.input_manager.start()
                logger.info("    ✓ Input system initialized")
            else:
                logger.info("    → No input hardware available")

            # Initialize screen manager
            logger.info("  - ScreenManager")
            self.screen_manager = ScreenManager(self.display, self.input_manager)

            return True

        except Exception as e:
            logger.error(f"Failed to initialize core components: {e}")
            return False

    def _init_managers(self) -> bool:
        """
        Initialize VoIP and music managers.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Initializing managers...")

        # Update display status
        self.display.clear(self.display.COLOR_BLACK)
        self.display.text(
            "Connecting VoIP...",
            10, 80,
            color=self.display.COLOR_WHITE,
            font_size=16
        )
        self.display.text(
            "Connecting Mopidy...",
            10, 110,
            color=self.display.COLOR_WHITE,
            font_size=16
        )
        self.display.update()

        try:
            # Initialize VoIP manager
            logger.info("  - VoIPManager")
            voip_config = VoIPConfig.from_config_manager(self.config_manager)
            self.voip_manager = VoIPManager(voip_config, config_manager=self.config_manager)

            # Start VoIP (don't fail if VoIP doesn't start - can still use music)
            if self.voip_manager.start():
                logger.info("    ✓ VoIP started successfully")
            else:
                logger.warning("    ⚠ VoIP failed to start (music-only mode)")

            # Initialize Mopidy client
            logger.info("  - MopidyClient")
            mopidy_host = self.config.get('audio', {}).get('mopidy_host', 'localhost')
            mopidy_port = self.config.get('audio', {}).get('mopidy_port', 6680)
            self.mopidy_client = MopidyClient(host=mopidy_host, port=mopidy_port)

            # Connect to Mopidy (don't fail if not connected - can still use VoIP)
            if self.mopidy_client.connect():
                logger.info("    ✓ Mopidy connected successfully")
                # Start track change polling
                self.mopidy_client.start_polling()
            else:
                logger.warning("    ⚠ Mopidy connection failed (VoIP-only mode)")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize managers: {e}")
            return False

    def _setup_screens(self) -> bool:
        """
        Setup and register all screens.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Setting up screens...")

        try:
            # Create menu screen with integrated options
            menu_items = [
                "Now Playing",
                "Browse Playlists",
                "VoIP Status",
                "Call Contact",
                "Back"
            ]
            self.menu_screen = MenuScreen(
                self.display,
                self.context,
                items=menu_items
            )

            # Create home screen
            self.home_screen = HomeScreen(
                self.display,
                self.context
            )

            # Music screens
            self.now_playing_screen = NowPlayingScreen(
                self.display,
                self.context,
                mopidy_client=self.mopidy_client
            )

            self.playlist_screen = PlaylistScreen(
                self.display,
                self.context,
                mopidy_client=self.mopidy_client
            )

            # VoIP screens
            self.call_screen = CallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager
            )

            self.contact_list_screen = ContactListScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                config_manager=self.config_manager
            )

            self.incoming_call_screen = IncomingCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                caller_address="",
                caller_name="Unknown"
            )

            self.outgoing_call_screen = OutgoingCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager,
                callee_address="",
                callee_name="Unknown"
            )

            self.in_call_screen = InCallScreen(
                self.display,
                self.context,
                voip_manager=self.voip_manager
            )

            # Register all screens with screen manager
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
            logger.info(f"    - Music screens: now_playing, playlists")
            logger.info(f"    - VoIP screens: call, contacts, incoming_call, outgoing_call, in_call")
            logger.info(f"    - Navigation: home, menu")

            # Set initial screen to menu
            self.screen_manager.push_screen("menu")
            logger.info("  ✓ Initial screen set to menu")

            return True

        except Exception as e:
            logger.error(f"Failed to setup screens: {e}")
            return False

    def _setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""
        logger.info("Setting up VoIP callbacks...")

        if not self.voip_manager:
            logger.warning("  VoIPManager not available, skipping callbacks")
            return

        self.voip_manager.on_incoming_call(
            lambda caller_address, caller_name: self._run_on_main_thread(
                f"incoming call from {caller_name or caller_address}",
                lambda: self._handle_incoming_call(caller_address, caller_name),
            )
        )
        self.voip_manager.on_call_state_change(
            lambda state: self._run_on_main_thread(
                f"call state change to {state.value}",
                lambda: self._handle_call_state_change(state),
            )
        )
        self.voip_manager.on_registration_change(
            lambda state: self._run_on_main_thread(
                f"registration state change to {state.value}",
                lambda: self._handle_registration_change(state),
            )
        )

        logger.info("  ✓ VoIP callbacks registered")

    def _setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        logger.info("Setting up music callbacks...")

        if not self.mopidy_client:
            logger.warning("  MopidyClient not available, skipping callbacks")
            return

        self.mopidy_client.on_track_change(
            lambda track: self._run_on_main_thread(
                "track change",
                lambda: self._handle_track_change(track),
            )
        )
        self.mopidy_client.on_playback_state_change(
            lambda playback_state: self._run_on_main_thread(
                f"playback state change to {playback_state}",
                lambda: self._handle_playback_state_change(playback_state),
            )
        )

        logger.info("  ✓ Music callbacks registered")

    def _setup_state_callbacks(self) -> None:
        """Register state machine callbacks."""
        logger.info("Setting up state callbacks...")

        # Register callbacks for state transitions
        self.state_machine.on_enter(
            AppState.PLAYING_WITH_VOIP,
            self._on_enter_playing_with_voip
        )
        self.state_machine.on_enter(
            AppState.CALL_ACTIVE_MUSIC_PAUSED,
            self._on_enter_call_active_music_paused
        )

        logger.info("  ✓ State callbacks registered")

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _run_on_main_thread(
        self,
        description: str,
        callback: Callable[[], None],
    ) -> None:
        """
        Run work on the coordinator thread.

        Background manager threads enqueue callbacks here so UI mutations and
        state transitions happen from the main application loop.
        """
        if threading.get_ident() == self._main_thread_id:
            callback()
            return

        self._main_thread_actions.put((description, callback))
        logger.debug(f"Queued main-thread action: {description}")

    def _process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """
        Drain queued actions that were scheduled by background threads.

        Args:
            limit: Optional maximum number of actions to process.

        Returns:
            Number of processed actions.
        """
        processed = 0

        while limit is None or processed < limit:
            try:
                description, callback = self._main_thread_actions.get_nowait()
            except Empty:
                break

            try:
                logger.debug(f"Processing main-thread action: {description}")
                callback()
            except Exception as e:
                logger.error(f"Error processing main-thread action '{description}': {e}")

            processed += 1

        return processed

    def _pop_call_screens(self) -> None:
        """
        Pop all call-related screens from the stack.

        Uses the same pattern as demo_voip.py to prevent screen stack issues.
        """
        call_screens = [
            self.in_call_screen,
            self.incoming_call_screen,
            self.outgoing_call_screen
        ]

        # Keep popping while current screen is a call screen
        while self.screen_manager.current_screen in call_screens:
            self.screen_manager.pop_screen()
            # Safety check to prevent infinite loop
            if not self.screen_manager.screen_stack:
                break

        logger.debug("Call screens cleared from stack")

    def _update_now_playing_if_needed(self) -> None:
        """
        Update NowPlayingScreen if visible and music is playing.

        Used for periodic updates to animate the progress bar.
        """
        # Only update if NowPlayingScreen is visible
        if self.screen_manager.current_screen != self.now_playing_screen:
            return

        # Only update if music is actually playing
        if self.mopidy_client:
            playback_state = self.mopidy_client.get_playback_state()
            if playback_state == "playing":
                # Silently refresh the screen (no debug log to avoid spam)
                self.now_playing_screen.render()

    def _start_ringing(self) -> None:
        """Start playing ring tone for incoming call."""
        # Stop any existing ringing first
        self._stop_ringing()

        try:
            # Use speaker-test to generate a continuous 800 Hz ring tone.
            ring_output_device = self.config.get('audio', {}).get('ring_output_device')
            if not ring_output_device and self.config_manager:
                ring_output_device = self.config_manager.get_ring_output_device()

            command = [
                self.config.get('audio', {}).get('speaker_test_path', 'speaker-test'),
                "-t",
                "sine",
                "-f",
                "800",
            ]
            if ring_output_device:
                command.extend(["-D", ring_output_device])

            self.ringing_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.debug("🔔 Ring tone started")
        except Exception as e:
            logger.warning(f"Failed to start ring tone: {e}")

    def _stop_ringing(self) -> None:
        """Stop playing ring tone."""
        if self.ringing_process:
            try:
                self.ringing_process.terminate()
                self.ringing_process.wait(timeout=1.0)
                logger.debug("🔕 Ring tone stopped")
            except Exception as e:
                logger.warning(f"Failed to stop ring tone: {e}")
            finally:
                self.ringing_process = None

    # ========================================================================
    # VoIP Event Handlers
    # ========================================================================

    def _handle_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """
        Handle incoming call - coordinate music pause and state transition.

        Args:
            caller_address: SIP address of caller
            caller_name: Display name of caller
        """
        # Guard: prevent callback spam during ring
        if self.handling_incoming_call:
            logger.debug(f"  (Already handling call from {caller_name})")
            return

        self.handling_incoming_call = True
        logger.info(f"📞 INCOMING CALL: {caller_name} ({caller_address})")

        # Check if music is currently playing (check actual mopidy state, not state machine)
        playback_state = self.mopidy_client.get_playback_state() if self.mopidy_client else "stopped"

        if playback_state == "playing":
            self.music_was_playing_before_call = True
            logger.info("  🎵 Auto-pausing music for incoming call")

            # Pause music
            if self.mopidy_client:
                self.mopidy_client.pause()

            # Transition to paused-by-call state (if we're in a music state)
            if self.state_machine.is_music_playing():
                self.state_machine.transition_to(
                    AppState.PAUSED_BY_CALL,
                    "auto_pause_for_call"
                )

        # Transition to incoming call state using the correct trigger for the
        # current music/call context.
        if self.state_machine.current_state == AppState.PAUSED_BY_CALL:
            self.state_machine.transition_to(
                AppState.CALL_INCOMING,
                "incoming_call_ringing"
            )
        else:
            self.state_machine.transition_to(
                AppState.CALL_INCOMING,
                "incoming_call"
            )

        # Update and push incoming call screen
        self.incoming_call_screen.caller_address = caller_address
        self.incoming_call_screen.caller_name = caller_name
        self.incoming_call_screen.ring_animation_frame = 0  # Reset animation

        # Only push if not already showing (prevent stack overflow)
        if self.screen_manager.current_screen != self.incoming_call_screen:
            self.screen_manager.push_screen("incoming_call")
            logger.info("  → Pushed incoming call screen")

        # Start ring tone
        self._start_ringing()

    def _handle_call_state_change(self, state: CallState) -> None:
        """
        Handle VoIP call state changes.

        Args:
            state: New call state
        """
        logger.info(f"📞 Call state changed: {state.value}")

        if state == CallState.CONNECTED or state == CallState.STREAMS_RUNNING:
            current_state = self.state_machine.current_state

            if current_state == AppState.PAUSED_BY_CALL:
                self.state_machine.transition_to(
                    AppState.CALL_ACTIVE_MUSIC_PAUSED,
                    "call_answered"
                )
            elif current_state == AppState.CALL_INCOMING and self.music_was_playing_before_call:
                self.state_machine.transition_to(
                    AppState.CALL_ACTIVE_MUSIC_PAUSED,
                    "answer_call_resume_after"
                )
            elif current_state == AppState.CALL_OUTGOING and self.music_was_playing_before_call:
                self.state_machine.transition_to(
                    AppState.CALL_ACTIVE_MUSIC_PAUSED,
                    "call_connected_music_paused"
                )
            else:
                self.state_machine.transition_to(
                    AppState.CALL_ACTIVE,
                    "call_connected"
                )

            # Push in-call screen
            if self.screen_manager.current_screen != self.in_call_screen:
                self.screen_manager.push_screen("in_call")
                logger.info("  → Pushed in-call screen")

            # Stop ring tone when call is answered
            self._stop_ringing()

        elif state == CallState.RELEASED:
            # Call ended
            self._handle_call_ended()

    def _handle_call_ended(self) -> None:
        """Handle call end - restore music if needed."""
        logger.info("📞 Call ended")

        # Stop ring tone (in case call was rejected while ringing)
        self._stop_ringing()

        # Reset guard flag
        self.handling_incoming_call = False

        # Pop all call screens
        self._pop_call_screens()

        current_state = self.state_machine.current_state

        # Check if we should resume music
        if self.music_was_playing_before_call and self.auto_resume_after_call:
            logger.info("  🎵 Auto-resuming music after call")

            # Resume music playback
            if self.mopidy_client:
                self.mopidy_client.play()

            if current_state in (AppState.CALL_ACTIVE_MUSIC_PAUSED, AppState.CALL_INCOMING):
                self.state_machine.transition_to(
                    AppState.PLAYING_WITH_VOIP,
                    "call_ended_auto_resume"
                )
            elif current_state == AppState.PAUSED_BY_CALL:
                self.state_machine.transition_to(
                    AppState.PLAYING_WITH_VOIP,
                    "call_rejected_resume"
                )

            # Refresh NowPlayingScreen if visible to show play icon
            if self.screen_manager.current_screen == self.now_playing_screen:
                self.now_playing_screen.render()
                logger.debug("  → Now playing screen refreshed (showing play icon)")

        elif self.music_was_playing_before_call:
            logger.info("  🎵 Music stays paused (auto-resume disabled)")
            if current_state == AppState.CALL_ACTIVE_MUSIC_PAUSED:
                self.state_machine.transition_to(
                    AppState.PAUSED,
                    "call_ended_stay_paused"
                )
            elif current_state in (AppState.CALL_INCOMING, AppState.PAUSED_BY_CALL):
                self.state_machine.transition_to(
                    AppState.PAUSED,
                    "reject_call_stay_paused"
                )

        else:
            # No music was playing, return to idle or menu
            logger.info("  No music to resume")
            if self.state_machine.current_state == AppState.CALL_ACTIVE:
                self.state_machine.transition_to(
                    AppState.CALL_IDLE,
                    "call_ended"
                )

        # Reset flag
        self.music_was_playing_before_call = False

    def _handle_registration_change(self, state: RegistrationState) -> None:
        """
        Handle VoIP registration state changes.

        Args:
            state: New registration state
        """
        logger.info(f"📞 VoIP registration: {state.value}")

        self.voip_registered = (state == RegistrationState.OK)

        if state == RegistrationState.OK:
            logger.info("  ✓ VoIP ready to receive calls")
            # If music is playing, upgrade to PLAYING_WITH_VOIP
            if self.state_machine.current_state == AppState.PLAYING:
                self.state_machine.transition_to(
                    AppState.PLAYING_WITH_VOIP,
                    "voip_ready"
                )
        elif state == RegistrationState.FAILED:
            logger.warning("  ⚠ VoIP registration failed")

        # Update call screen if visible
        if self.screen_manager.current_screen == self.call_screen:
            self.call_screen.render()
            logger.debug("  → Call screen refreshed")

    # ========================================================================
    # Music Event Handlers
    # ========================================================================

    def _handle_track_change(self, track: Optional[MopidyTrack]) -> None:
        """
        Handle music track changes.

        Args:
            track: New track (None if playback stopped)
        """
        if track:
            logger.info(f"🎵 Track changed: {track.name} - {track.get_artist_string()}")
        else:
            logger.info("🎵 Playback stopped")

            # If we're in PLAYING_WITH_VOIP and track is None, music may have stopped
            if self.state_machine.is_music_playing():
                logger.warning("  Track is None but state is playing - music may have stopped")
                # Transition to paused to reflect reality
                self.state_machine.transition_to(
                    AppState.PAUSED,
                    "pause"
                )

        # Update now playing screen if visible
        if self.screen_manager.current_screen == self.now_playing_screen:
            self.now_playing_screen.render()
            logger.debug("  → Now playing screen refreshed")

    def _handle_playback_state_change(self, playback_state: str) -> None:
        """
        Handle music playback state changes.

        Syncs state machine with actual mopidy playback state.

        Args:
            playback_state: New playback state (playing/paused/stopped)
        """
        logger.info(f"🎵 Playback state changed: {playback_state}")

        # Only sync state machine if we're not in a call
        # (during calls, call logic handles music states)
        if self.state_machine.is_call_active():
            logger.debug("  → In call, state machine managed by call logic")
            return

        # Sync state machine with actual playback state
        current_state = self.state_machine.current_state

        if playback_state == "playing":
            if self.voip_registered:
                if current_state == AppState.PAUSED:
                    self.state_machine.transition_to(
                        AppState.PLAYING_WITH_VOIP,
                        "resume"
                    )
                elif current_state == AppState.PLAYING:
                    self.state_machine.transition_to(
                        AppState.PLAYING_WITH_VOIP,
                        "voip_ready"
                    )
                elif current_state == AppState.MENU:
                    self.state_machine.transition_to(
                        AppState.PLAYING_WITH_VOIP,
                        "select_media_with_voip"
                    )
            else:
                if current_state == AppState.PAUSED:
                    self.state_machine.transition_to(
                        AppState.PLAYING,
                        "resume"
                    )
                elif current_state == AppState.MENU:
                    self.state_machine.transition_to(
                        AppState.PLAYING,
                        "select_media"
                    )

        elif playback_state in ("paused", "stopped"):
            if self.state_machine.is_music_playing() and current_state != AppState.PAUSED:
                self.state_machine.transition_to(
                    AppState.PAUSED,
                    "pause"
                )

        # Refresh NowPlayingScreen if visible to reflect new state
        if self.screen_manager.current_screen == self.now_playing_screen:
            self.now_playing_screen.render()
            logger.debug("  → Now playing screen refreshed")

    # ========================================================================
    # State Machine Callbacks
    # ========================================================================

    def _on_enter_playing_with_voip(self) -> None:
        """Callback when entering PLAYING_WITH_VOIP state."""
        logger.info("🎵 → Music playing with VoIP ready")

    def _on_enter_call_active_music_paused(self) -> None:
        """Callback when entering CALL_ACTIVE_MUSIC_PAUSED state."""
        logger.info("📞 → In call (music paused in background)")

    # ========================================================================
    # Public Methods
    # ========================================================================

    def run(self) -> None:
        """
        Run the main application loop.

        This is a blocking call that runs until the app is stopped.
        """
        logger.info("=" * 60)
        logger.info("YoyoPod Running")
        logger.info("=" * 60)
        logger.info("")
        logger.info("State Machine Status:")
        logger.info(f"  Current state: {self.state_machine.get_state_name()}")
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
            logger.info(f"  Connected: True")
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
            # Main loop
            last_screen_update = time.time()
            screen_update_interval = 1.0  # Update every second

            if self.simulate:
                # Simulation mode: just keep alive
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
            else:
                # Hardware mode: input handler manages button events
                # Also update NowPlayingScreen periodically for progress animation
                while True:
                    time.sleep(0.1)
                    self._process_pending_main_thread_actions()

                    # Check if it's time to update the screen
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

        # Stop VoIP manager
        if self.voip_manager:
            logger.info("  - Stopping VoIP manager")
            self.voip_manager.stop()

        # Stop music polling
        if self.mopidy_client:
            logger.info("  - Stopping music polling")
            self.mopidy_client.stop_polling()
            self.mopidy_client.cleanup()

        # Stop input handler
        if self.input_manager:
            logger.info("  - Stopping input manager")
            self.input_manager.stop()

        pending_actions = self._process_pending_main_thread_actions()
        if pending_actions:
            logger.info(f"  - Processed {pending_actions} queued app events during shutdown")

        # Clear display
        if self.display:
            logger.info("  - Clearing display")
            self.display.clear(self.display.COLOR_BLACK)
            self.display.text(
                "Goodbye!",
                70, 120,
                color=self.display.COLOR_CYAN,
                font_size=20
            )
            self.display.update()
            time.sleep(1)
            self.display.cleanup()

        logger.info("✓ YoyoPod stopped")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current application status.

        Returns:
            Status dictionary
        """
        return {
            'state': self.state_machine.get_state_name(),
            'voip_registered': self.voip_registered,
            'music_was_playing': self.music_was_playing_before_call,
            'auto_resume': self.auto_resume_after_call,
            'voip_available': self.voip_manager is not None,
            'music_available': self.mopidy_client is not None and self.mopidy_client.is_connected
        }
