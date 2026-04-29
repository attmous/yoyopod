"""Focused unit tests for the extracted VoIP messaging and voice-note services."""

from __future__ import annotations

import time
from pathlib import Path

from yoyopod.backends.voip import MockVoIPBackend
from yoyopod.integrations.call.messaging import MessagingService
from yoyopod.integrations.call.message_store import VoIPMessageStore
from yoyopod.integrations.call.models import (
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    VoIPConfig,
    VoIPMessageSnapshot,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
    VoIPVoiceNoteSnapshot,
)
from yoyopod.integrations.call import VoiceNoteService


def build_config(tmp_path: Path) -> VoIPConfig:
    """Create a test VoIP configuration backed by a temporary store."""

    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_password_ha1="hash",
        sip_identity="sip:alice@sip.example.com",
        file_transfer_server_url="https://transfer.example.com",
        message_store_dir=str(tmp_path / "messages"),
        voice_note_store_dir=str(tmp_path / "voice_notes"),
    )


def build_message_store(config: VoIPConfig) -> VoIPMessageStore:
    """Create a message store for one test config."""

    return VoIPMessageStore(config.message_store_dir)


def test_voip_config_requires_server_and_identity_for_backend_start(tmp_path: Path) -> None:
    """Backend startup should only proceed when the canonical SIP minimum is configured."""

    config = build_config(tmp_path)

    assert config.is_backend_start_configured() is True

    config.sip_identity = ""
    assert config.is_backend_start_configured() is False

    config.sip_identity = "sip:alice@sip.example.com"
    config.sip_server = ""
    assert config.is_backend_start_configured() is False


def lookup_contact_name(sip_address: str | None) -> str:
    """Resolve one address to a deterministic display name for tests."""

    if sip_address == "sip:mom@example.com":
        return "Mom"
    return "Unknown"


def test_messaging_service_normalizes_rcs_voice_note_envelope(tmp_path: Path) -> None:
    """MessagingService should coerce voice-note envelopes into voice-note records."""

    config = build_config(tmp_path)
    service = MessagingService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
    )
    envelope = VoIPMessageRecord(
        id="incoming-envelope-1",
        peer_sip_address="sip:mom@example.com",
        sender_sip_address="sip:mom@example.com",
        recipient_sip_address="sip:alice@example.com",
        kind=MessageKind.TEXT,
        direction=MessageDirection.INCOMING,
        delivery_state=MessageDeliveryState.SENDING,
        created_at="2026-04-06T00:00:00+00:00",
        updated_at="2026-04-06T00:00:00+00:00",
        text=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<file xmlns="urn:gsma:params:xml:ns:rcs:rcs:fthttp" '
            'xmlns:am="urn:gsma:params:xml:ns:rcs:rcs:rram">'
            '<file-info type="file">'
            "<content-type>audio/wav;voice-recording=yes</content-type>"
            "<am:playing-length>4046</am:playing-length>"
            "</file-info>"
            "</file>"
        ),
        local_file_path="/tmp/incoming-envelope.mka",
        mime_type="application/vnd.gsma.rcs-ft-http+xml",
        unread=True,
    )

    normalized = service._normalize_message_record(envelope)

    assert normalized.kind == MessageKind.VOICE_NOTE
    assert normalized.mime_type == "audio/wav"
    assert normalized.duration_ms == 4046
    assert normalized.text == ""


def test_messaging_service_decorates_and_persists_incoming_messages(tmp_path: Path) -> None:
    """Incoming messages should be decorated before they are persisted or forwarded."""

    config = build_config(tmp_path)
    service = MessagingService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
    )
    received: list[VoIPMessageRecord] = []
    service.on_message_received(received.append)

    service.handle_message_received(
        VoIPMessageRecord(
            id="incoming-1",
            peer_sip_address="sip:mom@example.com",
            sender_sip_address="sip:mom@example.com",
            recipient_sip_address="sip:alice@example.com",
            kind=MessageKind.TEXT,
            direction=MessageDirection.INCOMING,
            delivery_state=MessageDeliveryState.DELIVERED,
            created_at="2026-04-06T00:00:00+00:00",
            updated_at="2026-04-06T00:00:00+00:00",
            text="hello",
        )
    )

    stored = service.message_store.get("incoming-1")
    assert stored is not None
    assert stored.display_name == "Mom"
    assert received[-1].display_name == "Mom"


def test_messaging_service_applies_runtime_snapshot_to_known_message_once(
    tmp_path: Path,
) -> None:
    """Rust last-message snapshots should mirror known records without duplicate summaries."""

    config = build_config(tmp_path)
    service = MessagingService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
    )
    summary_events: list[str] = []
    service.on_message_summary_change(lambda _unread, _summary: summary_events.append("changed"))
    service.message_store.upsert(
        VoIPMessageRecord(
            id="msg-1",
            peer_sip_address="sip:mom@example.com",
            sender_sip_address="sip:alice@example.com",
            recipient_sip_address="sip:mom@example.com",
            kind=MessageKind.VOICE_NOTE,
            direction=MessageDirection.OUTGOING,
            delivery_state=MessageDeliveryState.SENDING,
            created_at="2026-04-29T00:00:00+00:00",
            updated_at="2026-04-29T00:00:00+00:00",
            local_file_path="",
        )
    )
    snapshot = VoIPRuntimeSnapshot(
        last_message=VoIPMessageSnapshot(
            message_id="msg-1",
            kind=MessageKind.VOICE_NOTE,
            direction=MessageDirection.OUTGOING,
            delivery_state=MessageDeliveryState.DELIVERED,
            local_file_path="/tmp/note.wav",
        )
    )

    service.apply_runtime_snapshot(snapshot)
    service.apply_runtime_snapshot(snapshot)
    service.apply_runtime_snapshot(
        VoIPRuntimeSnapshot(
            last_message=VoIPMessageSnapshot(
                message_id="unknown",
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.OUTGOING,
                delivery_state=MessageDeliveryState.DELIVERED,
                local_file_path="/tmp/unknown.wav",
            )
        )
    )

    stored = service.message_store.get("msg-1")
    assert stored is not None
    assert stored.delivery_state == MessageDeliveryState.DELIVERED
    assert stored.local_file_path == "/tmp/note.wav"
    assert service.message_store.get("unknown") is None
    assert summary_events == ["changed"]


def test_message_store_tracks_unread_voice_note_counts_by_contact(tmp_path: Path) -> None:
    """Unread incoming voice notes should be grouped by peer address."""

    config = build_config(tmp_path)
    store = build_message_store(config)
    for index, address in enumerate(
        [
            "sip:mom@example.com",
            "sip:mom@example.com",
            "sip:dad@example.com",
        ],
        start=1,
    ):
        store.upsert(
            VoIPMessageRecord(
                id=f"incoming-{index}",
                peer_sip_address=address,
                sender_sip_address=address,
                recipient_sip_address="sip:alice@example.com",
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.INCOMING,
                delivery_state=MessageDeliveryState.DELIVERED,
                created_at="2026-04-06T00:00:00+00:00",
                updated_at="2026-04-06T00:00:00+00:00",
                unread=True,
            )
        )

    store.upsert(
        VoIPMessageRecord(
            id="outgoing-1",
            peer_sip_address="sip:mom@example.com",
            sender_sip_address="sip:alice@example.com",
            recipient_sip_address="sip:mom@example.com",
            kind=MessageKind.VOICE_NOTE,
            direction=MessageDirection.OUTGOING,
            delivery_state=MessageDeliveryState.DELIVERED,
            created_at="2026-04-06T00:00:00+00:00",
            updated_at="2026-04-06T00:00:00+00:00",
            unread=False,
        )
    )

    assert store.unread_voice_note_count() == 3
    assert store.unread_voice_note_counts_by_contact() == {
        "sip:dad@example.com": 1,
        "sip:mom@example.com": 2,
    }

    store.mark_contact_seen("sip:mom@example.com")

    assert store.unread_voice_note_counts_by_contact() == {
        "sip:dad@example.com": 1,
    }


def test_voice_note_service_transitions_recording_review_and_sending(tmp_path: Path) -> None:
    """VoiceNoteService should manage the active draft through record and send states."""

    config = build_config(tmp_path)
    backend = MockVoIPBackend()
    summary_events: list[str] = []
    service = VoiceNoteService(
        config=config,
        backend=backend,
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
        notify_message_summary_change=lambda: summary_events.append("changed"),
    )

    assert service.start_voice_note_recording("sip:mom@example.com")
    active = service.get_active_voice_note()
    assert active is not None
    assert active.send_state == "recording"

    review = service.stop_voice_note_recording()
    assert review is not None
    assert review.send_state == "review"
    assert review.status_text == "Ready to send"

    assert service.send_active_voice_note() is True
    sending = service.get_active_voice_note()
    assert sending is not None
    assert sending.send_state == "sending"
    assert sending.message_id == "mock-note-1"
    assert summary_events == ["changed"]
    assert service._message_store.get("mock-note-1") is not None


def test_voice_note_service_flags_oversized_recordings_on_stop(tmp_path: Path) -> None:
    """Stopping an oversized recording should leave the draft in a failed review state."""

    config = build_config(tmp_path)
    config.voice_note_max_duration_seconds = 1
    backend = MockVoIPBackend()
    backend.recording_duration_ms = 1200
    service = VoiceNoteService(
        config=config,
        backend=backend,
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
        notify_message_summary_change=lambda: None,
    )

    assert service.start_voice_note_recording("sip:mom@example.com")

    failed = service.stop_voice_note_recording()

    assert failed is not None
    assert failed.send_state == "failed"
    assert failed.status_text == "Note too long"


def test_voice_note_service_updates_active_draft_on_delivery_and_failure(
    tmp_path: Path,
) -> None:
    """Delivery and failure events should update the active draft directly."""

    config = build_config(tmp_path)
    service = VoiceNoteService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
        notify_message_summary_change=lambda: None,
    )
    assert service.start_voice_note_recording("sip:mom@example.com")
    assert service.stop_voice_note_recording() is not None
    assert service.send_active_voice_note() is True

    service.handle_message_delivery_changed(
        MessageDeliveryChanged(
            message_id="mock-note-1",
            delivery_state=MessageDeliveryState.DELIVERED,
        )
    )
    delivered = service.get_active_voice_note()
    assert delivered is not None
    assert delivered.send_state == "sent"
    assert delivered.status_text == "Delivered"

    delivered.send_state = "sending"
    delivered.send_started_at = time.monotonic()
    service.handle_message_failed(MessageFailed(message_id="mock-note-1", reason="Upload failed"))
    failed = service.get_active_voice_note()
    assert failed is not None
    assert failed.send_state == "failed"
    assert failed.status_text == "Upload failed"


def test_voice_note_service_applies_runtime_snapshot_to_active_draft(
    tmp_path: Path,
) -> None:
    """Rust voice-note snapshots should update state without wiping local draft metadata."""

    config = build_config(tmp_path)
    service = VoiceNoteService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
        notify_message_summary_change=lambda: None,
    )
    assert service.start_voice_note_recording("sip:mom@example.com", "Mom")
    assert service.stop_voice_note_recording() is not None
    assert service.send_active_voice_note() is True
    draft = service.get_active_voice_note()
    assert draft is not None
    original_path = draft.file_path
    draft.send_started_at = 42.0

    service.apply_runtime_snapshot(
        VoIPRuntimeSnapshot(
            voice_note=VoIPVoiceNoteSnapshot(
                state="sending",
                file_path="",
                duration_ms=2400,
                mime_type="audio/ogg",
                message_id="rust-msg-1",
            )
        )
    )

    sending = service.get_active_voice_note()
    assert sending is not None
    assert sending.recipient_address == "sip:mom@example.com"
    assert sending.recipient_name == "Mom"
    assert sending.file_path == original_path
    assert sending.duration_ms == 2400
    assert sending.mime_type == "audio/ogg"
    assert sending.message_id == "rust-msg-1"
    assert sending.send_state == "sending"
    assert sending.status_text == "Sending..."
    assert sending.send_started_at == 42.0

    service.apply_runtime_snapshot(
        VoIPRuntimeSnapshot(
            voice_note=VoIPVoiceNoteSnapshot(
                state="failed",
                message_id="rust-msg-1",
            ),
            last_message=VoIPMessageSnapshot(
                message_id="rust-msg-1",
                delivery_state=MessageDeliveryState.FAILED,
                error="Upload failed",
            ),
        )
    )

    failed = service.get_active_voice_note()
    assert failed is not None
    assert failed.send_state == "failed"
    assert failed.status_text == "Upload failed"
    assert failed.send_started_at == 0.0


def test_voice_note_service_enforces_send_timeout_and_marks_store_failed(tmp_path: Path) -> None:
    """Timed-out sends should fail both the active draft and the persisted message record."""

    config = build_config(tmp_path)
    summary_events: list[str] = []
    service = VoiceNoteService(
        config=config,
        backend=MockVoIPBackend(),
        message_store=build_message_store(config),
        lookup_contact_name=lookup_contact_name,
        notify_message_summary_change=lambda: summary_events.append("changed"),
    )
    assert service.start_voice_note_recording("sip:mom@example.com")
    assert service.stop_voice_note_recording() is not None
    assert service.send_active_voice_note() is True

    active = service.get_active_voice_note()
    assert active is not None
    active.send_started_at = time.monotonic() - 30.0

    service.check_active_voice_note_timeout()

    timed_out = service.get_active_voice_note()
    assert timed_out is not None
    assert timed_out.send_state == "failed"
    assert timed_out.status_text == "Send timed out"
    stored = service._message_store.get("mock-note-1")
    assert stored is not None
    assert stored.delivery_state == MessageDeliveryState.FAILED
    assert summary_events == ["changed", "changed"]
