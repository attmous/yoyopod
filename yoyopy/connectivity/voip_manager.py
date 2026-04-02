"""App-facing VoIP facade built on top of typed backend events."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from loguru import logger

from yoyopy.connectivity.voip_backend import LinphonecBackend, VoIPBackend
from yoyopy.connectivity.voip_types import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
)


class VoIPManager:
    """Application-facing VoIP facade that delegates subprocess work to a backend."""

    def __init__(
        self,
        config: VoIPConfig,
        config_manager=None,
        backend: Optional[VoIPBackend] = None,
    ) -> None:
        self.config = config
        self.config_manager = config_manager
        self.backend = backend or LinphonecBackend(config)
        self.running = False
        self.registered = False
        self.registration_state = RegistrationState.NONE
        self.call_state = CallState.IDLE
        self.current_call_id: Optional[str] = None
        self.caller_address: Optional[str] = None
        self.caller_name: Optional[str] = None
        self.call_duration: int = 0
        self.call_start_time: Optional[float] = None
        self.is_muted = False

        self.registration_callbacks: list[Callable[[RegistrationState], None]] = []
        self.call_state_callbacks: list[Callable[[CallState], None]] = []
        self.incoming_call_callbacks: list[Callable[[str, str], None]] = []
        self.availability_callbacks: list[Callable[[bool, str], None]] = []

        self.duration_thread: Optional[threading.Thread] = None
        self.duration_stop_event = threading.Event()
        self._stopping = False

        self.backend.on_event(self._handle_backend_event)
        logger.info(f"VoIPManager initialized (server: {config.sip_server})")

    def start(self) -> bool:
        """Start the configured VoIP backend."""

        if self.running:
            logger.warning("VoIP manager already running")
            return True

        self.running = self.backend.start()
        if not self.running:
            self._update_registration_state(RegistrationState.FAILED)
        self._notify_availability_change(self.running, "started" if self.running else "start_failed")
        return self.running

    def stop(self, notify_events: bool = True) -> None:
        """Stop the backend and optionally suppress teardown callbacks."""

        logger.info("Stopping VoIP manager...")
        self._stopping = True
        try:
            self._stop_call_timer()
            self.backend.stop()
            self._apply_stopped_state()
            if notify_events:
                self._notify_availability_change(False, "stopped")
        finally:
            self._stopping = False
        logger.info("VoIP manager stopped")

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        """Initiate an outgoing call."""

        if not self.registered:
            logger.error("Cannot make call: not registered")
            return False

        self.caller_address = sip_address
        self.caller_name = contact_name or self._lookup_contact_name(sip_address)
        logger.info(f"Making call to: {self.caller_name} ({sip_address})")
        return self.backend.make_call(sip_address)

    def answer_call(self) -> bool:
        """Answer an incoming call."""

        logger.info("Answering call")
        return self.backend.answer_call()

    def hangup(self) -> bool:
        """Hang up the current call."""

        logger.info("Hanging up call")
        return self.backend.hangup()

    def reject_call(self) -> bool:
        """Reject an incoming call."""

        logger.info("Rejecting call")
        return self.backend.reject_call()

    def mute(self) -> bool:
        """Mute the current call microphone."""

        if self.is_muted:
            return False
        logger.info("Muting microphone")
        if self.backend.mute():
            self.is_muted = True
            return True
        return False

    def unmute(self) -> bool:
        """Unmute the current call microphone."""

        if not self.is_muted:
            return False
        logger.info("Unmuting microphone")
        if self.backend.unmute():
            self.is_muted = False
            return True
        return False

    def toggle_mute(self) -> bool:
        """Toggle microphone mute state."""

        if self.is_muted:
            self.unmute()
            return False
        self.mute()
        return True

    def get_status(self) -> dict:
        """Return the current VoIP status."""

        return {
            "running": self.running,
            "registered": self.registered,
            "registration_state": self.registration_state.value,
            "call_state": self.call_state.value,
            "call_id": self.current_call_id,
            "sip_identity": self.config.sip_identity,
        }

    def on_registration_change(self, callback: Callable[[RegistrationState], None]) -> None:
        """Register a callback for SIP registration changes."""

        self.registration_callbacks.append(callback)

    def on_call_state_change(self, callback: Callable[[CallState], None]) -> None:
        """Register a callback for call-state changes."""

        self.call_state_callbacks.append(callback)

    def on_incoming_call(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for incoming call notifications."""

        self.incoming_call_callbacks.append(callback)

    def on_availability_change(self, callback: Callable[[bool, str], None]) -> None:
        """Register a callback for backend availability changes."""

        self.availability_callbacks.append(callback)

    def get_call_duration(self) -> int:
        """Return the current call duration in seconds."""

        if self.call_start_time and self.call_state in (
            CallState.CONNECTED,
            CallState.STREAMS_RUNNING,
        ):
            return int(time.time() - self.call_start_time)
        return 0

    def get_caller_info(self) -> dict:
        """Return information about the active caller or callee."""

        if self.caller_address and not self.caller_name:
            self.caller_name = self._lookup_contact_name(self.caller_address)

        return {
            "address": self.caller_address,
            "name": self.caller_name or self.caller_address,
            "display_name": self.caller_name or self._lookup_contact_name(self.caller_address),
        }

    def cleanup(self) -> None:
        """Clean up all VoIP resources."""

        self._stop_call_timer()
        self.stop()
        logger.info("VoIP manager cleaned up")

    def _handle_backend_event(self, event: VoIPEvent) -> None:
        """Apply a typed backend event to the manager state and callbacks."""
        if self._stopping:
            logger.debug(f"Ignoring VoIP backend event during shutdown: {event!r}")
            return

        if isinstance(event, RegistrationStateChanged):
            self._update_registration_state(event.state)
            return
        if isinstance(event, CallStateChanged):
            self._update_call_state(event.state)
            return
        if isinstance(event, IncomingCallDetected):
            self._handle_incoming_call_event(event.caller_address)
            return
        if isinstance(event, BackendStopped):
            logger.warning(f"VoIP backend stopped unexpectedly: {event.reason or 'unknown'}")
            if self.call_state not in (CallState.IDLE, CallState.RELEASED):
                self._update_call_state(CallState.RELEASED)
            self._update_registration_state(RegistrationState.FAILED)
            self.running = False
            self._notify_availability_change(False, event.reason or "backend_stopped")

    def _handle_incoming_call_event(self, caller_address: str) -> None:
        """Resolve caller metadata and notify incoming-call callbacks."""

        self.caller_address = caller_address
        self.caller_name = self._lookup_contact_name(caller_address)

        for callback in self.incoming_call_callbacks:
            try:
                callback(
                    caller_address,
                    self.caller_name or self._extract_username(caller_address),
                )
            except Exception as exc:
                logger.error(f"Error in incoming call callback: {exc}")

    def _update_registration_state(self, state: RegistrationState) -> None:
        """Update registration state and fire callbacks when it changes."""

        if state == self.registration_state:
            return

        old_state = self.registration_state
        self.registration_state = state
        self.registered = state == RegistrationState.OK

        logger.info(f"Registration state: {old_state.value} -> {state.value}")
        for callback in self.registration_callbacks:
            try:
                callback(state)
            except Exception as exc:
                logger.error(f"Error in registration callback: {exc}")

    def _update_call_state(self, state: CallState) -> None:
        """Update call state and fire callbacks when it changes."""

        if state == self.call_state:
            return

        old_state = self.call_state
        self.call_state = state
        logger.info(f"Call state: {old_state.value} -> {state.value}")

        if state == CallState.CONNECTED and self.call_start_time is None:
            self._start_call_timer()
        elif state == CallState.RELEASED:
            self._clear_call_session()

        for callback in self.call_state_callbacks:
            try:
                callback(state)
            except Exception as exc:
                logger.error(f"Error in call state callback: {exc}")

    def _extract_username(self, sip_address: Optional[str]) -> str:
        """Extract a displayable username from a SIP address."""

        if not sip_address:
            return "Unknown"

        if "@" in sip_address:
            username_part = sip_address.split("@", 1)[0]
            if ":" in username_part:
                return username_part.split(":")[-1]
            return username_part
        return sip_address

    def _lookup_contact_name(self, sip_address: Optional[str]) -> str:
        """Look up a contact name for a SIP address."""

        if not sip_address:
            return "Unknown"

        if self.config_manager is not None:
            contact = self.config_manager.get_contact_by_address(sip_address)
            if contact:
                logger.debug(f"Found contact: {contact.name} for {sip_address}")
                return contact.name

        return self._extract_username(sip_address)

    def _start_call_timer(self) -> None:
        """Start tracking the duration of the active call."""

        self.call_start_time = time.time()
        self.call_duration = 0
        self.duration_stop_event.clear()
        self.duration_thread = threading.Thread(target=self._track_duration, daemon=True)
        self.duration_thread.start()
        logger.debug("Call duration timer started")

    def _stop_call_timer(self) -> None:
        """Stop tracking call duration."""

        self.duration_stop_event.set()
        if self.duration_thread is not None:
            self.duration_thread.join(timeout=1)
            self.duration_thread = None
        self.call_start_time = None
        self.call_duration = 0
        logger.debug("Call duration timer stopped")

    def _clear_call_session(self) -> None:
        """Clear active call metadata without notifying callbacks."""
        self._stop_call_timer()
        self.current_call_id = None
        self.caller_address = None
        self.caller_name = None
        self.is_muted = False

    def _apply_stopped_state(self) -> None:
        """Apply teardown state without emitting lifecycle callbacks."""
        if self.call_state not in (CallState.IDLE, CallState.RELEASED):
            self.call_state = CallState.RELEASED
        self._clear_call_session()
        self.running = False
        self.registered = False
        self.registration_state = RegistrationState.NONE

    def _track_duration(self) -> None:
        """Background loop that updates the active call duration."""

        while not self.duration_stop_event.is_set():
            if self.call_start_time is not None:
                self.call_duration = int(time.time() - self.call_start_time)
            time.sleep(1)

    def _notify_availability_change(self, available: bool, reason: str) -> None:
        """Notify listeners that backend availability changed."""
        for callback in self.availability_callbacks:
            try:
                callback(available, reason)
            except Exception as exc:
                logger.error(f"Error in availability callback: {exc}")
