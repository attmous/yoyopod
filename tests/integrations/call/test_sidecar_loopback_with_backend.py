"""End-to-end loopback tests that wire ``SidecarSupervisor`` -> sidecar_main ->
``SidecarBackendAdapter`` -> ``MockVoIPBackend`` together.

These tests exercise the full Phase 2B.2 stack inside one Python process via
loopback mode (#378) — the supervisor runs the real ``run_sidecar`` entry
point on a daemon thread, which constructs the adapter and routes commands
through a mock backend that we control from the test.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import pytest

from yoyopod.backends.voip.mock_backend import MockVoIPBackend
from yoyopod.integrations.call.models import (
    CallState,
    CallStateChanged as BackendCallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged as BackendMessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageKind,
    MessageReceived as BackendMessageReceived,
    RegistrationState,
    RegistrationStateChanged as BackendRegistrationStateChanged,
    VoIPConfig,
    VoIPMessageRecord,
)
from yoyopod.integrations.call.sidecar_main import run_sidecar
from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CallStateChanged,
    CancelVoiceNoteRecording,
    Configure,
    Dial,
    Hangup,
    IncomingCall,
    MessageDeliveryChanged,
    MessageReceived,
    Ping,
    Pong,
    Register,
    RegistrationStateChanged,
    SendTextMessage,
    SendVoiceNote,
    StartVoiceNoteRecording,
    StopVoiceNoteRecording,
    Unregister,
)
from yoyopod.integrations.call.sidecar_supervisor import SidecarSupervisor

LOOPBACK_BUDGET_SECONDS = 2.0


# Module-level so loopback (and a future spawn variant) can both pickle/find it.
_TEST_BACKEND_HANDLE: dict[str, MockVoIPBackend] = {}


def _shared_mock_backend_factory(_config: VoIPConfig) -> MockVoIPBackend:
    """Hand back the test-shared :class:`MockVoIPBackend` so the test can drive it."""

    return _TEST_BACKEND_HANDLE["backend"]


def _sidecar_target_with_mock_backend(conn: Connection) -> None:
    """Loopback sidecar target that wires a shared mock backend into ``run_sidecar``."""

    run_sidecar(conn, backend_factory=_shared_mock_backend_factory)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def collected_events() -> list[Any]:
    return []


@pytest.fixture
def event_handler(collected_events: list[Any]) -> Callable[[Any], None]:
    return collected_events.append


@pytest.fixture
def shared_mock_backend() -> MockVoIPBackend:
    backend = MockVoIPBackend()
    _TEST_BACKEND_HANDLE["backend"] = backend
    yield backend
    _TEST_BACKEND_HANDLE.clear()


@pytest.fixture
def supervisor(
    event_handler: Callable[[Any], None], shared_mock_backend: MockVoIPBackend
) -> SidecarSupervisor:
    sup = SidecarSupervisor(
        on_event=event_handler,
        sidecar_target=_sidecar_target_with_mock_backend,
        use_loopback=True,
        handshake_timeout_seconds=LOOPBACK_BUDGET_SECONDS,
    )
    sup.start()
    assert sup.wait_for_state("running", timeout_seconds=LOOPBACK_BUDGET_SECONDS)
    yield sup
    sup.stop(timeout_seconds=LOOPBACK_BUDGET_SECONDS)


def _wait_for(predicate, *, timeout: float = LOOPBACK_BUDGET_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _serialized_config() -> dict[str, Any]:
    return dataclasses.asdict(
        VoIPConfig(sip_server="sip.example.com", sip_identity="sip:alice@example.com")
    )


# ---------------------------------------------------------------------------
# End-to-end flows
# ---------------------------------------------------------------------------


def test_configure_and_register_starts_mock_backend(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)
    assert shared_mock_backend.running


def test_backend_event_round_trips_to_main(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    shared_mock_backend.emit(BackendRegistrationStateChanged(state=RegistrationState.OK))
    assert _wait_for(
        lambda: any(
            isinstance(event, RegistrationStateChanged) and event.state == "ok"
            for event in collected_events
        )
    )


def test_incoming_call_then_accept_drives_backend(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    shared_mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    assert _wait_for(lambda: any(isinstance(event, IncomingCall) for event in collected_events))
    incoming = next(event for event in collected_events if isinstance(event, IncomingCall))

    supervisor.send(Accept(call_id=incoming.call_id, cmd_id=3))
    assert _wait_for(lambda: "answer" in shared_mock_backend.commands)


def test_call_state_change_flows_back_with_call_id(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    shared_mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    assert _wait_for(lambda: any(isinstance(event, IncomingCall) for event in collected_events))
    incoming = next(event for event in collected_events if isinstance(event, IncomingCall))

    shared_mock_backend.emit(BackendCallStateChanged(state=CallState.CONNECTED))
    assert _wait_for(
        lambda: any(
            isinstance(event, CallStateChanged)
            and event.call_id == incoming.call_id
            and event.state == "connected"
            for event in collected_events
        )
    )


def test_dial_then_hangup_round_trips(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    supervisor.send(Dial(uri="sip:bob@example.com", cmd_id=3))
    assert _wait_for(lambda: "call sip:bob@example.com" in shared_mock_backend.commands)

    # Adapter assigned a call_id; main can hang up using the same id.
    # Simulate that by reading the call id off the adapter via the backend's
    # callback registration: the adapter mints call-1 the first time it sees
    # a dial succeed, so we just send Hangup with that label.
    supervisor.send(Hangup(call_id="call-1", cmd_id=4))
    assert _wait_for(lambda: "terminate" in shared_mock_backend.commands)


def test_unregister_stops_mock_backend(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    supervisor.send(Unregister())
    assert _wait_for(lambda: not shared_mock_backend.running)


def test_ping_works_without_configure(
    supervisor: SidecarSupervisor, collected_events: list[Any]
) -> None:
    supervisor.send(Ping(cmd_id=77))
    assert _wait_for(
        lambda: any(isinstance(event, Pong) and event.cmd_id == 77 for event in collected_events)
    )


# ---------------------------------------------------------------------------
# Messaging round-trip (Phase 2B.4)
# ---------------------------------------------------------------------------


def test_send_text_message_round_trips_with_id_translation(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    """Outbound text message: SendTextMessage -> backend.send_text_message -> mapped delivery event."""

    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    shared_mock_backend.next_text_message_id = "backend-msg-loop"
    supervisor.send(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="loopback hello",
            client_id="client-msg-loop",
            cmd_id=3,
        )
    )
    assert _wait_for(
        lambda: "text sip:bob@example.com loopback hello" in shared_mock_backend.commands
    )

    # Drive the delivery event from the backend; sidecar should re-key the
    # backend id to the client id main minted, so the on-wire delivery event
    # carries ``client-msg-loop``.
    shared_mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="backend-msg-loop",
            delivery_state=MessageDeliveryState.DELIVERED,
        )
    )
    assert _wait_for(
        lambda: any(
            isinstance(event, MessageDeliveryChanged)
            and event.message_id == "client-msg-loop"
            and event.delivery_state == MessageDeliveryState.DELIVERED.value
            for event in collected_events
        )
    )


def test_inbound_message_received_round_trips(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    """Inbound MessageReceived flows through the wire as flat fields."""

    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    record = VoIPMessageRecord(
        id="inbound-loop-1",
        peer_sip_address="sip:bob@example.com",
        sender_sip_address="sip:bob@example.com",
        recipient_sip_address="sip:alice@example.com",
        kind=MessageKind.TEXT,
        direction=MessageDirection.INCOMING,
        delivery_state=MessageDeliveryState.DELIVERED,
        created_at="2026-04-25T12:00:00+00:00",
        updated_at="2026-04-25T12:00:00+00:00",
        text="ping from bob",
        unread=True,
    )
    shared_mock_backend.emit(BackendMessageReceived(message=record))
    assert _wait_for(
        lambda: any(
            isinstance(event, MessageReceived)
            and event.message_id == "inbound-loop-1"
            and event.text == "ping from bob"
            and event.kind == MessageKind.TEXT.value
            and event.unread is True
            for event in collected_events
        )
    )


# ---------------------------------------------------------------------------
# Voice notes round-trip (Phase 2B.4b)
# ---------------------------------------------------------------------------


def test_voice_note_record_stop_round_trips(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    """Start + Stop voice-note commands invoke the backend through the wire."""

    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    supervisor.send(StartVoiceNoteRecording(file_path="/tmp/voice-loop.wav", cmd_id=3))
    assert _wait_for(lambda: shared_mock_backend.recording_active)

    supervisor.send(StopVoiceNoteRecording(cmd_id=4))
    assert _wait_for(lambda: not shared_mock_backend.recording_active)
    assert "record-stop" in shared_mock_backend.commands


def test_voice_note_cancel_round_trips(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    supervisor.send(StartVoiceNoteRecording(file_path="/tmp/voice-cancel.wav", cmd_id=3))
    assert _wait_for(lambda: shared_mock_backend.recording_active)

    supervisor.send(CancelVoiceNoteRecording(cmd_id=4))
    assert _wait_for(lambda: not shared_mock_backend.recording_active)
    assert "record-cancel" in shared_mock_backend.commands


def test_send_voice_note_round_trips_with_id_translation(
    supervisor: SidecarSupervisor,
    shared_mock_backend: MockVoIPBackend,
    collected_events: list[Any],
) -> None:
    """SendVoiceNote -> backend.send_voice_note + delivery event re-keyed to client_id."""

    supervisor.send(Configure(config=_serialized_config(), cmd_id=1))
    supervisor.send(Register(cmd_id=2))
    assert _wait_for(lambda: shared_mock_backend.running)

    shared_mock_backend.next_voice_note_id = "backend-vn-loop"
    supervisor.send(
        SendVoiceNote(
            uri="sip:bob@example.com",
            file_path="/tmp/voice-7.wav",
            duration_ms=4200,
            mime_type="audio/wav",
            client_id="client-msg-vn-loop",
            cmd_id=5,
        )
    )
    assert _wait_for(
        lambda: any(
            cmd.startswith("voice-note sip:bob@example.com voice-7.wav 4200 audio/wav")
            for cmd in shared_mock_backend.commands
        )
    )

    # Drive the delivery event from the backend; sidecar must re-key the
    # backend id to the client id main minted, so the on-wire delivery
    # event carries ``client-msg-vn-loop``.
    shared_mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="backend-vn-loop",
            delivery_state=MessageDeliveryState.DELIVERED,
        )
    )
    assert _wait_for(
        lambda: any(
            isinstance(event, MessageDeliveryChanged)
            and event.message_id == "client-msg-vn-loop"
            and event.delivery_state == MessageDeliveryState.DELIVERED.value
            for event in collected_events
        )
    )
