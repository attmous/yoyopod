"""Focused unit tests for the extracted VoIP messaging and voice-note services."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from yoyopod.communication.calling.mock_backend import MockVoIPBackend
from yoyopod.communication.calling.messaging import MessagingService
from yoyopod.communication.calling.voice_notes import VoiceNoteService
from yoyopod.communication.messaging import VoIPMessageStore
from yoyopod.communication.models import (
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    VoIPConfig,
    VoIPMessageRecord,
)


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


def lookup_contact_name(sip_address: str | None) -> str:
    """Resolve one address to a deterministic display name for tests."""

    if sip_address == "sip:mom@example.com":
        return "Mom"
    return "Unknown"


def test_calling_package_reexports_iterate_metrics() -> None:
    """The calling package should expose iterate metrics without backend imports."""

    from yoyopod.communication.calling import VoIPIterateMetrics

    assert VoIPIterateMetrics().drained_events == 0


def test_backend_compat_shim_imports_mock_without_liblinphone() -> None:
    """Mock-only imports should not pull in the production Liblinphone backend."""

    repo_root = Path(__file__).resolve().parents[1]
    script = """
import importlib
import sys

module = importlib.import_module("yoyopod.communication.calling.backend_protocol")
assert "yoyopod.communication.integrations.liblinphone.backend" not in sys.modules
assert module.VoIPBackend.__name__ == "VoIPBackend"
assert "yoyopod.communication.calling.mock_backend" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


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
