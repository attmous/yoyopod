"""App-facing VoIP facade built on top of Liblinphone backend events."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPBackend
from yoyopod.backends.voip import LiblinphoneBackend
from yoyopod.integrations.call.messaging import MessagingService
from yoyopod.integrations.call.message_store import VoIPMessageStore
from yoyopod.integrations.call.models import (
    BackendRecovered,
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDownloadCompleted,
    MessageFailed,
    MessageReceived,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
    VoIPRuntimeSnapshotChanged,
)
from yoyopod.integrations.call.voice_notes import VoiceNoteDraft, VoiceNoteService

if TYPE_CHECKING:
    from yoyopod.integrations.contacts.directory import PeopleManager


@dataclass(frozen=True, slots=True)
class VoIPIterateSnapshot:
    """Latest iterate timing sample reported by one backend execution lane."""

    sample_id: int = 0
    last_started_at: float = 0.0
    last_completed_at: float = 0.0
    schedule_delay_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    native_duration_seconds: float = 0.0
    event_drain_duration_seconds: float = 0.0
    drained_events: int = 0
    interval_seconds: float = 0.0
    in_flight: bool = False


class VoIPManager:
    """Application-facing VoIP facade over Liblinphone calls and messages."""

    def __init__(
        self,
        config: VoIPConfig,
        people_directory: "PeopleManager | None" = None,
        backend: VoIPBackend | None = None,
        message_store: VoIPMessageStore | None = None,
        event_scheduler: Callable[[Callable[[], None]], None] | None = None,
        background_iterate_enabled: bool = False,
    ) -> None:
        self.config = config
        self.people_directory = people_directory
        self.backend = backend or LiblinphoneBackend(config)
        self.running = False
        self.registered = False
        self.registration_state = RegistrationState.NONE
        self.call_state = CallState.IDLE
        self.current_call_id: str | None = None
        self.caller_address: str | None = None
        self.caller_name: str | None = None
        self.call_start_time: float | None = None
        self.is_muted = False
        self._runtime_snapshot: VoIPRuntimeSnapshot | None = None
        self._pending_terminal_action: str | None = None
        self._message_store = message_store or self._build_message_store()
        self._messaging_service = MessagingService(
            config=self.config,
            backend=self.backend,
            message_store=self._message_store,
            lookup_contact_name=self._lookup_contact_name,
        )
        self._voice_note_service = VoiceNoteService(
            config=self.config,
            backend=self.backend,
            message_store=self._message_store,
            lookup_contact_name=self._lookup_contact_name,
            notify_message_summary_change=self._notify_message_summary_change,
        )

        self.registration_callbacks: list[Callable[[RegistrationState], None]] = []
        self.call_state_callbacks: list[Callable[[CallState], None]] = []
        self.incoming_call_callbacks: list[Callable[[str, str], None]] = []
        self.availability_callbacks: list[Callable[[bool, str, RegistrationState], None]] = []
        self.runtime_snapshot_callbacks: list[Callable[[VoIPRuntimeSnapshot], None]] = []
        self._last_lifecycle_availability: tuple[bool, str, RegistrationState] | None = None
        self._event_scheduler = event_scheduler
        self._background_iterate_enabled = bool(background_iterate_enabled and event_scheduler)
        if background_iterate_enabled and event_scheduler is None:
            logger.warning(
                "VoIP background iterate requested without a main-thread scheduler; "
                "falling back to coordinator-thread iterate"
            )
        self._iterate_interval_seconds = max(0.01, float(config.iterate_interval_ms) / 1000.0)
        self._iterate_snapshot = VoIPIterateSnapshot(
            interval_seconds=self._iterate_interval_seconds
        )
        self._iterate_state_lock = threading.Lock()
        self._iterate_thread: threading.Thread | None = None
        self._iterate_stop_event = threading.Event()
        self._iterate_wakeup_event = threading.Event()

        self._stopping = False

        self.backend.on_event(self._dispatch_backend_event)
        logger.info("VoIPManager initialized (server: {})", config.sip_server)

    def _build_message_store(self) -> VoIPMessageStore:
        store_dir = Path(self.config.message_store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
        return VoIPMessageStore(store_dir)

    def start(self) -> bool:
        if self.running:
            return True

        if not self.config.is_backend_start_configured():
            logger.warning("VoIP start skipped: SIP identity/server not configured")
            self._update_registration_state(RegistrationState.FAILED)
            self._notify_availability_change(False, "start_unconfigured")
            self._notify_message_summary_change()
            return False

        self.running = self.backend.start()
        if not self.running:
            self._update_registration_state(RegistrationState.FAILED)
        self._notify_availability_change(
            self.running, "started" if self.running else "start_failed"
        )
        self._notify_message_summary_change()
        return self.running

    def stop(self, notify_events: bool = True) -> None:
        logger.info("Stopping VoIP manager...")
        self._stopping = True
        try:
            self._stop_background_iterate_loop()
            self._stop_call_timer()
            self._stop_voice_note_playback()
            self.backend.stop()
            self._apply_stopped_state()
            if notify_events:
                self._notify_availability_change(False, "stopped")
        finally:
            self._stopping = False
        logger.info("VoIP manager stopped")

    def iterate(self) -> int:
        drained_events = 0
        if self.running:
            drained_events = self.backend.iterate()
        self._check_active_voice_note_timeout()
        return drained_events

    @property
    def background_iterate_enabled(self) -> bool:
        """Return whether this manager owns a dedicated iterate worker."""

        return self._background_iterate_enabled

    def ensure_background_iterate_running(self) -> None:
        """Start the dedicated iterate worker when app-mode background cadence is enabled."""

        if not self._background_iterate_enabled or not self.running:
            return
        if self._iterate_thread is not None and self._iterate_thread.is_alive():
            return

        self._iterate_stop_event.clear()
        self._iterate_wakeup_event.clear()
        self._iterate_thread = threading.Thread(
            target=self._run_background_iterate_loop,
            daemon=True,
            name="voip-iterate",
        )
        self._iterate_thread.start()

    def set_iterate_interval_seconds(self, interval_seconds: float) -> None:
        """Update the active background iterate cadence."""

        clamped_interval_seconds = max(0.01, float(interval_seconds))
        with self._iterate_state_lock:
            if abs(self._iterate_interval_seconds - clamped_interval_seconds) <= 1e-9:
                return
            self._iterate_interval_seconds = clamped_interval_seconds
            self._iterate_snapshot = replace(
                self._iterate_snapshot,
                interval_seconds=clamped_interval_seconds,
            )
        self._iterate_wakeup_event.set()

    def get_iterate_timing_snapshot(self) -> VoIPIterateSnapshot | None:
        """Return the latest iterate timing sample when a worker owns the backend cadence."""

        if not self._background_iterate_enabled:
            return None
        with self._iterate_state_lock:
            return self._iterate_snapshot

    def get_runtime_snapshot(self) -> VoIPRuntimeSnapshot | None:
        """Return the latest Rust-owned VoIP runtime snapshot when available."""

        return self._runtime_snapshot

    def owns_runtime_snapshot(self) -> bool:
        """Return whether the backend is the source of truth for live runtime facts."""

        return self._backend_owns_runtime_snapshot()

    def poll_housekeeping(self) -> None:
        """Run lightweight coordinator-thread-only maintenance alongside background iterate."""

        self._check_active_voice_note_timeout()

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        if not self.registered:
            logger.error("Cannot make call: not registered")
            return False

        resolved_name = contact_name or self._lookup_contact_name(sip_address)
        logger.info("Making call to: {} ({})", resolved_name, sip_address)
        if not self.backend.make_call(sip_address):
            return False

        if not self._backend_owns_runtime_snapshot():
            self.caller_address = sip_address
            self.caller_name = resolved_name
        self._pending_terminal_action = None
        return True

    def answer_call(self) -> bool:
        if not self.backend.answer_call():
            return False

        self._pending_terminal_action = None
        return True

    def hangup(self) -> bool:
        if not self.backend.hangup():
            return False

        self._pending_terminal_action = "hangup"
        return True

    def reject_call(self) -> bool:
        if not self.backend.reject_call():
            return False

        self._pending_terminal_action = "reject"
        return True

    def mute(self) -> bool:
        if self.is_muted:
            return False
        if self.backend.mute():
            if not self._backend_owns_runtime_snapshot():
                self.is_muted = True
            return True
        return False

    def unmute(self) -> bool:
        if not self.is_muted:
            return False
        if self.backend.unmute():
            if not self._backend_owns_runtime_snapshot():
                self.is_muted = False
            return True
        return False

    def toggle_mute(self) -> bool:
        if self.is_muted:
            self.unmute()
            return False
        self.mute()
        return True

    def send_text_message(self, sip_address: str, text: str, display_name: str = "") -> bool:
        return self._messaging_service.send_text_message(sip_address, text, display_name)

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        if self.call_state not in (
            CallState.IDLE,
            CallState.RELEASED,
            CallState.END,
            CallState.ERROR,
        ):
            logger.warning(
                "Cannot start voice-note recording while call state is {}",
                self.call_state.value,
            )
            return False
        return self._voice_note_service.start_voice_note_recording(
            recipient_address, recipient_name
        )

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        return self._voice_note_service.stop_voice_note_recording()

    def cancel_voice_note_recording(self) -> bool:
        return self._voice_note_service.cancel_voice_note_recording()

    def send_active_voice_note(self) -> bool:
        return self._voice_note_service.send_active_voice_note()

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        return self._voice_note_service.get_active_voice_note()

    def discard_active_voice_note(self) -> None:
        self._voice_note_service.discard_active_voice_note()

    def latest_voice_note_for_contact(self, sip_address: str) -> VoIPMessageRecord | None:
        return self._voice_note_service.latest_voice_note_for_contact(sip_address)

    def unread_voice_note_count(self) -> int:
        return self._voice_note_service.unread_voice_note_count()

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        return self._voice_note_service.unread_voice_note_counts_by_contact()

    def latest_voice_note_summary(self) -> dict[str, dict[str, object]]:
        return self._voice_note_service.latest_voice_note_summary()

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        self._voice_note_service.mark_voice_notes_seen(sip_address)

    def play_latest_voice_note(self, sip_address: str) -> bool:
        return self._voice_note_service.play_latest_voice_note(sip_address)

    def play_voice_note(self, file_path: str) -> bool:
        return self._voice_note_service.play_voice_note(file_path)

    def on_registration_change(self, callback: Callable[[RegistrationState], None]) -> None:
        self.registration_callbacks.append(callback)

    def on_call_state_change(self, callback: Callable[[CallState], None]) -> None:
        self.call_state_callbacks.append(callback)

    def on_incoming_call(self, callback: Callable[[str, str], None]) -> None:
        self.incoming_call_callbacks.append(callback)

    def on_availability_change(
        self,
        callback: Callable[[bool, str, RegistrationState], None],
    ) -> None:
        self.availability_callbacks.append(callback)

    def on_runtime_snapshot_change(
        self,
        callback: Callable[[VoIPRuntimeSnapshot], None],
    ) -> None:
        self.runtime_snapshot_callbacks.append(callback)

    def on_message_received(self, callback: Callable[[VoIPMessageRecord], None]) -> None:
        self._messaging_service.on_message_received(callback)

    def on_message_delivery_change(self, callback: Callable[[VoIPMessageRecord], None]) -> None:
        self._messaging_service.on_message_delivery_change(callback)

    def on_message_failure(self, callback: Callable[[str, str], None]) -> None:
        self._messaging_service.on_message_failure(callback)

    def on_message_summary_change(
        self,
        callback: Callable[[int, dict[str, dict[str, object]]], None],
    ) -> None:
        self._messaging_service.on_message_summary_change(callback)

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "registered": self.registered,
            "registration_state": self.registration_state.value,
            "call_state": self.call_state.value,
            "call_id": self.current_call_id,
            "sip_identity": self.config.sip_identity,
            "unread_voice_notes": self.unread_voice_note_count(),
        }

    def get_iterate_metrics(self) -> object | None:
        """Return the latest backend-native keep-alive timing sample when available."""

        get_metrics = getattr(self.backend, "get_iterate_metrics", None)
        if not callable(get_metrics):
            return None
        return cast(object, get_metrics())

    def get_call_duration(self) -> int:
        if self.call_start_time and self.call_state in (
            CallState.CONNECTED,
            CallState.STREAMS_RUNNING,
        ):
            return int(time.time() - self.call_start_time)
        return 0

    def consume_pending_terminal_action(self) -> str | None:
        """Return and clear the most recent local call teardown action."""

        action = self._pending_terminal_action
        self._pending_terminal_action = None
        return action

    def get_caller_info(self) -> dict:
        if self.caller_address and not self.caller_name:
            self.caller_name = self._lookup_contact_name(self.caller_address)

        return {
            "address": self.caller_address,
            "name": self.caller_name or self.caller_address,
            "display_name": self.caller_name or self._lookup_contact_name(self.caller_address),
        }

    def cleanup(self) -> None:
        self._stop_call_timer()
        self.stop()

    def _dispatch_backend_event(self, event: VoIPEvent) -> None:
        """Handle backend events immediately or queue them back to the coordinator thread."""

        if self._event_scheduler is None:
            self._handle_backend_event(event)
            return

        def _handle_scheduled_event(event_to_handle: VoIPEvent = event) -> None:
            self._handle_backend_event(event_to_handle)

        self._event_scheduler(_handle_scheduled_event)

    def _stop_background_iterate_loop(self) -> None:
        """Stop the dedicated iterate worker if one is active."""

        self._iterate_stop_event.set()
        self._iterate_wakeup_event.set()
        if self._iterate_thread is not None:
            self._iterate_thread.join(timeout=1.0)
            self._iterate_thread = None
        with self._iterate_state_lock:
            self._iterate_snapshot = replace(self._iterate_snapshot, in_flight=False)

    def _run_background_iterate_loop(self) -> None:
        """Advance the backend on a dedicated worker instead of the coordinator thread."""

        try:
            next_due_at = time.monotonic()
            while not self._iterate_stop_event.is_set():
                wait_seconds = max(0.0, next_due_at - time.monotonic())
                woke_early = self._iterate_wakeup_event.wait(wait_seconds)
                if self._iterate_stop_event.is_set():
                    break
                if woke_early:
                    self._iterate_wakeup_event.clear()
                    next_due_at = time.monotonic() + self._current_iterate_interval_seconds()
                    continue

                started_at = time.monotonic()
                schedule_delay_seconds = max(0.0, started_at - next_due_at)
                with self._iterate_state_lock:
                    self._iterate_snapshot = replace(
                        self._iterate_snapshot,
                        last_started_at=started_at,
                        schedule_delay_seconds=schedule_delay_seconds,
                        in_flight=True,
                    )

                drained_events = self.backend.iterate() if self.running else 0
                metrics = self.get_iterate_metrics()
                completed_at = time.monotonic()

                with self._iterate_state_lock:
                    self._iterate_snapshot = VoIPIterateSnapshot(
                        sample_id=self._iterate_snapshot.sample_id + 1,
                        last_started_at=started_at,
                        last_completed_at=completed_at,
                        schedule_delay_seconds=schedule_delay_seconds,
                        total_duration_seconds=max(0.0, completed_at - started_at),
                        native_duration_seconds=max(
                            0.0,
                            float(getattr(metrics, "native_duration_seconds", 0.0) or 0.0),
                        ),
                        event_drain_duration_seconds=max(
                            0.0,
                            float(getattr(metrics, "event_drain_duration_seconds", 0.0) or 0.0),
                        ),
                        drained_events=max(0, int(drained_events)),
                        interval_seconds=self._iterate_interval_seconds,
                        in_flight=False,
                    )

                next_due_at = started_at + self._current_iterate_interval_seconds()
        except Exception as exc:
            if not self._iterate_stop_event.is_set():
                reason = str(exc).strip() or exc.__class__.__name__
                logger.exception("VoIP background iterate loop crashed: {}", reason)
                self._dispatch_backend_event(BackendStopped(reason=reason))
        finally:
            with self._iterate_state_lock:
                self._iterate_snapshot = replace(self._iterate_snapshot, in_flight=False)

    def _current_iterate_interval_seconds(self) -> float:
        """Return the currently selected iterate interval for the background worker."""

        with self._iterate_state_lock:
            return self._iterate_interval_seconds

    def _handle_backend_event(self, event: VoIPEvent) -> None:
        if self._stopping:
            logger.debug("Ignoring VoIP backend event during shutdown: {!r}", event)
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
            logger.warning("VoIP backend stopped unexpectedly: {}", event.reason or "unknown")
            if self.call_state not in (CallState.IDLE, CallState.RELEASED):
                self._update_call_state(CallState.RELEASED)
            self._update_registration_state(RegistrationState.FAILED)
            self.running = False
            self._notify_availability_change(False, event.reason or "backend_stopped")
            return
        if isinstance(event, BackendRecovered):
            logger.info("VoIP backend recovered: {}", event.reason or "backend_recovered")
            self.running = True
            self._update_registration_state(RegistrationState.PROGRESS)
            self._notify_availability_change(True, event.reason or "backend_recovered")
            return
        if isinstance(event, VoIPRuntimeSnapshotChanged):
            self._apply_runtime_snapshot(event.snapshot)
            return
        if isinstance(event, MessageReceived):
            self._messaging_service.handle_message_received(event.message)
            return
        if isinstance(event, MessageDeliveryChanged):
            self._voice_note_service.handle_message_delivery_changed(event)
            self._messaging_service.handle_message_delivery_changed(event)
            return
        if isinstance(event, MessageDownloadCompleted):
            self._messaging_service.handle_message_download_completed(event)
            return
        if isinstance(event, MessageFailed):
            self._voice_note_service.handle_message_failed(event)
            self._messaging_service.handle_message_failed(event)

    def _apply_runtime_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        self._runtime_snapshot = snapshot
        lifecycle_state = snapshot.lifecycle.state.strip().lower()
        self.running = snapshot.lifecycle.backend_available or lifecycle_state not in {
            "failed",
            "stopped",
            "unconfigured",
        }
        self._update_registration_state(snapshot.registration_state)
        self._sync_call_identity(snapshot)
        self.is_muted = snapshot.muted
        self._update_call_state(snapshot.call_state)
        self._notify_lifecycle_availability_from_snapshot(snapshot)
        self._voice_note_service.apply_runtime_snapshot(snapshot)
        self._messaging_service.apply_runtime_snapshot(snapshot)
        self._notify_runtime_snapshot_change(snapshot)

    def _sync_call_identity(self, snapshot: VoIPRuntimeSnapshot) -> None:
        has_active_call = bool(snapshot.active_call_id or snapshot.active_call_peer)
        if has_active_call:
            self.current_call_id = snapshot.active_call_id or None
            if snapshot.active_call_peer:
                self.caller_address = snapshot.active_call_peer
                self.caller_name = self._lookup_contact_name(snapshot.active_call_peer)
            return
        if snapshot.call_state in (
            CallState.IDLE,
            CallState.RELEASED,
            CallState.END,
            CallState.ERROR,
        ):
            self.current_call_id = None
            self.caller_address = None
            self.caller_name = None

    def _backend_owns_runtime_snapshot(self) -> bool:
        return callable(getattr(self.backend, "get_runtime_snapshot", None))

    def _notify_message_summary_change(self) -> None:
        self._messaging_service.notify_message_summary_change()

    def _handle_incoming_call_event(self, caller_address: str) -> None:
        self.caller_address = caller_address
        self.caller_name = self._lookup_contact_name(caller_address)
        for callback in self.incoming_call_callbacks:
            try:
                callback(caller_address, self.caller_name or self._extract_username(caller_address))
            except Exception as exc:
                logger.error("Error in incoming call callback: {}", exc)

    def _update_registration_state(self, state: RegistrationState) -> None:
        if state == self.registration_state:
            return

        old_state = self.registration_state
        self.registration_state = state
        self.registered = state == RegistrationState.OK

        logger.info("Registration state: {} -> {}", old_state.value, state.value)
        for callback in self.registration_callbacks:
            try:
                callback(state)
            except Exception as exc:
                logger.error("Error in registration callback: {}", exc)

    def _update_call_state(self, state: CallState) -> None:
        if state == self.call_state:
            return

        old_state = self.call_state
        self.call_state = state
        logger.info("Call state: {} -> {}", old_state.value, state.value)

        if state in (
            CallState.INCOMING,
            CallState.OUTGOING,
            CallState.OUTGOING_PROGRESS,
            CallState.OUTGOING_RINGING,
            CallState.OUTGOING_EARLY_MEDIA,
            CallState.CONNECTED,
            CallState.STREAMS_RUNNING,
            CallState.PAUSED,
            CallState.PAUSED_BY_REMOTE,
            CallState.UPDATED_BY_REMOTE,
        ):
            self._stop_voice_note_playback()

        if (
            state in (CallState.CONNECTED, CallState.STREAMS_RUNNING)
            and self.call_start_time is None
        ):
            self._start_call_timer()
        elif state in (CallState.RELEASED, CallState.END, CallState.ERROR):
            self._clear_call_session()

        for callback in self.call_state_callbacks:
            try:
                callback(state)
            except Exception as exc:
                logger.error("Error in call state callback: {}", exc)

    def _extract_username(self, sip_address: str | None) -> str:
        if not sip_address:
            return "Unknown"
        if "@" in sip_address:
            username_part = sip_address.split("@", 1)[0]
            if ":" in username_part:
                return username_part.split(":")[-1]
            return username_part
        return sip_address

    def _lookup_contact_name(self, sip_address: str | None) -> str:
        if not sip_address:
            return "Unknown"

        if self.people_directory is not None:
            contact = self.people_directory.get_contact_by_address(sip_address)
            if contact:
                return str(contact.display_name)
        return self._extract_username(sip_address)

    def _start_call_timer(self) -> None:
        self.call_start_time = time.time()

    def _stop_call_timer(self) -> None:
        self.call_start_time = None

    def _clear_call_session(self) -> None:
        self._stop_call_timer()
        self.current_call_id = None
        self.caller_address = None
        self.caller_name = None
        self.is_muted = False

    def _apply_stopped_state(self) -> None:
        if self.call_state not in (CallState.IDLE, CallState.RELEASED):
            self.call_state = CallState.RELEASED
        self._clear_call_session()
        self._pending_terminal_action = None
        self.running = False
        self.registered = False
        self.registration_state = RegistrationState.NONE

    def _notify_availability_change(self, available: bool, reason: str) -> None:
        self._last_lifecycle_availability = (available, reason, self.registration_state)
        for callback in self.availability_callbacks:
            try:
                callback(available, reason, self.registration_state)
            except Exception as exc:
                logger.error("Error in availability callback: {}", exc)

    def _notify_lifecycle_availability_from_snapshot(
        self,
        snapshot: VoIPRuntimeSnapshot,
    ) -> None:
        lifecycle_state = snapshot.lifecycle.state.strip().lower()
        if not lifecycle_state:
            return
        reason = snapshot.lifecycle.reason or lifecycle_state
        available = bool(snapshot.lifecycle.backend_available)
        key = (available, reason, self.registration_state)
        if self._last_lifecycle_availability == key:
            return
        self._notify_availability_change(available, reason)

    def _notify_runtime_snapshot_change(self, snapshot: VoIPRuntimeSnapshot) -> None:
        for callback in self.runtime_snapshot_callbacks:
            try:
                callback(snapshot)
            except Exception as exc:
                logger.error("Error in runtime snapshot callback: {}", exc)

    def _stop_voice_note_playback(self) -> None:
        self._voice_note_service.stop_voice_note_playback()

    @staticmethod
    def _build_voice_note_playback_command(file_path: str) -> list[str]:
        return VoiceNoteService.build_voice_note_playback_command(file_path)

    def _check_active_voice_note_timeout(self) -> None:
        self._voice_note_service.check_active_voice_note_timeout()


__all__ = ["VoIPIterateSnapshot", "VoIPManager"]
