"""
Call-event coordination for YoyoPod.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from loguru import logger

from yoyopod.coordinators.registry import AppRuntimeState, CoordinatorRuntime
from yoyopod.coordinators.screen import ScreenCoordinator
from yoyopod.core import EventBus
from yoyopod.core import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    RegistrationChangedEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopod.integrations.call import (
    CallHistoryStore,
    CallSessionState,
    CallSessionTracker,
    CallState,
    RegistrationState,
    sync_context_voip_status,
)


class CallCoordinator:
    """Own VoIP event publishing and main-thread call orchestration."""

    def __init__(
        self,
        runtime: CoordinatorRuntime,
        screen_coordinator: ScreenCoordinator,
        auto_resume_after_call: bool,
        call_history_store: CallHistoryStore | None = None,
        initial_voip_registered: bool = False,
    ) -> None:
        self.runtime = runtime
        self.screen_coordinator = screen_coordinator
        self.auto_resume_after_call = auto_resume_after_call
        self.call_history_store = call_history_store
        self.voip_registered = initial_voip_registered
        self.ringing_process: Optional[subprocess.Popen] = None
        self._event_bus: Optional[EventBus] = None
        self._bound = False
        self._session_tracker = CallSessionTracker(call_history_store)

    def bind(self, event_bus: EventBus) -> None:
        """Bind typed event subscriptions once."""
        if self._bound:
            return

        self._event_bus = event_bus
        event_bus.subscribe(IncomingCallEvent, self._on_incoming_call_event)
        event_bus.subscribe(CallStateChangedEvent, self._on_call_state_changed_event)
        event_bus.subscribe(CallEndedEvent, self._on_call_ended_event)
        event_bus.subscribe(RegistrationChangedEvent, self._on_registration_changed_event)
        event_bus.subscribe(VoIPAvailabilityChangedEvent, self._on_availability_changed_event)
        self._bound = True

    def publish_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Publish an incoming-call event from the VoIP manager thread."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(
            IncomingCallEvent(caller_address=caller_address, caller_name=caller_name)
        )

    def publish_call_state_events(self, state: CallState) -> None:
        """Publish call state events onto the bus."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(CallStateChangedEvent(state=state))

    def publish_registration_change(self, state: RegistrationState) -> None:
        """Publish registration changes from the VoIP manager thread."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(RegistrationChangedEvent(state=state))

    def publish_availability_change(
        self,
        available: bool,
        reason: str = "",
        registration_state: RegistrationState = RegistrationState.NONE,
    ) -> None:
        """Publish backend availability changes from VoIP threads."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(
            VoIPAvailabilityChangedEvent(
                available=available,
                reason=reason,
                registration_state=registration_state,
            )
        )

    def start_ringing(self) -> None:
        """Start playing the ring tone for an incoming call."""
        self.stop_ringing()

        try:
            ring_output_device = None
            speaker_test_path = "speaker-test"
            if self.runtime.config_manager:
                ring_output_device = self.runtime.config_manager.get_ring_output_device()
                speaker_test_path = self.runtime.config_manager.get_speaker_test_path()

            command = [
                speaker_test_path,
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
                stderr=subprocess.DEVNULL,
            )
            logger.debug("Ring tone started")
        except Exception as exc:
            logger.warning(f"Failed to start ring tone: {exc}")

    def stop_ringing(self) -> None:
        """Stop playing the ring tone."""
        if self.ringing_process:
            try:
                self.ringing_process.terminate()
                self.ringing_process.wait(timeout=1.0)
                logger.debug("Ring tone stopped")
            except Exception as exc:
                logger.warning(f"Failed to stop ring tone: {exc}")
            finally:
                self.ringing_process = None

    def cleanup(self) -> None:
        """Clean up call-related coordinator state."""
        self.stop_ringing()

    def on_enter_call_active_music_paused(self) -> None:
        """Log entry into the active-call-with-paused-music state."""
        logger.info("In call (music paused in background)")

    def _on_incoming_call_event(self, event: IncomingCallEvent) -> None:
        self.handle_incoming_call(event.caller_address, event.caller_name)

    def _on_call_state_changed_event(self, event: CallStateChangedEvent) -> None:
        self.handle_call_state_change(event.state)

    def _on_call_ended_event(self, event: CallEndedEvent) -> None:
        self.handle_call_ended(reason=event.reason)

    def _on_registration_changed_event(self, event: RegistrationChangedEvent) -> None:
        self.handle_registration_change(event.state)

    def _on_availability_changed_event(self, event: VoIPAvailabilityChangedEvent) -> None:
        self.handle_availability_change(
            event.available,
            event.reason,
            event.registration_state,
        )

    def handle_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Capture incoming-call metadata for the active incoming phase."""
        logger.info(f"Incoming call metadata: {caller_name} ({caller_address})")
        self._session_tracker.begin_incoming_call(caller_address, caller_name)
        self._present_incoming_call_if_ready()

    def handle_call_state_change(self, state: CallState) -> None:
        """Coordinate high-level call state updates."""
        logger.info(f"Call state changed: {state.value}")

        if state in (
            CallState.OUTGOING,
            CallState.OUTGOING_PROGRESS,
            CallState.OUTGOING_RINGING,
            CallState.OUTGOING_EARLY_MEDIA,
        ):
            self._pause_music_for_call(phase="outgoing")
            session = self._session_tracker.ensure_outgoing_call(self.runtime.current_caller_info())
            self.runtime.call_fsm.transition("dial")
            self.runtime.sync_app_state("call_outgoing")
            self.screen_coordinator.show_outgoing_call(
                session.sip_address,
                session.display_name,
            )
            return

        if state == CallState.INCOMING:
            self._pause_music_for_call(phase="incoming")
            self.runtime.call_fsm.transition("incoming")
            self.runtime.sync_app_state("call_incoming_state")
            self._present_incoming_call_if_ready()
            return

        if state in (CallState.CONNECTED, CallState.STREAMS_RUNNING):
            self._session_tracker.mark_answered()
            self.runtime.call_fsm.transition("connect")
            state_change = self.runtime.sync_app_state("call_connected")
            if state_change.entered(AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED):
                logger.info("In call (music paused in background)")
            self.screen_coordinator.show_in_call()
            self.stop_ringing()
            return

        if state in (CallState.RELEASED, CallState.END, CallState.ERROR):
            if not self._has_live_call_state():
                logger.debug("Ignoring duplicate terminal call state {}", state.value)
                return

            local_end_action = self._consume_pending_terminal_action()
            self._session_tracker.mark_terminal_state(
                state,
                local_end_action=local_end_action,
            )
            self.handle_call_ended(reason=state.value)
            return

        logger.debug("Call state {} does not change coordinator phase", state.value)

    def handle_call_ended(self, *, reason: str = "released") -> None:
        """Coordinate call cleanup and possible music resume."""
        if not self.runtime.call_fsm.is_active and not self._session_tracker.has_live_session:
            logger.warning(
                "Ignoring terminal call teardown without an active session (reason: {})",
                reason,
            )
            self.stop_ringing()
            self._session_tracker.clear_pending_incoming_call()
            self.screen_coordinator.pop_call_screens()
            self.runtime.sync_app_state(f"call_ended:{reason}")
            return

        logger.info("Call ended ({})", reason)

        self.stop_ringing()
        self._session_tracker.clear_pending_incoming_call()
        self._finalize_call_history()
        self.screen_coordinator.pop_call_screens()

        should_resume = self.runtime.call_interruption_policy.should_auto_resume(
            self.auto_resume_after_call
        )
        if self.runtime.call_fsm.is_active:
            self.runtime.call_fsm.transition("end")
        else:
            self.runtime.call_fsm.sync(CallSessionState.IDLE)

        if should_resume:
            if self._resume_music_after_call():
                logger.info("Auto-resumed music after call")
            else:
                logger.warning("Music remains paused after failed auto-resume")
                self.runtime.music_fsm.transition("pause")
        elif self.runtime.call_interruption_policy.music_interrupted_by_call:
            logger.info("Music stays paused (auto-resume disabled)")
            self.runtime.music_fsm.transition("pause")
        else:
            logger.info("No music to resume")

        self.runtime.call_interruption_policy.clear()
        self.runtime.sync_app_state("call_ended")

    def handle_registration_change(self, state: RegistrationState) -> None:
        """Coordinate registration updates and VoIP availability state."""
        logger.info(f"VoIP registration: {state.value}")

        self.voip_registered = state == RegistrationState.OK
        self.runtime.set_voip_ready(self.voip_registered)
        sync_context_voip_status(
            self.runtime.context,
            config_manager=self.runtime.config_manager,
            ready=self.voip_registered,
            running=True,
            registration_state=state,
        )

        if state == RegistrationState.OK:
            logger.info("VoIP ready to receive calls")
        elif state == RegistrationState.FAILED:
            logger.warning("VoIP registration failed")

        self.screen_coordinator.refresh_call_screen_if_visible()

    def handle_availability_change(
        self,
        available: bool,
        reason: str,
        registration_state: RegistrationState = RegistrationState.NONE,
    ) -> None:
        """Coordinate backend availability changes and forced call cleanup."""
        self.voip_registered = registration_state == RegistrationState.OK
        self.runtime.set_voip_ready(self.voip_registered)

        if available:
            logger.info(f"VoIP backend available ({reason or 'ready'})")
            sync_context_voip_status(
                self.runtime.context,
                config_manager=self.runtime.config_manager,
                ready=self.voip_registered,
                running=True,
                registration_state=registration_state,
            )
            self.screen_coordinator.refresh_call_screen_if_visible()
            return

        logger.warning(f"VoIP backend unavailable ({reason or 'unknown'})")
        sync_context_voip_status(
            self.runtime.context,
            config_manager=self.runtime.config_manager,
            ready=False,
            running=False,
            registration_state=registration_state,
        )
        self.stop_ringing()
        self.screen_coordinator.refresh_call_screen_if_visible()

        if self.runtime.call_fsm.is_active or self._session_tracker.has_live_session:
            self.handle_call_ended(reason=reason or "unavailable")

    def _pause_music_for_call(self, *, phase: str) -> None:
        """Pause active playback once when a call enters an interruption phase."""

        if self.runtime.call_interruption_policy.music_interrupted_by_call:
            return

        if self.runtime.music_backend is None or not self.runtime.music_backend.is_connected:
            logger.debug("Skipping auto-pause for {} call: music backend unavailable", phase)
            return

        if self.runtime.music_backend.get_playback_state() != "playing":
            return

        logger.info("Auto-pausing music for {} call", phase)
        if not self.runtime.music_backend.pause():
            logger.warning("Failed to auto-pause music for {} call", phase)
            return

        self.runtime.call_interruption_policy.mark_paused_for_call(self.runtime.music_fsm)

    def _resume_music_after_call(self) -> bool:
        """Resume interrupted music only when the backend confirms the command."""

        if self.runtime.music_backend is None or not self.runtime.music_backend.is_connected:
            logger.warning("Cannot auto-resume music after call: music backend unavailable")
            return False

        if not self.runtime.music_backend.play():
            return False

        self.runtime.music_fsm.transition("play")
        self.screen_coordinator.refresh_now_playing_screen()
        return True

    def _present_incoming_call_if_ready(self) -> None:
        """Show the incoming-call screen once state and caller metadata are both known."""

        if self.runtime.call_fsm.state != CallSessionState.INCOMING:
            return
        if self._session_tracker.pending_incoming_call is None:
            logger.debug("Incoming call phase entered before caller metadata arrived")
            return

        caller_address, caller_name = self._session_tracker.pending_incoming_call
        self.screen_coordinator.show_incoming_call(caller_address, caller_name)
        self.start_ringing()

    def _has_live_call_state(self) -> bool:
        """Return whether the coordinator still has a live call to tear down."""

        return self.runtime.call_fsm.is_active or self._session_tracker.has_live_session

    def _consume_pending_terminal_action(self) -> str | None:
        """Return any locally initiated teardown action awaiting terminal backend state."""

        voip_manager = self.runtime.current_voip_manager()
        consume_action = getattr(voip_manager, "consume_pending_terminal_action", None)
        if callable(consume_action):
            return consume_action()
        return None

    def _finalize_call_history(self) -> None:
        """Persist the just-finished call into the Talk history store."""

        self._session_tracker.finalize(
            call_duration_seconds=self.runtime.current_call_duration_seconds(),
        )
        self._publish_call_summary_to_context()

    def _publish_call_summary_to_context(self) -> None:
        """Refresh Talk summary data stored in the shared app context."""

        if self.runtime.context is None or self.call_history_store is None:
            return

        self.runtime.context.update_call_summary(
            missed_calls=self.call_history_store.missed_count(),
            recent_calls=self.call_history_store.recent_preview(),
        )
