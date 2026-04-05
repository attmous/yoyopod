"""
Call-event coordination for YoyoPod.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from loguru import logger

from yoyopy.coordinators.runtime import AppRuntimeState, CoordinatorRuntime
from yoyopy.coordinators.screen import ScreenCoordinator
from yoyopy.event_bus import EventBus
from yoyopy.events import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    RegistrationChangedEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopy.voip import CallState, RegistrationState


class CallCoordinator:
    """Own VoIP event publishing and main-thread call orchestration."""

    def __init__(
        self,
        runtime: CoordinatorRuntime,
        screen_coordinator: ScreenCoordinator,
        auto_resume_after_call: bool,
        initial_voip_registered: bool = False,
    ) -> None:
        self.runtime = runtime
        self.screen_coordinator = screen_coordinator
        self.auto_resume_after_call = auto_resume_after_call
        self.voip_registered = initial_voip_registered
        self.handling_incoming_call = False
        self.ringing_process: Optional[subprocess.Popen] = None
        self._event_bus: Optional[EventBus] = None
        self._bound = False

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
        if state == CallState.RELEASED:
            self._event_bus.publish(CallEndedEvent())

    def publish_registration_change(self, state: RegistrationState) -> None:
        """Publish registration changes from the VoIP manager thread."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(RegistrationChangedEvent(state=state))

    def publish_availability_change(self, available: bool, reason: str = "") -> None:
        """Publish backend availability changes from VoIP threads."""
        if self._event_bus is None:
            raise RuntimeError("CallCoordinator is not bound to an EventBus")

        self._event_bus.publish(VoIPAvailabilityChangedEvent(available=available, reason=reason))

    def start_ringing(self) -> None:
        """Start playing the ring tone for an incoming call."""
        self.stop_ringing()

        try:
            ring_output_device = self.runtime.config.get("audio", {}).get("ring_output_device")
            if not ring_output_device and self.runtime.config_manager:
                ring_output_device = self.runtime.config_manager.get_ring_output_device()

            command = [
                self.runtime.config.get("audio", {}).get("speaker_test_path", "speaker-test"),
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
            logger.debug("🔔 Ring tone started")
        except Exception as exc:
            logger.warning(f"Failed to start ring tone: {exc}")

    def stop_ringing(self) -> None:
        """Stop playing the ring tone."""
        if self.ringing_process:
            try:
                self.ringing_process.terminate()
                self.ringing_process.wait(timeout=1.0)
                logger.debug("🔕 Ring tone stopped")
            except Exception as exc:
                logger.warning(f"Failed to stop ring tone: {exc}")
            finally:
                self.ringing_process = None

    def cleanup(self) -> None:
        """Clean up call-related coordinator state."""
        self.stop_ringing()

    def on_enter_call_active_music_paused(self) -> None:
        """Log entry into the active-call-with-paused-music state."""
        logger.info("🎞 → In call (music paused in background)")

    def _on_incoming_call_event(self, event: IncomingCallEvent) -> None:
        self.handle_incoming_call(event.caller_address, event.caller_name)

    def _on_call_state_changed_event(self, event: CallStateChangedEvent) -> None:
        self.handle_call_state_change(event.state)

    def _on_call_ended_event(self, event: CallEndedEvent) -> None:
        self.handle_call_ended()

    def _on_registration_changed_event(self, event: RegistrationChangedEvent) -> None:
        self.handle_registration_change(event.state)

    def _on_availability_changed_event(self, event: VoIPAvailabilityChangedEvent) -> None:
        self.handle_availability_change(event.available, event.reason)

    def handle_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Coordinate music pause and UI transitions for an incoming call."""
        if self.handling_incoming_call:
            logger.debug(f"  (Already handling call from {caller_name})")
            return

        self.handling_incoming_call = True
        logger.info(f"📞 INCOMING CALL: {caller_name} ({caller_address})")

        playback_state = (
            self.runtime.mopidy_client.get_playback_state()
            if self.runtime.mopidy_client and self.runtime.mopidy_client.is_connected
            else "stopped"
        )

        if playback_state == "playing":
            logger.info("  🎵 Auto-pausing music for incoming call")
            self.runtime.call_interruption_policy.pause_for_call(self.runtime.music_fsm)
            if self.runtime.mopidy_client:
                self.runtime.mopidy_client.pause()

        self.runtime.call_fsm.transition("incoming")
        self.runtime.sync_app_state("incoming_call")

        self.screen_coordinator.show_incoming_call(caller_address, caller_name)
        self.start_ringing()

    def handle_call_state_change(self, state: CallState) -> None:
        """Coordinate high-level call state updates."""
        logger.info(f"📞 Call state changed: {state.value}")

        if state in (
            CallState.OUTGOING,
            CallState.OUTGOING_PROGRESS,
            CallState.OUTGOING_RINGING,
            CallState.OUTGOING_EARLY_MEDIA,
        ):
            self.runtime.call_fsm.transition("dial")
            self.runtime.sync_app_state("call_outgoing")
            return

        if state == CallState.INCOMING:
            self.runtime.call_fsm.transition("incoming")
            self.runtime.sync_app_state("call_incoming_state")
            return

        if state in (CallState.CONNECTED, CallState.STREAMS_RUNNING):
            self.runtime.call_fsm.transition("connect")
            state_change = self.runtime.sync_app_state("call_connected")
            if state_change.entered(AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED):
                logger.info("In call (music paused in background)")
            self.screen_coordinator.show_in_call()
            self.stop_ringing()

    def handle_call_ended(self) -> None:
        """Coordinate call cleanup and possible music resume."""
        logger.info("📞 Call ended")

        self.stop_ringing()
        self.handling_incoming_call = False
        self.screen_coordinator.pop_call_screens()

        should_resume = self.runtime.call_interruption_policy.should_auto_resume(
            self.auto_resume_after_call
        )
        self.runtime.call_fsm.transition("end")

        if should_resume:
            logger.info("  🎵 Auto-resuming music after call")
            if self.runtime.mopidy_client:
                self.runtime.mopidy_client.play()
            self.runtime.music_fsm.transition("play")
            self.screen_coordinator.refresh_now_playing_screen()
        elif self.runtime.call_interruption_policy.music_interrupted_by_call:
            logger.info("  🎵 Music stays paused (auto-resume disabled)")
            self.runtime.music_fsm.transition("pause")
        else:
            logger.info("  No music to resume")

        self.runtime.call_interruption_policy.clear()
        self.runtime.sync_app_state("call_ended")

    def handle_registration_change(self, state: RegistrationState) -> None:
        """Coordinate registration updates and VoIP availability state."""
        logger.info(f"📞 VoIP registration: {state.value}")

        self.voip_registered = state == RegistrationState.OK
        self.runtime.set_voip_ready(self.voip_registered)
        if self.runtime.context is not None:
            self.runtime.context.update_voip_status(
                configured=self._is_voip_configured(),
                ready=self.voip_registered,
            )

        if state == RegistrationState.OK:
            logger.info("  ✓ VoIP ready to receive calls")
        elif state == RegistrationState.FAILED:
            logger.warning("  ⚠ VoIP registration failed")

        self.screen_coordinator.refresh_call_screen_if_visible()

    def handle_availability_change(self, available: bool, reason: str) -> None:
        """Coordinate backend availability changes and forced call cleanup."""
        if available:
            logger.info(f"VoIP backend available ({reason or 'ready'})")
            if self.runtime.context is not None:
                self.runtime.context.update_voip_status(
                    configured=self._is_voip_configured(),
                    ready=self.voip_registered,
                )
            self.screen_coordinator.refresh_call_screen_if_visible()
            return

        logger.warning(f"VoIP backend unavailable ({reason or 'unknown'})")
        self.voip_registered = False
        self.runtime.set_voip_ready(False, trigger=f"voip_{reason or 'unavailable'}")
        if self.runtime.context is not None:
            self.runtime.context.update_voip_status(
                configured=self._is_voip_configured(),
                ready=False,
            )
        self.stop_ringing()
        self.screen_coordinator.refresh_call_screen_if_visible()

        if self.runtime.call_fsm.is_active:
            self.handle_call_ended()

    def _is_voip_configured(self) -> bool:
        """Return whether the app has meaningful SIP identity data configured."""

        if self.runtime.config_manager is not None:
            if self.runtime.config_manager.get_sip_identity().strip():
                return True
            if self.runtime.config_manager.get_sip_username().strip():
                return True

        config_file = self.runtime.config.get("voip", {}).get("config_file")
        return bool(config_file)
