"""Voice-note service used by the VoIP manager facade."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPBackend
from yoyopod.integrations.call.message_store import VoIPMessageStore
from yoyopod.integrations.call.models import (
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    VoIPConfig,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
)

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp

VOICE_NOTE_SEND_TIMEOUT_SECONDS = 15.0
VOICE_NOTE_CONTAINER_GAIN_DB = 12.0


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


class VoiceNoteService:
    """Own voice-note recording, sending, playback, and active-draft state."""

    def __init__(
        self,
        *,
        config: VoIPConfig,
        backend: VoIPBackend,
        message_store: VoIPMessageStore,
        lookup_contact_name: Callable[[str | None], str],
        notify_message_summary_change: Callable[[], None],
    ) -> None:
        self.config = config
        self.backend = backend
        self._message_store = message_store
        self._lookup_contact_name = lookup_contact_name
        self._notify_message_summary_change = notify_message_summary_change
        self._active_voice_note: VoiceNoteDraft | None = None
        self._playback_process: subprocess.Popen[bytes] | None = None

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
        timestamp = self._iso_now()
        self._message_store.upsert(
            VoIPMessageRecord(
                id=message_id,
                peer_sip_address=draft.recipient_address,
                sender_sip_address=self.config.sip_identity,
                recipient_sip_address=draft.recipient_address,
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.OUTGOING,
                delivery_state=MessageDeliveryState.SENDING,
                created_at=timestamp,
                updated_at=timestamp,
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

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        return self._message_store.unread_voice_note_counts_by_contact()

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
        self.stop_voice_note_playback()
        try:
            command = self.build_voice_note_playback_command(file_path)
            self._playback_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.error("Failed to play voice note {}: {}", file_path, exc)
            return False

    def stop_voice_note_playback(self) -> None:
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

    def handle_message_delivery_changed(self, event: MessageDeliveryChanged) -> None:
        if (
            self._active_voice_note is None
            or self._active_voice_note.message_id != event.message_id
        ):
            return

        if event.delivery_state in (MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED):
            self._active_voice_note.send_state = "sent"
            self._active_voice_note.status_text = (
                "Delivered" if event.delivery_state == MessageDeliveryState.DELIVERED else "Sent"
            )
            self._active_voice_note.send_started_at = 0.0
        elif event.delivery_state == MessageDeliveryState.FAILED:
            self._active_voice_note.send_state = "failed"
            self._active_voice_note.status_text = event.error or "Couldn't send"
            self._active_voice_note.send_started_at = 0.0

    def handle_message_failed(self, event: MessageFailed) -> None:
        if (
            self._active_voice_note is None
            or self._active_voice_note.message_id != event.message_id
        ):
            return
        self._active_voice_note.send_state = "failed"
        self._active_voice_note.status_text = event.reason or "Couldn't send"
        self._active_voice_note.send_started_at = 0.0

    def apply_runtime_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        """Mirror Rust-owned active voice-note state into the current draft."""

        draft = self._active_voice_note
        if draft is None:
            return

        voice_note = snapshot.voice_note
        state = voice_note.state.strip().lower() or "idle"
        if state == "idle":
            return

        if voice_note.file_path and not draft.file_path:
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

    def check_active_voice_note_timeout(self) -> None:
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
    def build_voice_note_playback_command(file_path: str) -> list[str]:
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

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()


def _snapshot_failure_text(snapshot: VoIPRuntimeSnapshot) -> str:
    message = snapshot.last_message
    if message is not None and message.error:
        return message.error
    return "Couldn't send"


class VoiceNoteEventHandler:
    """Keep shared voice-note state aligned with the active VoIP session."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def handle_voice_note_summary_changed(
        self,
        unread_voice_notes: int,
        latest_voice_note_by_contact: dict[str, dict[str, object]],
    ) -> None:
        """Keep Talk voice-note summary state in sync with the VoIP manager."""

        if self.app.context is None:
            return
        self.app.context.update_voice_note_summary(
            unread_voice_notes=unread_voice_notes,
            latest_voice_note_by_contact=latest_voice_note_by_contact,
        )
        self.refresh_talk_related_screen()

    def handle_voice_note_activity_changed(self, *_args: Any) -> None:
        """Refresh active draft state after a message or delivery update."""

        self.sync_active_voice_note_context()
        self.sync_talk_summary_context()
        self.refresh_talk_related_screen()

    def handle_voice_note_failure(self, *_args: Any) -> None:
        """Refresh draft state after a failed message operation."""

        self.sync_active_voice_note_context()
        self.refresh_talk_related_screen()

    def sync_active_voice_note_context(self) -> None:
        """Mirror the active voice-note draft into the shared app context."""

        if self.app.context is None or self.app.voip_manager is None:
            return
        draft = self.app.voip_manager.get_active_voice_note()
        if draft is None:
            self.app.context.update_active_voice_note(send_state="idle")
            return
        self.app.context.update_active_voice_note(
            send_state=draft.send_state,
            status_text=draft.status_text,
            file_path=draft.file_path,
            duration_ms=draft.duration_ms,
        )

    def sync_talk_summary_context(self) -> None:
        """Refresh Talk summary counts and latest voice-note metadata in AppContext."""

        if self.app.context is None or self.app.call_history_store is None:
            return

        self.app.context.update_call_summary(
            missed_calls=self.app.call_history_store.missed_count(),
            recent_calls=self.app.call_history_store.recent_preview(),
        )
        if self.app.voip_manager is not None:
            self.app.context.update_voice_note_summary(
                unread_voice_notes=self.app.voip_manager.unread_voice_note_count(),
                latest_voice_note_by_contact=self.app.voip_manager.latest_voice_note_summary(),
            )

    def refresh_talk_related_screen(self) -> None:
        """Re-render Talk screens when their message state changes."""

        if self.app.screen_manager is None:
            return
        current_screen = self.app.screen_manager.get_current_screen()
        if current_screen is None:
            return
        if current_screen.route_name in {"call", "talk_contact", "voice_note"}:
            self.app.screen_manager.refresh_current_screen()


__all__ = [
    "VOICE_NOTE_CONTAINER_GAIN_DB",
    "VOICE_NOTE_SEND_TIMEOUT_SECONDS",
    "VoiceNoteDraft",
    "VoiceNoteEventHandler",
    "VoiceNoteService",
]
