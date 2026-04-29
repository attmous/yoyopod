"""Messaging service used by the VoIP manager facade."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPBackend
from yoyopod.integrations.call.message_store import VoIPMessageStore
from yoyopod.integrations.call.models import (
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageDownloadCompleted,
    MessageFailed,
    MessageKind,
    VoIPConfig,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
)


class MessagingService:
    """Own message persistence, text sending, and message callback forwarding."""

    def __init__(
        self,
        *,
        config: VoIPConfig,
        backend: VoIPBackend,
        message_store: VoIPMessageStore,
        lookup_contact_name: Callable[[str | None], str],
    ) -> None:
        self.config = config
        self.backend = backend
        self.message_store = message_store
        self._lookup_contact_name = lookup_contact_name
        self.message_received_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_delivery_callbacks: list[Callable[[VoIPMessageRecord], None]] = []
        self.message_failure_callbacks: list[Callable[[str, str], None]] = []
        self.message_summary_callbacks: list[
            Callable[[int, dict[str, dict[str, object]]], None]
        ] = []

    def send_text_message(self, sip_address: str, text: str, display_name: str = "") -> bool:
        message_id = self.backend.send_text_message(sip_address, text)
        if not message_id:
            return False

        timestamp = self._iso_now()
        self.message_store.upsert(
            VoIPMessageRecord(
                id=message_id,
                peer_sip_address=sip_address,
                sender_sip_address=self.config.sip_identity,
                recipient_sip_address=sip_address,
                kind=MessageKind.TEXT,
                direction=MessageDirection.OUTGOING,
                delivery_state=MessageDeliveryState.SENDING,
                created_at=timestamp,
                updated_at=timestamp,
                text=text,
                display_name=display_name or self._lookup_contact_name(sip_address),
            )
        )
        self.notify_message_summary_change()
        return True

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

    def handle_message_received(self, message: VoIPMessageRecord) -> None:
        record = self._decorate_message(self._normalize_message_record(message))
        logger.info(
            "VoIPManager received message: id={} kind={} direction={} peer={} file={}",
            record.id,
            record.kind.value,
            record.direction.value,
            record.peer_sip_address,
            record.local_file_path,
        )
        self.message_store.upsert(record)
        for callback in self.message_received_callbacks:
            try:
                callback(record)
            except Exception as exc:
                logger.error("Error in message received callback: {}", exc)
        self.notify_message_summary_change()

    def handle_message_delivery_changed(self, event: MessageDeliveryChanged) -> None:
        self.message_store.update_delivery(
            event.message_id,
            event.delivery_state,
            local_file_path=event.local_file_path,
        )
        record = self.message_store.get(event.message_id)
        if record is None:
            return

        for callback in self.message_delivery_callbacks:
            try:
                callback(record)
            except Exception as exc:
                logger.error("Error in message delivery callback: {}", exc)
        self.notify_message_summary_change()

    def handle_message_download_completed(self, event: MessageDownloadCompleted) -> None:
        record = self.message_store.get(event.message_id)
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
        self.message_store.upsert(updated)
        for callback in self.message_delivery_callbacks:
            try:
                callback(updated)
            except Exception as exc:
                logger.error("Error in message download callback: {}", exc)
        self.notify_message_summary_change()

    def handle_message_failed(self, event: MessageFailed) -> None:
        self.message_store.update_delivery(event.message_id, MessageDeliveryState.FAILED)
        for callback in self.message_failure_callbacks:
            try:
                callback(event.message_id, event.reason)
            except Exception as exc:
                logger.error("Error in message failure callback: {}", exc)
        self.notify_message_summary_change()

    def apply_runtime_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        """Mirror Rust-owned last-message facts into known persisted records."""

        message = snapshot.last_message
        if message is None or not message.message_id:
            return

        record = self.message_store.get(message.message_id)
        if record is None:
            return

        delivery_state = message.delivery_state or record.delivery_state
        local_file_path = message.local_file_path or record.local_file_path
        if delivery_state == record.delivery_state and local_file_path == record.local_file_path:
            return

        updated = replace(
            record,
            delivery_state=delivery_state,
            local_file_path=local_file_path,
            updated_at=self._iso_now(),
        )
        self.message_store.upsert(updated)
        for callback in self.message_delivery_callbacks:
            try:
                callback(updated)
            except Exception as exc:
                logger.error("Error in message snapshot callback: {}", exc)
        self.notify_message_summary_change()

    def unread_voice_note_count(self) -> int:
        return self.message_store.unread_voice_note_count()

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        return self.message_store.unread_voice_note_counts_by_contact()

    def latest_voice_note_summary(self) -> dict[str, dict[str, object]]:
        return self.message_store.latest_voice_note_by_contact()

    def notify_message_summary_change(self) -> None:
        unread = self.unread_voice_note_count()
        summary = self.latest_voice_note_summary()
        for callback in self.message_summary_callbacks:
            try:
                callback(unread, summary)
            except Exception as exc:
                logger.error("Error in message summary callback: {}", exc)

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

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()
