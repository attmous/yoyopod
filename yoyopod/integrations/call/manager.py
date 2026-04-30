"""App-facing VoIP facade backed by the Rust VoIP runtime worker."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPBackend
from yoyopod.integrations.call.models import (
    BackendRecovered,
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
    VoIPRuntimeSnapshotChanged,
)
from yoyopod.integrations.call.history import CallHistoryEntry
from yoyopod.integrations.call.voice_note_draft import VoiceNoteDraft

if TYPE_CHECKING:
    from yoyopod.integrations.contacts.directory import PeopleManager

VOICE_NOTE_CONTAINER_GAIN_DB = 12.0


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
    """Application-facing VoIP facade over the Rust-owned VoIP runtime."""

    def __init__(
        self,
        config: VoIPConfig,
        people_directory: "PeopleManager | None" = None,
        backend: VoIPBackend | None = None,
        event_scheduler: Callable[[Callable[[], None]], None] | None = None,
        background_iterate_enabled: bool = False,
    ) -> None:
        self.config = config
        self.people_directory = people_directory
        if backend is None:
            raise ValueError("VoIPManager requires an explicit VoIP backend")
        if not callable(getattr(backend, "get_runtime_snapshot", None)):
            raise ValueError("VoIPManager requires a Rust runtime snapshot backend")
        self.backend = backend
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
        self._last_rust_message_summary_key: (
            tuple[
                int,
                tuple[tuple[str, int], ...],
                tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
            ]
            | None
        ) = None
        self._pending_terminal_action: str | None = None
        self._rust_active_voice_note: VoiceNoteDraft | None = None

        self.registration_callbacks: list[Callable[[RegistrationState], None]] = []
        self.call_state_callbacks: list[Callable[[CallState], None]] = []
        self.incoming_call_callbacks: list[Callable[[str, str], None]] = []
        self.availability_callbacks: list[Callable[[bool, str, RegistrationState], None]] = []
        self.runtime_snapshot_callbacks: list[Callable[[VoIPRuntimeSnapshot], None]] = []
        self.message_received_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_delivery_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_failure_callbacks: list[Callable[[str, str], None]] = []
        self.message_summary_callbacks: list[
            Callable[[int, dict[str, dict[str, object]]], None]
        ] = []
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

    def start(self) -> bool:
        if self.running:
            return True

        if not self.config.is_backend_start_configured():
            logger.warning("VoIP start skipped: SIP identity/server not configured")
            self._update_registration_state(RegistrationState.FAILED)
            self._notify_availability_change(False, "start_unconfigured")
            self._notify_message_summary_change(0, {})
            return False

        self.running = self.backend.start()
        if not self.running:
            self._update_registration_state(RegistrationState.FAILED)
        self._notify_availability_change(
            self.running, "started" if self.running else "start_failed"
        )
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

        return True

    def poll_housekeeping(self) -> None:
        """Run lightweight coordinator-thread-only maintenance alongside background iterate."""

        return

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        if not self.registered:
            logger.error("Cannot make call: not registered")
            return False

        resolved_name = contact_name or self._lookup_contact_name(sip_address)
        logger.info("Making call to: {} ({})", resolved_name, sip_address)
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
        return bool(self.backend.mute())

    def unmute(self) -> bool:
        if not self.is_muted:
            return False
        return bool(self.backend.unmute())

    def toggle_mute(self) -> bool:
        if self.is_muted:
            self.unmute()
            return False
        self.mute()
        return True

    def send_text_message(self, sip_address: str, text: str, display_name: str = "") -> bool:
        message_id = self.backend.send_text_message(sip_address, text)
        return bool(message_id)

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
        return self._start_rust_voice_note_recording(recipient_address, recipient_name)

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        return self._stop_rust_voice_note_recording()

    def cancel_voice_note_recording(self) -> bool:
        success = self.backend.cancel_voice_note_recording()
        self._rust_active_voice_note = None
        return success

    def send_active_voice_note(self) -> bool:
        return self._send_rust_active_voice_note()

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        if self._rust_active_voice_note is None:
            self._refresh_rust_voice_note_snapshot()
        return self._rust_active_voice_note

    def discard_active_voice_note(self) -> None:
        self._rust_active_voice_note = None

    def latest_voice_note_for_contact(self, sip_address: str) -> VoIPMessageRecord | None:
        return self._runtime_voice_note_record_for_contact(sip_address)

    def unread_voice_note_count(self) -> int:
        if self._runtime_snapshot is not None:
            return max(0, int(self._runtime_snapshot.unread_voice_notes))
        return 0

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        if self._runtime_snapshot is not None:
            return dict(self._runtime_snapshot.unread_voice_notes_by_contact)
        return {}

    def latest_voice_note_summary(self) -> dict[str, dict[str, object]]:
        if self._runtime_snapshot is not None:
            return {
                str(address): dict(summary)
                for address, summary in self._runtime_snapshot.latest_voice_note_by_contact.items()
            }
        return {}

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        mark_seen = getattr(self.backend, "mark_voice_notes_seen", None)
        if callable(mark_seen):
            mark_seen(sip_address)

    def call_history_unread_count(self) -> int:
        if self._runtime_snapshot is not None:
            return max(0, int(self._runtime_snapshot.unseen_call_history))
        return 0

    def call_history_recent_preview(self) -> tuple[str, ...]:
        if self._runtime_snapshot is None:
            return ()
        preview: list[str] = []
        for entry in self.call_history_recent_entries():
            preview.append(entry.title)
        return tuple(preview)

    def call_history_recent_entries(self) -> tuple[CallHistoryEntry, ...]:
        """Return Rust-owned recent call history as app-facing list rows."""

        if self._runtime_snapshot is None:
            return ()

        entries: list[CallHistoryEntry] = []
        for raw_entry in self._runtime_snapshot.recent_call_history:
            if not isinstance(raw_entry, dict):
                continue
            entry = _call_history_entry_from_snapshot(self, raw_entry)
            if entry is not None:
                entries.append(entry)
        return tuple(entries)

    def mark_call_history_seen(self, sip_address: str = "") -> bool:
        mark_seen = getattr(self.backend, "mark_call_history_seen", None)
        if not callable(mark_seen):
            return False
        return bool(mark_seen(sip_address))

    def play_latest_voice_note(self, sip_address: str) -> bool:
        record = self._runtime_voice_note_record_for_contact(sip_address)
        if record is None or not record.local_file_path:
            return False
        return self.play_voice_note(record.local_file_path)

    def play_voice_note(self, file_path: str) -> bool:
        play = getattr(self.backend, "play_voice_note", None)
        if callable(play):
            return bool(play(file_path))
        return False

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
        if isinstance(event, BackendRecovered):
            logger.info("VoIP backend recovered: {}", event.reason or "backend_recovered")
            self.running = True
            self._update_registration_state(RegistrationState.PROGRESS)
            self._notify_availability_change(True, event.reason or "backend_recovered")
            return
        if isinstance(event, VoIPRuntimeSnapshotChanged):
            self._apply_runtime_snapshot(event.snapshot)
            return
        if isinstance(event, MessageFailed):
            self._handle_rust_voice_note_failed(event)
            return

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
        self._apply_rust_voice_note_snapshot(snapshot)
        self._notify_rust_message_summary_change(snapshot)
        self._notify_runtime_snapshot_change(snapshot)

    def _start_rust_voice_note_recording(
        self,
        recipient_address: str,
        recipient_name: str,
    ) -> bool:
        if not recipient_address:
            logger.error("Cannot start voice-note recording without a recipient address")
            return False

        file_path = _build_recording_file_path(self.config)
        if not self.backend.start_voice_note_recording(file_path):
            return False

        self._rust_active_voice_note = VoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name or self._lookup_contact_name(recipient_address),
            file_path=file_path,
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def _stop_rust_voice_note_recording(self) -> VoiceNoteDraft | None:
        draft = self.get_active_voice_note()
        if draft is None:
            return None

        duration_ms = self.backend.stop_voice_note_recording()
        if duration_ms is None:
            return None

        draft.duration_ms = max(0, int(duration_ms))
        draft.send_state = "review"
        draft.status_text = "Ready to send"
        return draft

    def _send_rust_active_voice_note(self) -> bool:
        draft = self.get_active_voice_note()
        if draft is None:
            return False
        if not draft.recipient_address:
            logger.error("Cannot send Rust-owned voice note without a recipient address")
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
        return True

    def _refresh_rust_voice_note_snapshot(self) -> None:
        get_snapshot = getattr(self.backend, "get_runtime_snapshot", None)
        if not callable(get_snapshot):
            return
        snapshot = cast(VoIPRuntimeSnapshot | None, get_snapshot())
        if snapshot is None:
            return
        self._runtime_snapshot = snapshot
        self._apply_rust_voice_note_snapshot(snapshot)

    def _apply_rust_voice_note_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        voice_note = snapshot.voice_note
        state = voice_note.state.strip().lower() or "idle"
        if state == "idle":
            return

        draft = self._rust_active_voice_note
        if draft is None:
            draft = VoiceNoteDraft(
                recipient_address="",
                recipient_name="",
                file_path=voice_note.file_path,
                mime_type=voice_note.mime_type or "audio/wav",
            )
            self._rust_active_voice_note = draft

        if voice_note.file_path:
            draft.file_path = voice_note.file_path
        if voice_note.duration_ms > 0:
            draft.duration_ms = voice_note.duration_ms
        if voice_note.mime_type:
            draft.mime_type = voice_note.mime_type
        if voice_note.message_id:
            draft.message_id = voice_note.message_id

        if state == "recording":
            draft.send_state = "recording"
            draft.status_text = "Recording..."
            return
        if state == "recorded":
            draft.send_state = "review"
            draft.status_text = "Ready to send"
            return
        if state == "sending":
            draft.send_state = "sending"
            draft.status_text = "Sending..."
            if draft.send_started_at <= 0.0:
                draft.send_started_at = time.monotonic()
            return
        if state == "sent":
            draft.send_state = "sent"
            draft.status_text = "Sent"
            draft.send_started_at = 0.0
            return
        if state == "failed":
            draft.send_state = "failed"
            draft.status_text = _snapshot_failure_text(snapshot)
            draft.send_started_at = 0.0

    def _handle_rust_voice_note_failed(self, event: MessageFailed) -> None:
        draft = self._rust_active_voice_note
        if draft is None:
            return
        if event.message_id and draft.message_id != event.message_id:
            return

        draft.send_state = "failed"
        draft.status_text = event.reason or "Couldn't send"
        draft.send_started_at = 0.0
        self._notify_message_failure(event.message_id, draft.status_text)

    def _notify_rust_message_summary_change(self, snapshot: VoIPRuntimeSnapshot) -> None:
        summary = {
            str(address): dict(value)
            for address, value in snapshot.latest_voice_note_by_contact.items()
        }
        key = _message_summary_key(
            snapshot.unread_voice_notes,
            snapshot.unread_voice_notes_by_contact,
            summary,
        )
        if self._last_rust_message_summary_key == key:
            return
        self._last_rust_message_summary_key = key
        self._notify_message_summary_change(max(0, int(snapshot.unread_voice_notes)), summary)

    def _runtime_voice_note_record_for_contact(
        self,
        sip_address: str,
    ) -> VoIPMessageRecord | None:
        if self._runtime_snapshot is None or not sip_address:
            return None
        summary = self._runtime_snapshot.latest_voice_note_by_contact.get(sip_address)
        if not isinstance(summary, dict):
            return None
        message_id = str(summary.get("message_id", "") or "")
        if not message_id:
            return None
        direction_value = str(summary.get("direction", MessageDirection.INCOMING.value) or "")
        delivery_value = str(summary.get("delivery_state", MessageDeliveryState.QUEUED.value) or "")
        try:
            direction = MessageDirection(direction_value)
        except ValueError:
            direction = MessageDirection.INCOMING
        try:
            delivery_state = MessageDeliveryState(delivery_value)
        except ValueError:
            delivery_state = MessageDeliveryState.QUEUED
        sender = sip_address if direction == MessageDirection.INCOMING else self.config.sip_identity
        recipient = (
            self.config.sip_identity if direction == MessageDirection.INCOMING else sip_address
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        return VoIPMessageRecord(
            id=message_id,
            peer_sip_address=sip_address,
            sender_sip_address=sender,
            recipient_sip_address=recipient,
            kind=MessageKind.VOICE_NOTE,
            direction=direction,
            delivery_state=delivery_state,
            created_at=timestamp,
            updated_at=timestamp,
            local_file_path=str(summary.get("local_file_path", "") or ""),
            duration_ms=max(0, int(summary.get("duration_ms", 0) or 0)),
            unread=bool(summary.get("unread", False)),
            display_name=str(summary.get("display_name", "") or ""),
        )

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

    def _notify_message_summary_change(
        self,
        unread_voice_notes: int,
        latest_voice_note_by_contact: dict[str, dict[str, object]],
    ) -> None:
        for callback in self.message_summary_callbacks:
            try:
                callback(unread_voice_notes, latest_voice_note_by_contact)
            except Exception as exc:
                logger.error("Error in message summary callback: {}", exc)

    def _notify_message_failure(self, message_id: str, reason: str) -> None:
        for callback in self.message_failure_callbacks:
            try:
                callback(message_id, reason)
            except Exception as exc:
                logger.error("Error in message failure callback: {}", exc)

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
        stop = getattr(self.backend, "stop_voice_note_playback", None)
        if callable(stop):
            stop()

    @staticmethod
    def _build_voice_note_playback_command(file_path: str) -> list[str]:
        return _voice_note_playback_command(file_path)


def _message_summary_key(
    unread_voice_notes: int,
    unread_by_contact: dict[str, int],
    latest_by_contact: dict[str, dict[str, object]],
) -> tuple[
    int,
    tuple[tuple[str, int], ...],
    tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
]:
    latest_key = tuple(
        sorted(
            (
                str(address),
                tuple(sorted((str(field), str(value)) for field, value in dict(summary).items())),
            )
            for address, summary in latest_by_contact.items()
        )
    )
    return (
        max(0, int(unread_voice_notes)),
        tuple(
            sorted(
                (str(address), max(0, int(count))) for address, count in unread_by_contact.items()
            )
        ),
        latest_key,
    )


def _build_recording_file_path(config: VoIPConfig) -> str:
    voice_note_dir = Path(config.voice_note_store_dir)
    voice_note_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(voice_note_dir / f"voice-note-{timestamp}.wav")


def _voice_note_playback_command(file_path: str) -> list[str]:
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


def _call_history_entry_from_snapshot(
    manager: VoIPManager,
    raw_entry: dict[str, object],
) -> CallHistoryEntry | None:
    sip_address = str(raw_entry.get("peer_sip_address", "") or "").strip()
    if not sip_address:
        return None

    direction = str(raw_entry.get("direction", "") or "").strip()
    if direction not in {"incoming", "outgoing"}:
        direction = "incoming"

    outcome = str(raw_entry.get("outcome", "") or "").strip()
    if outcome not in {"missed", "completed", "cancelled", "rejected", "failed"}:
        outcome = "failed"

    session_id = str(raw_entry.get("session_id", "") or "").strip()
    return CallHistoryEntry.from_dict(
        {
            "id": session_id or sip_address,
            "direction": direction,
            "display_name": manager._lookup_contact_name(sip_address),
            "sip_address": sip_address,
            "outcome": outcome,
            "duration_seconds": _duration_seconds_from_value(
                raw_entry.get("duration_seconds")
            ),
            "seen": _bool_from_value(raw_entry.get("seen", False)),
        }
    )


def _duration_seconds_from_value(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _bool_from_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = ["VoIPIterateSnapshot", "VoIPManager"]
