"""Round-trip and error-path tests for the sidecar wire protocol."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection

import pytest

from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CallStateChanged,
    CancelVoiceNoteRecording,
    Configure,
    Dial,
    Error,
    Hangup,
    Hello,
    IncomingCall,
    Log,
    MediaStateChanged,
    MessageDeliveryChanged,
    MessageDownloadCompleted,
    MessageFailed,
    MessageReceived,
    Ping,
    Pong,
    PROTOCOL_VERSION,
    ProtocolError,
    Ready,
    Register,
    RegistrationStateChanged,
    Reject,
    SendTextMessage,
    SendVoiceNote,
    SetMute,
    SetVolume,
    Shutdown,
    StartVoiceNoteRecording,
    StopVoiceNoteRecording,
    Unregister,
    decode_command,
    decode_event,
    encode,
    recv_command,
    recv_event,
    send_message,
)


def test_protocol_version_is_pinned() -> None:
    assert PROTOCOL_VERSION == 1


@pytest.mark.parametrize(
    "message",
    [
        Hello(version=1, capabilities=("voip", "messaging")),
        Configure(
            config={
                "sip_server": "sip.example.com",
                "sip_username": "alice",
                "sip_password": "hunter2",
                "transport": "tcp",
            },
            cmd_id=5,
        ),
        Register(cmd_id=7),
        Unregister(),
        Dial(uri="sip:bob@example.com", cmd_id=42),
        Accept(call_id="c-1", cmd_id=8),
        Reject(call_id="c-2"),
        Hangup(call_id="c-3", cmd_id=9),
        SetMute(call_id="c-4", on=True),
        SetVolume(call_id="c-5", level=0.6, cmd_id=10),
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hello",
            client_id="client-msg-1",
            cmd_id=12,
        ),
        StartVoiceNoteRecording(file_path="/tmp/voice-note.wav", cmd_id=13),
        StopVoiceNoteRecording(cmd_id=14),
        CancelVoiceNoteRecording(cmd_id=15),
        SendVoiceNote(
            uri="sip:bob@example.com",
            file_path="/tmp/voice-note.wav",
            duration_ms=4200,
            mime_type="audio/wav",
            client_id="client-msg-vn-1",
            cmd_id=16,
        ),
        Ping(cmd_id=11),
        Shutdown(),
    ],
)
def test_command_round_trip(message: object) -> None:
    decoded = decode_command(encode(message))
    assert decoded == message


@pytest.mark.parametrize(
    "message",
    [
        Hello(version=1, capabilities=()),
        Ready(),
        RegistrationStateChanged(state="registered", reason=None),
        RegistrationStateChanged(state="failed", reason="invalid_credentials"),
        IncomingCall(call_id="c-1", from_uri="sip:bob@example.com", from_display="Bob"),
        CallStateChanged(call_id="c-2", state="active"),
        MediaStateChanged(call_id="c-3", mic_muted=True, speaker_volume=0.8),
        MessageReceived(
            message_id="msg-1",
            peer_sip_address="sip:bob@example.com",
            sender_sip_address="sip:bob@example.com",
            recipient_sip_address="sip:alice@example.com",
            kind="text",
            direction="incoming",
            delivery_state="delivered",
            created_at="2026-04-25T10:00:00Z",
            updated_at="2026-04-25T10:00:00Z",
            text="hello there",
            display_name="Bob",
        ),
        MessageReceived(
            message_id="msg-2",
            peer_sip_address="sip:bob@example.com",
            sender_sip_address="sip:bob@example.com",
            recipient_sip_address="sip:alice@example.com",
            kind="voice_note",
            direction="incoming",
            delivery_state="delivered",
            created_at="2026-04-25T10:01:00Z",
            updated_at="2026-04-25T10:01:00Z",
            local_file_path="/tmp/voice-1.opus",
            mime_type="audio/opus",
            duration_ms=4200,
            unread=True,
        ),
        MessageDeliveryChanged(
            message_id="client-msg-1",
            delivery_state="delivered",
        ),
        MessageDeliveryChanged(
            message_id="client-msg-2",
            delivery_state="failed",
            error="not_registered",
        ),
        MessageDownloadCompleted(
            message_id="msg-3",
            local_file_path="/tmp/inbound.opus",
            mime_type="audio/opus",
        ),
        MessageFailed(message_id="client-msg-3", reason="timeout"),
        Pong(cmd_id=11),
        Error(code="invalid_state", message="not registered", cmd_id=42),
        Log(level="WARNING", message="degraded media"),
    ],
)
def test_event_round_trip(message: object) -> None:
    decoded = decode_event(encode(message))
    assert decoded == message


def test_unknown_command_type_raises() -> None:
    payload = encode(Ready())  # Ready is an event, not a command
    with pytest.raises(ProtocolError, match="Unknown command type"):
        decode_command(payload)


def test_unknown_event_type_raises() -> None:
    payload = encode(Register(cmd_id=1))
    with pytest.raises(ProtocolError, match="Unknown event type"):
        decode_event(payload)


def test_malformed_payload_raises() -> None:
    import msgpack

    junk = msgpack.packb({"not_a_message": True})
    with pytest.raises(ProtocolError, match="Malformed"):
        decode_command(junk)


def test_decode_with_missing_required_field_raises_protocol_error() -> None:
    """Frames missing required dataclass fields must raise ProtocolError, not TypeError.

    Reader threads and the sidecar command loop only catch ProtocolError, so
    a TypeError leaking out of dataclass construction would crash them.
    """

    import msgpack

    # ``Dial`` requires ``uri`` — a frame that omits it must surface as ProtocolError.
    junk = msgpack.packb({"type": "Dial", "data": {"cmd_id": 9}})
    with pytest.raises(ProtocolError, match="Cannot construct Dial"):
        decode_command(junk)


def test_decode_silently_ignores_unknown_extra_fields() -> None:
    """Unknown fields are filtered out by ``_construct`` (forward compat).

    This complements :func:`test_decode_with_missing_required_field_raises_protocol_error`
    by documenting the asymmetric handling: missing required fields are an
    error, but unknown extra fields are silently dropped so newer peers can
    add fields without breaking older readers.
    """

    import msgpack

    payload = msgpack.packb({"type": "Ping", "data": {"cmd_id": 7, "future_field": "ignored"}})
    decoded = decode_command(payload)
    assert decoded == Ping(cmd_id=7)


def test_send_and_recv_command_over_pipe() -> None:
    parent_conn: Connection
    child_conn: Connection
    parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
    try:
        send_message(parent_conn, Register(cmd_id=1))
        send_message(parent_conn, Dial(uri="sip:peer@s", cmd_id=2))

        first = recv_command(child_conn)
        second = recv_command(child_conn)

        assert first == Register(cmd_id=1)
        assert second == Dial(uri="sip:peer@s", cmd_id=2)
    finally:
        parent_conn.close()
        child_conn.close()


def test_send_and_recv_event_over_pipe() -> None:
    parent_conn: Connection
    child_conn: Connection
    parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
    try:
        send_message(child_conn, Ready())
        send_message(
            child_conn,
            RegistrationStateChanged(state="registered", reason=None),
        )

        first = recv_event(parent_conn)
        second = recv_event(parent_conn)

        assert first == Ready()
        assert second == RegistrationStateChanged(state="registered", reason=None)
    finally:
        parent_conn.close()
        child_conn.close()


def test_hello_capabilities_preserves_tuple_type() -> None:
    payload = encode(Hello(version=1, capabilities=("voip", "messaging")))
    decoded = decode_command(payload)
    assert isinstance(decoded.capabilities, tuple)
    assert decoded.capabilities == ("voip", "messaging")
