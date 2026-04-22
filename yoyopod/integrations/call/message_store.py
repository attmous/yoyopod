"""Persistent message and voice-note storage for the call domain."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from yoyopod.integrations.call.models import (
    MessageDeliveryState,
    MessageDirection,
    MessageKind,
    VoIPMessageRecord,
)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO8601 string."""

    return datetime.now(timezone.utc).isoformat()


class VoIPMessageStore:
    """Persist Talk messages and voice-note metadata to JSON on disk."""

    def __init__(self, store_dir: str | Path, max_entries: int = 200) -> None:
        self.store_dir = Path(store_dir)
        self.max_entries = max(1, int(max_entries))
        self.index_file = self.store_dir / "messages.json"
        self._messages: list[VoIPMessageRecord] = []
        self.load()

    def load(self) -> None:
        """Load message metadata from disk if present."""

        if not self.index_file.exists():
            self._messages = []
            return

        try:
            with open(self.index_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            items = payload.get("messages", [])
            self._messages = [self._from_dict(item) for item in items]
            self._messages = self._messages[: self.max_entries]
        except Exception as exc:
            logger.warning("Failed to load message store from {}: {}", self.index_file, exc)
            self._messages = []

    def save(self) -> None:
        """Persist the current message metadata index to disk."""

        try:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            with open(self.index_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {"messages": [self._to_dict(message) for message in self._messages[: self.max_entries]]},
                    handle,
                    indent=2,
                )
        except Exception as exc:
            logger.warning("Failed to save message store to {}: {}", self.index_file, exc)

    def upsert(self, message: VoIPMessageRecord) -> VoIPMessageRecord:
        """Insert or replace one message record and persist the updated index."""

        self._messages = [existing for existing in self._messages if existing.id != message.id]
        self._messages.insert(0, message)
        self._messages = self._messages[: self.max_entries]
        self.save()
        return message

    def get(self, message_id: str) -> VoIPMessageRecord | None:
        """Return one message by id if present."""

        for message in self._messages:
            if message.id == message_id:
                return message
        return None

    def update_delivery(
        self,
        message_id: str,
        delivery_state: MessageDeliveryState,
        *,
        local_file_path: str | None = None,
    ) -> VoIPMessageRecord | None:
        """Update delivery state for one message and persist the change."""

        message = self.get(message_id)
        if message is None:
            return None

        updated = replace(
            message,
            delivery_state=delivery_state,
            updated_at=_utc_now_iso(),
            local_file_path=local_file_path or message.local_file_path,
        )
        return self.upsert(updated)

    def mark_contact_seen(self, sip_address: str) -> None:
        """Mark all incoming unread messages from one peer as read."""

        changed = False
        updated_messages: list[VoIPMessageRecord] = []
        for message in self._messages:
            if (
                message.peer_sip_address == sip_address
                and message.direction == MessageDirection.INCOMING
                and message.unread
            ):
                updated_messages.append(
                    replace(message, unread=False, updated_at=_utc_now_iso())
                )
                changed = True
            else:
                updated_messages.append(message)

        if changed:
            self._messages = updated_messages
            self.save()

    def list_recent(self, limit: int | None = None) -> list[VoIPMessageRecord]:
        """Return recent messages, newest first."""

        if limit is None:
            return list(self._messages)
        return list(self._messages[: max(0, limit)])

    def unread_voice_note_count(self) -> int:
        """Return the number of unread incoming voice notes."""

        return sum(
            1
            for message in self._messages
            if message.kind == MessageKind.VOICE_NOTE
            and message.direction == MessageDirection.INCOMING
            and message.unread
        )

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        """Return unread incoming voice-note counts grouped by peer address."""

        counts: dict[str, int] = {}
        for message in self._messages:
            if (
                message.kind != MessageKind.VOICE_NOTE
                or message.direction != MessageDirection.INCOMING
                or not message.unread
                or not message.peer_sip_address
            ):
                continue
            counts[message.peer_sip_address] = counts.get(message.peer_sip_address, 0) + 1
        return counts

    def latest_voice_note_by_contact(self) -> dict[str, dict[str, object]]:
        """Return compact per-contact voice-note metadata for the Talk UI."""

        latest: dict[str, dict[str, object]] = {}
        for message in self._messages:
            if message.kind != MessageKind.VOICE_NOTE:
                continue
            if message.peer_sip_address in latest:
                continue
            latest[message.peer_sip_address] = {
                "message_id": message.id,
                "direction": message.direction.value,
                "delivery_state": message.delivery_state.value,
                "local_file_path": message.local_file_path,
                "duration_ms": message.duration_ms,
                "unread": message.unread,
                "display_name": message.display_name,
            }
        return latest

    def latest_voice_note_for_contact(self, sip_address: str) -> VoIPMessageRecord | None:
        """Return the latest voice-note record for one peer."""

        for message in self._messages:
            if message.peer_sip_address == sip_address and message.kind == MessageKind.VOICE_NOTE:
                return message
        return None

    @staticmethod
    def _to_dict(message: VoIPMessageRecord) -> dict[str, object]:
        return {
            "id": message.id,
            "peer_sip_address": message.peer_sip_address,
            "sender_sip_address": message.sender_sip_address,
            "recipient_sip_address": message.recipient_sip_address,
            "kind": message.kind.value,
            "direction": message.direction.value,
            "delivery_state": message.delivery_state.value,
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "text": message.text,
            "local_file_path": message.local_file_path,
            "mime_type": message.mime_type,
            "duration_ms": message.duration_ms,
            "unread": message.unread,
            "display_name": message.display_name,
        }

    @staticmethod
    def _from_dict(data: dict[str, object]) -> VoIPMessageRecord:
        return VoIPMessageRecord(
            id=str(data.get("id", "")),
            peer_sip_address=str(data.get("peer_sip_address", "")),
            sender_sip_address=str(data.get("sender_sip_address", "")),
            recipient_sip_address=str(data.get("recipient_sip_address", "")),
            kind=MessageKind(str(data.get("kind", MessageKind.TEXT.value))),
            direction=MessageDirection(str(data.get("direction", MessageDirection.INCOMING.value))),
            delivery_state=MessageDeliveryState(
                str(data.get("delivery_state", MessageDeliveryState.QUEUED.value))
            ),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
            text=str(data.get("text", "")),
            local_file_path=str(data.get("local_file_path", "")),
            mime_type=str(data.get("mime_type", "")),
            duration_ms=max(0, int(data.get("duration_ms", 0) or 0)),
            unread=bool(data.get("unread", False)),
            display_name=str(data.get("display_name", "")),
        )
