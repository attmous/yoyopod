"""App-facing VoIP facade built on top of Liblinphone backend events."""

from __future__ import annotations

import subprocess
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, cast

from loguru import logger

from yoyopod.communication.calling.backend import LiblinphoneBackend, VoIPBackend
from yoyopod.communication.messaging import VoIPMessageStore
from yoyopod.communication.models import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDownloadCompleted,
    MessageFailed,
    MessageKind,
    MessageDirection,
    MessageReceived,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
    VoIPMessageRecord,
)

if TYPE_CHECKING:
    from yoyopod.people import PeopleDirectory


@dataclass(slots=True)
class VoiceNoteDraft:
    """Locally recorded voice-note draft awaiting send or retry."""

    recipient_address: str
    recipient_name: str
    file_path: str
    duration_ms: int = 0
    mime_type: str = "audio/wav"
    message_id: str = ""
    send_state: str = "idle"
    status_text: str = ""
    send_started_at: float = 0.0


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


VOICE_NOTE_SEND_TIMEOUT_SECONDS = 15.0
VOICE_NOTE_CONTAINER_GAIN_DB = 12.0


class VoIPManager:
    """Application-facing VoIP facade over Liblinphone calls and messages."""

    def __init__(
        self,
        config: VoIPConfig,
        people_directory: "PeopleDirectory | None" = None,
        backend: Optional[VoIPBackend] = None,
        message_store: Optional[VoIPMessageStore] = None,
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
        self.current_call_id: Optional[str] = None
        self.caller_address: Optional[str] = None
        self.caller_name: Optional[str] = None
        self.call_start_time: Optional[float] = None
        self.is_muted = False
        self._pending_terminal_action: str | None = None
        self._message_store = message_store or self._build_message_store()
        self._active_voice_note: VoiceNoteDraft | None = None
        self._playback_process: subprocess.Popen | None = None

        self.registration_callbacks: list[Callable[[RegistrationState], None]] = []
        self.call_state_callbacks: list[Callable[[CallState], None]] = []
        self.incoming_call_callbacks: list[Callable[[str, str], None]] = []
        self.availability_callbacks: list[Callable[[bool, str], None]] = []
        self.message_received_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_delivery_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_failure_callbacks: list[Callable[[str, str], None]] = []
        self.message_summary_callbacks: list[
            Callable[[int, dict[str, dict[str, object]]], None]
        ] = []
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

    def poll_housekeeping(self) -> None:
        """Run lightweight coordinator-thread-only maintenance alongside background iterate."""

        self._check_active_voice_note_timeout()

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        if not self.registered:
            logger.error("Cannot make call: not registered")
            return False

        self.caller_address = sip_address
        self.caller_name = contact_name or self._lookup_contact_name(sip_address)
        logger.info("Making call to: {} ({})", self.caller_name, sip_address)
        if not self.backend.make_call(sip_address):
            return False

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
            self.is_muted = True
            return True
        return False

    def unmute(self) -> bool:
        if not self.is_muted:
            return False
        if self.backend.unmute():
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
        message_id = self.backend.send_text_message(sip_address, text)
        if not message_id:
            return False
        self._message_store.upsert(
            VoIPMessageRecord(
                id=message_id,
                peer_sip_address=sip_address,
                sender_sip_address=self.config.sip_identity,
                recipient_sip_address=sip_address,
                kind=MessageKind.TEXT,
                direction=MessageDirection.OUTGOING,
                delivery_state=MessageDeliveryState.SENDING,
                created_at=self._iso_now(),
                updated_at=self._iso_now(),
                text=text,
                display_name=display_name or self._lookup_contact_name(sip_address),
            )
        )
        self._notify_message_summary_change()
        return True

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        if not recipient_address:
            logger.error("Cannot start voice-note recording without a recipient address")
            return False

        self.discard_active_voice_note()
        voice_note_dir = Path(self.config.voice_note_store_dir)
        voice_note_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_name = f"voice-note-{timestamp}.wav"
        file_path = str(voice_note_dir / file_name)

        if not self.backend.start_voice_note_recording(file_path):
            return False

        self._active_voice_note = VoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name or self._lookup_contact_name(recipient_address),
            file_path=file_path,
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        if self._active_voice_note is None:
            return None

        duration_ms = self.backend.stop_voice_note_recording()
        if duration_ms is None:
            return None

        self._active_voice_note.duration_ms = duration_ms
        max_duration_ms = max(1, self.config.voice_note_max_duration_seconds) * 1000
        if duration_ms > max_duration_ms:
            self._active_voice_note.send_state = "failed"
            self._active_voice_note.status_text = "Note too long"
            return self._active_voice_note
        self._active_voice_note.send_state = "review"
        self._active_voice_note.status_text = "Ready to send"
        return self._active_voice_note

    def cancel_voice_note_recording(self) -> bool:
        success = self.backend.cancel_voice_note_recording()
        self.discard_active_voice_note()
        return success

    def send_active_voice_note(self) -> bool:
        if self._active_voice_note is None:
            return False

        draft = self._active_voice_note
        if not self.config.effective_file_transfer_server_url():
            draft.send_state = "failed"
            draft.status_text = "Voice notes unavailable"
            return False
        draft.send_state = "sending"
        draft.status_text = "Sending..."
        draft.send_started_at = time.monotonic()
        message_id = self.backend.send_voice_note(
            draft.recipient_address,
            file_path=draft.file_path,
            duration_ms=draft.duration_ms,
            mime_type=draft.mime_type,
        )
        if not message_id:
            draft.send_state = "failed"
            draft.status_text = "Couldn't send"
            draft.send_started_at = 0.0
            return False

        draft.message_id = message_id
        self._message_store.upsert(
            VoIPMessageRecord(
                id=message_id,
                peer_sip_address=draft.recipient_address,
                sender_sip_address=self.config.sip_identity,
                recipient_sip_address=draft.recipient_address,
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.OUTGOING,
                delivery_state=MessageDeliveryState.SENDING,
                created_at=self._iso_now(),
                updated_at=self._iso_now(),
                local_file_path=draft.file_path,
                mime_type=draft.mime_type,
                duration_ms=draft.duration_ms,
                unread=False,
                display_name=draft.recipient_name,
            )
        )
        self._notify_message_summary_change()
        return True

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        return self._active_voice_note

    def discard_active_voice_note(self) -> None:
        """Drop the active draft and delete its local file if it exists."""

        draft = self._active_voice_note
        self._active_voice_note = None
        if draft is None or not draft.file_path:
            return
        try:
            Path(draft.file_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Failed to remove discarded voice note {}: {}", draft.file_path, exc)

    def latest_voice_note_for_contact(self, sip_address: str) -> VoIPMessageRecord | None:
        if not sip_address:
            return None
        return self._message_store.latest_voice_note_for_contact(sip_address)

    def unread_voice_note_count(self) -> int:
        return self._message_store.unread_voice_note_count()

    def latest_voice_note_summary(self) -> dict[str, dict[str, object]]:
        return self._message_store.latest_voice_note_by_contact()

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        self._message_store.mark_contact_seen(sip_address)
        self._notify_message_summary_change()

    def play_latest_voice_note(self, sip_address: str) -> bool:
        record = self.latest_voice_note_for_contact(sip_address)
        if record is None or not record.local_file_path:
            return False
        return self.play_voice_note(record.local_file_path)

    def play_voice_note(self, file_path: str) -> bool:
        self._stop_voice_note_playback()
        try:
            command = self._build_voice_note_playback_command(file_path)
            self._playback_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.error("Failed to play voice note {}: {}", file_path, exc)
            return False

    def on_registration_change(self, callback: Callable[[RegistrationState], None]) -> None:
        self.registration_callbacks.append(callback)

    def on_call_state_change(self, callback: Callable[[CallState], None]) -> None:
        self.call_state_callbacks.append(callback)

    def on_incoming_call(self, callback: Callable[[str, str], None]) -> None:
        self.incoming_call_callbacks.append(callback)

    def on_availability_change(self, callback: Callable[[bool, str], None]) -> None:
        self.availability_callbacks.append(callback)

    def on_message_received(self, callback: Callable[[VoIPMessageRecord], None]) -> None:
        self.message_received_callbacks.append(callback)

    def on_message_delivery_change(self, callback: Callable[[VoIPMessageRecord], None]) -> None:
        self.message_delivery_callbacks.append(callback)

    def on_message_failure(self, callback: Callable[[str, str], None]) -> None:
        self.message_failure_callbacks.append(callback)

    def on_message_summary_change(
        self,
        callback: Callable[[int, dict[str, dict[str, object]]], None],
    ) -> None:
        self.message_summary_callbacks.append(callback)

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
        if isinstance(event, MessageReceived):
            self._handle_message_received(event.message)
            return
        if isinstance(event, MessageDeliveryChanged):
            self._handle_message_delivery_changed(event)
            return
        if isinstance(event, MessageDownloadCompleted):
            self._handle_message_download_completed(event)
            return
        if isinstance(event, MessageFailed):
            self._handle_message_failed(event)

    def _handle_message_received(self, message: VoIPMessageRecord) -> None:
        record = self._decorate_message(self._normalize_message_record(message))
        logger.info(
            "VoIPManager received message: id={} kind={} direction={} peer={} file={}",
            record.id,
            record.kind.value,
            record.direction.value,
            record.peer_sip_address,
            record.local_file_path,
        )
        self._message_store.upsert(record)
        for callback in self.message_received_callbacks:
            try:
                callback(record)
            except Exception as exc:
                logger.error("Error in message received callback: {}", exc)
        self._notify_message_summary_change()

    def _handle_message_delivery_changed(self, event: MessageDeliveryChanged) -> None:
        self._message_store.update_delivery(
            event.message_id,
            event.delivery_state,
            local_file_path=event.local_file_path,
        )
        record = self._message_store.get(event.message_id)
        if record is None:
            return

        if (
            self._active_voice_note is not None
            and self._active_voice_note.message_id == event.message_id
        ):
            if event.delivery_state in (MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED):
                self._active_voice_note.send_state = "sent"
                self._active_voice_note.status_text = (
                    "Delivered"
                    if event.delivery_state == MessageDeliveryState.DELIVERED
                    else "Sent"
                )
                self._active_voice_note.send_started_at = 0.0
            elif event.delivery_state == MessageDeliveryState.FAILED:
                self._active_voice_note.send_state = "failed"
                self._active_voice_note.status_text = event.error or "Couldn't send"
                self._active_voice_note.send_started_at = 0.0

        for callback in self.message_delivery_callbacks:
            try:
                callback(record)
            except Exception as exc:
                logger.error("Error in message delivery callback: {}", exc)
        self._notify_message_summary_change()

    def _handle_message_download_completed(self, event: MessageDownloadCompleted) -> None:
        record = self._message_store.get(event.message_id)
        if record is None:
            logger.warning(
                "Voice-note download completed for unknown message id={} file={}",
                event.message_id,
                event.local_file_path,
            )
            return
        logger.info(
            "VoIPManager download completed: id={} file={} mime={}",
            event.message_id,
            event.local_file_path,
            event.mime_type,
        )
        updated = replace(
            record,
            local_file_path=event.local_file_path,
            mime_type=event.mime_type or record.mime_type,
            updated_at=self._iso_now(),
        )
        self._message_store.upsert(updated)
        for callback in self.message_delivery_callbacks:
            try:
                callback(updated)
            except Exception as exc:
                logger.error("Error in message download callback: {}", exc)
        self._notify_message_summary_change()

    def _handle_message_failed(self, event: MessageFailed) -> None:
        self._message_store.update_delivery(event.message_id, MessageDeliveryState.FAILED)
        if (
            self._active_voice_note is not None
            and self._active_voice_note.message_id == event.message_id
        ):
            self._active_voice_note.send_state = "failed"
            self._active_voice_note.status_text = event.reason or "Couldn't send"
            self._active_voice_note.send_started_at = 0.0
        for callback in self.message_failure_callbacks:
            try:
                callback(event.message_id, event.reason)
            except Exception as exc:
                logger.error("Error in message failure callback: {}", exc)
        self._notify_message_summary_change()

    def _normalize_message_record(self, message: VoIPMessageRecord) -> VoIPMessageRecord:
        if message.kind == MessageKind.VOICE_NOTE:
            if message.mime_type == "application/vnd.gsma.rcs-ft-http+xml" and message.text:
                return replace(
                    message,
                    mime_type=self._extract_voice_note_payload_mime(message.text) or "audio/wav",
                    duration_ms=message.duration_ms
                    or self._extract_voice_note_duration_ms(message.text),
                    text="",
                )
            return message

        if (
            message.kind == MessageKind.TEXT
            and message.mime_type == "application/vnd.gsma.rcs-ft-http+xml"
            and "voice-recording=yes" in message.text
        ):
            return replace(
                message,
                kind=MessageKind.VOICE_NOTE,
                mime_type=self._extract_voice_note_payload_mime(message.text) or "audio/wav",
                duration_ms=message.duration_ms
                or self._extract_voice_note_duration_ms(message.text),
                text="",
            )
        return message

    def _decorate_message(self, message: VoIPMessageRecord) -> VoIPMessageRecord:
        display_name = message.display_name or self._lookup_contact_name(message.peer_sip_address)
        return replace(message, display_name=display_name)

    @staticmethod
    def _extract_voice_note_payload_mime(xml_text: str) -> str:
        match = re.search(r"<content-type>([^<]+)</content-type>", xml_text)
        if not match:
            return ""
        return match.group(1).split(";", 1)[0].strip()

    @staticmethod
    def _extract_voice_note_duration_ms(xml_text: str) -> int:
        match = re.search(r"<am:playing-length>(\d+)</am:playing-length>", xml_text)
        if not match:
            return 0
        return max(0, int(match.group(1)))

    def _notify_message_summary_change(self) -> None:
        unread = self.unread_voice_note_count()
        summary = self.latest_voice_note_summary()
        for callback in self.message_summary_callbacks:
            try:
                callback(unread, summary)
            except Exception as exc:
                logger.error("Error in message summary callback: {}", exc)

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

    def _extract_username(self, sip_address: Optional[str]) -> str:
        if not sip_address:
            return "Unknown"
        if "@" in sip_address:
            username_part = sip_address.split("@", 1)[0]
            if ":" in username_part:
                return username_part.split(":")[-1]
            return username_part
        return sip_address

    def _lookup_contact_name(self, sip_address: Optional[str]) -> str:
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
        for callback in self.availability_callbacks:
            try:
                callback(available, reason)
            except Exception as exc:
                logger.error("Error in availability callback: {}", exc)

    def _stop_voice_note_playback(self) -> None:
        if self._playback_process is None:
            return
        try:
            self._playback_process.terminate()
            self._playback_process.wait(timeout=1)
        except Exception:
            try:
                self._playback_process.kill()
            except Exception:
                pass
        finally:
            self._playback_process = None

    @staticmethod
    def _build_voice_note_playback_command(file_path: str) -> list[str]:
        suffix = Path(file_path).suffix.lower()
        if suffix in {".mka", ".mkv", ".ogg", ".opus", ".mp3", ".m4a"}:
            return [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-af",
                f"volume={VOICE_NOTE_CONTAINER_GAIN_DB}dB",
                file_path,
            ]
        return ["aplay", "-q", file_path]

    def _check_active_voice_note_timeout(self) -> None:
        draft = self._active_voice_note
        if draft is None or draft.send_state != "sending" or draft.send_started_at <= 0.0:
            return
        if (time.monotonic() - draft.send_started_at) < VOICE_NOTE_SEND_TIMEOUT_SECONDS:
            return

        draft.send_state = "failed"
        draft.status_text = "Send timed out"
        draft.send_started_at = 0.0
        if draft.message_id:
            self._message_store.update_delivery(draft.message_id, MessageDeliveryState.FAILED)
        self._notify_message_summary_change()

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()
