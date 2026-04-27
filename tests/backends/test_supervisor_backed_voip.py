"""Unit + loopback-integration tests for :class:`SupervisorBackedBackend`.

Two layers of coverage:

1. **Unit tests** with a fake supervisor verify the protocol-event ->
   :class:`VoIPEvent` translation and the command dispatch decisions
   without spawning anything.
2. **Loopback integration test** wires a real :class:`SidecarSupervisor`
   in loopback mode against a :class:`MockVoIPBackend` factory and
   exercises the full ``start -> register -> dial -> hangup`` round trip
   end-to-end. This is the harness that proves the protocol/event
   plumbing is wired correctly without paying the spawn cost or
   depending on real liblinphone.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import pytest

from yoyopod.backends.voip.mock_backend import MockVoIPBackend
from yoyopod.backends.voip.supervisor_backed import SupervisorBackedBackend
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged as BackendCallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged as BackendRegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
)
from yoyopod.integrations.call.sidecar_main import run_sidecar
from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CancelVoiceNoteRecording,
    Configure,
    Dial,
    Error as ProtocolError,
    Hangup,
    Hello,
    IncomingCall,
    Log as ProtocolLog,
    MediaStateChanged,
    Pong,
    Ready,
    Register,
    RegistrationStateChanged as ProtocolRegistrationStateChanged,
    SendVoiceNote,
    SetMute,
    StartVoiceNoteRecording,
    StopVoiceNoteRecording,
    Unregister,
    CallStateChanged as ProtocolCallStateChanged,
)
from yoyopod.integrations.call.sidecar_supervisor import SidecarSupervisor

LOOPBACK_BUDGET_SECONDS = 2.0


def _config() -> VoIPConfig:
    return VoIPConfig(sip_server="sip.example.com", sip_identity="sip:alice@example.com")


# ---------------------------------------------------------------------------
# Fake supervisor for unit tests
# ---------------------------------------------------------------------------


class _FakeSupervisor:
    """Minimal stand-in that records sent commands and exposes ``_on_event``."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.started = False
        self.stopped = False
        self.send_should_raise: Exception | None = None
        self.start_should_raise: Exception | None = None
        # Set after attachment by the backend constructor.
        self._on_event: Callable[[Any], None] | None = None

    def start(self) -> None:
        if self.start_should_raise is not None:
            raise self.start_should_raise
        self.started = True

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        self.stopped = True

    def send(self, command: Any) -> None:
        if self.send_should_raise is not None:
            raise self.send_should_raise
        self.sent.append(command)

    # ``_on_event`` mimics the supervisor's internal handler attribute the
    # backend reaches for in __init__; nothing on this fake actually calls it.


# ---------------------------------------------------------------------------
# Unit tests: command dispatch
# ---------------------------------------------------------------------------


def test_start_sends_configure_then_register_in_order() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    assert backend.start() is True
    assert fake.started is True
    assert backend.running is True
    assert [type(cmd).__name__ for cmd in fake.sent] == ["Configure", "Register"]
    cfg_cmd: Configure = fake.sent[0]
    assert cfg_cmd.config == dataclasses.asdict(_config())


def test_start_returns_false_when_supervisor_refuses() -> None:
    fake = _FakeSupervisor()
    fake.start_should_raise = RuntimeError("permanently failed")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    assert backend.start() is False
    assert backend.running is False


def test_start_returns_false_on_spawn_oserror_instead_of_crashing() -> None:
    """Process spawn failures (OSError) must degrade to ``start() == False``.

    Codex review on #393 (P2): the original ``except RuntimeError`` was
    too narrow — ``multiprocessing.Process.start()`` can raise OSError
    (Windows path issues, Linux fork limits, etc.) and that would have
    escaped this method and crashed ``ManagersBoot.init_managers``.
    """

    fake = _FakeSupervisor()
    fake.start_should_raise = OSError("simulated spawn failure")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    assert backend.start() is False
    assert backend.running is False


def test_start_returns_false_when_configure_send_fails() -> None:
    fake = _FakeSupervisor()
    fake.send_should_raise = RuntimeError("not running")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    assert backend.start() is False
    assert backend.running is False


def test_make_call_sends_dial_command() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend.start()
    fake.sent.clear()

    assert backend.make_call("sip:bob@example.com") is True
    assert isinstance(fake.sent[-1], Dial)
    assert fake.sent[-1].uri == "sip:bob@example.com"


def test_answer_call_without_tracked_call_returns_false() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    assert backend.answer_call() is False
    assert not any(type(cmd).__name__ == "Accept" for cmd in fake.sent)


def test_answer_call_with_tracked_call_sends_accept() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-7")
    assert backend.answer_call() is True
    assert isinstance(fake.sent[-1], Accept)
    assert fake.sent[-1].call_id == "call-7"


def test_hangup_with_tracked_call_sends_hangup() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-3")
    assert backend.hangup() is True
    assert isinstance(fake.sent[-1], Hangup)
    assert fake.sent[-1].call_id == "call-3"


def test_mute_unmute_send_correct_set_mute_commands() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-1")

    assert backend.mute() is True
    assert isinstance(fake.sent[-1], SetMute)
    assert fake.sent[-1].on is True

    assert backend.unmute() is True
    assert fake.sent[-1].on is False


def test_iterate_returns_zero_and_get_iterate_metrics_returns_none() -> None:
    backend = SupervisorBackedBackend(_config(), supervisor=_FakeSupervisor())
    assert backend.iterate() == 0
    assert backend.get_iterate_metrics() is None


def test_stop_sends_unregister_and_clears_call_state() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend.start()
    backend._set_current_call_id("call-9")

    backend.stop()

    assert backend.running is False
    assert fake.stopped is True
    # The last command sent before stop() should be Unregister.
    assert any(isinstance(cmd, Unregister) for cmd in fake.sent)
    assert backend._read_current_call_id() is None


# ---------------------------------------------------------------------------
# Unit tests: protocol -> VoIP event translation
# ---------------------------------------------------------------------------


def test_registration_state_event_translates_to_voip_event() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(ProtocolRegistrationStateChanged(state="ok", reason=None))
    assert received and isinstance(received[-1], BackendRegistrationStateChanged)
    assert received[-1].state == RegistrationState.OK


def test_incoming_call_event_tracks_call_id_and_dispatches() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        IncomingCall(call_id="call-42", from_uri="sip:bob@example.com", from_display=None)
    )
    assert backend._read_current_call_id() == "call-42"
    assert any(
        isinstance(event, IncomingCallDetected) and event.caller_address == "sip:bob@example.com"
        for event in received
    )


def test_call_state_terminal_clears_call_id() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-5")

    backend._on_protocol_event(ProtocolCallStateChanged(call_id="call-5", state="released"))
    assert backend._read_current_call_id() is None


def test_call_state_non_terminal_tracks_call_id_for_outgoing_dial() -> None:
    """Outgoing Dial flow: CallStateChanged with non-terminal state should populate _current_call_id."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    backend._on_protocol_event(ProtocolCallStateChanged(call_id="call-99", state="connected"))
    assert backend._read_current_call_id() == "call-99"


def test_protocol_error_with_backend_stopped_dispatches_voip_event() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-stuck")
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolError(code="backend_stopped", message="iterate failed", cmd_id=None)
    )
    assert backend._read_current_call_id() is None
    assert any(
        isinstance(event, BackendStopped) and "iterate failed" in event.reason for event in received
    )


def test_dial_failed_error_drops_call_state_to_error() -> None:
    """``dial_failed`` must surface as CallStateChanged(ERROR) so optimistic UI drops back to idle.

    Codex review on #393 (P1): previously ``make_call`` returned True from
    the optimistic pipe-send, but a sidecar-side rejection (``dial_failed``,
    ``call_in_progress``, ...) only got logged. Without a corrective event
    the UI/runtime stayed in "dialing" state forever.
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolError(code="dial_failed", message="backend.make_call returned False", cmd_id=3)
    )
    assert any(
        isinstance(event, BackendCallStateChanged) and event.state == CallState.ERROR
        for event in received
    )
    assert backend._read_current_call_id() is None


def test_call_in_progress_error_during_active_call_drops_to_error() -> None:
    """``call_in_progress`` while a call id is tracked must trigger the error transition."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._set_current_call_id("call-12")
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(ProtocolError(code="call_in_progress", message="...", cmd_id=4))
    assert any(
        isinstance(event, BackendCallStateChanged) and event.state == CallState.ERROR
        for event in received
    )
    assert backend._read_current_call_id() is None


def test_call_fatal_error_dispatches_even_without_tracked_call() -> None:
    """Call-fatal codes must always dispatch CallStateChanged(ERROR).

    Codex follow-up review on #393 (P1 repeat): the previous guard
    skipped dispatch when ``_current_call_id`` was None for codes other
    than ``dial_failed``. That left the UI stranded if sidecar's
    ``_current_call_id`` was set but main's tracker was not (e.g.,
    back-to-back Dials, or stale ``unknown_call_id`` rejections).
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(ProtocolError(code="call_in_progress", message="busy", cmd_id=1))
    assert any(
        isinstance(event, BackendCallStateChanged) and event.state == CallState.ERROR
        for event in received
    )

    received.clear()
    backend._on_protocol_event(ProtocolError(code="unknown_call_id", message="stale", cmd_id=2))
    assert any(
        isinstance(event, BackendCallStateChanged) and event.state == CallState.ERROR
        for event in received
    )


def test_on_ready_during_initial_start_does_not_resend_configure() -> None:
    """The very first handshake fires on_ready while ``running`` is still False.

    During ``start()`` the supervisor invokes ``on_ready`` between handshake
    success and ``start()``'s own Configure+Register sends. The handler
    must not duplicate the Configure that ``start()`` is about to issue.
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    # Running is False before start(); on_ready should be a no-op.
    assert backend.running is False
    backend._on_supervisor_ready()
    assert fake.sent == []


def test_on_ready_after_restart_resends_configure_and_register() -> None:
    """After a transparent supervisor restart, the new sidecar is blank.

    Codex follow-up review on #393 (P1 new): the previous backend only
    sent Configure + Register inside ``start()``. A pipe-death triggered
    a transparent supervisor restart; the new sidecar came up with no
    backend configured and rejected later commands as ``not_configured``,
    while ``make_call`` still returned True from the optimistic pipe send.

    The fix adds an ``on_ready`` callback the supervisor fires after
    every successful handshake, and the backend re-issues Configure +
    Register against the freshly handshaked sidecar.
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    # Initial start — sends Configure + Register.
    assert backend.start() is True
    initial_sends = list(fake.sent)
    assert [type(cmd).__name__ for cmd in initial_sends] == ["Configure", "Register"]

    # Track a call to verify the ready handler clears stale state.
    backend._set_current_call_id("call-77")
    fake.sent.clear()
    received.clear()

    # Simulate the supervisor calling on_ready after a transparent restart.
    backend._on_supervisor_ready()

    # Configure + Register were re-sent against the new sidecar.
    assert [type(cmd).__name__ for cmd in fake.sent] == ["Configure", "Register"]
    # The stale call id was cleared so a fresh dial is not blocked.
    assert backend._read_current_call_id() is None
    # Listeners got a registration-progress event so the UI knows we're
    # re-registering against the fresh sidecar.
    assert any(
        isinstance(event, BackendRegistrationStateChanged)
        and event.state == RegistrationState.PROGRESS
        for event in received
    )


def test_on_ready_after_restart_logs_when_resend_fails() -> None:
    """If the supervisor cannot accept the re-Configure, the backend logs and continues."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend.start()
    fake.send_should_raise = RuntimeError("sidecar pipe closed mid-restart")
    fake.sent.clear()

    # Should not raise — error is logged and swallowed.
    backend._on_supervisor_ready()


def test_register_failed_error_dispatches_registration_failed() -> None:
    """``register_failed`` must surface as RegistrationStateChanged(FAILED)."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(ProtocolError(code="register_failed", message="bad creds", cmd_id=2))
    assert any(
        isinstance(event, BackendRegistrationStateChanged)
        and event.state == RegistrationState.FAILED
        for event in received
    )


def test_unrelated_error_codes_do_not_dispatch_voip_event() -> None:
    """Errors that are neither call-fatal nor registration-fatal stay log-only."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolError(code="invalid_config", message="bogus field", cmd_id=1)
    )
    assert received == []


# ---------------------------------------------------------------------------
# Messaging (Phase 2B.4)
# ---------------------------------------------------------------------------


def test_send_text_message_returns_client_id_and_sends_command() -> None:
    """Phase 2B.4: ``send_text_message`` mints a client_id and ships SendTextMessage."""

    from yoyopod.integrations.call.sidecar_protocol import SendTextMessage

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    result = backend.send_text_message("sip:bob@example.com", "hi")

    assert result is not None
    assert result.startswith("client-msg-")
    assert isinstance(fake.sent[-1], SendTextMessage)
    assert fake.sent[-1].uri == "sip:bob@example.com"
    assert fake.sent[-1].text == "hi"
    assert fake.sent[-1].client_id == result


def test_send_text_message_returns_none_when_supervisor_send_fails() -> None:
    fake = _FakeSupervisor()
    fake.send_should_raise = RuntimeError("sidecar pipe closed")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    assert backend.send_text_message("sip:bob@example.com", "hi") is None


def test_protocol_message_received_translates_to_backend_message_received() -> None:
    """``MessageReceived`` from the wire reconstructs a ``VoIPMessageRecord``."""

    from yoyopod.integrations.call.models import (
        MessageDeliveryState,
        MessageDirection,
        MessageKind,
        MessageReceived as BackendMessageReceived,
    )
    from yoyopod.integrations.call.sidecar_protocol import (
        MessageReceived as ProtocolMessageReceived,
    )

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolMessageReceived(
            message_id="msg-42",
            peer_sip_address="sip:bob@example.com",
            sender_sip_address="sip:bob@example.com",
            recipient_sip_address="sip:alice@example.com",
            kind="text",
            direction="incoming",
            delivery_state="delivered",
            created_at="2026-04-28T10:00:00+00:00",
            updated_at="2026-04-28T10:00:00+00:00",
            text="hello",
            unread=True,
            display_name="Bob",
        )
    )
    matches = [event for event in received if isinstance(event, BackendMessageReceived)]
    assert matches, received
    record = matches[-1].message
    assert record.id == "msg-42"
    assert record.kind == MessageKind.TEXT
    assert record.direction == MessageDirection.INCOMING
    assert record.delivery_state == MessageDeliveryState.DELIVERED
    assert record.text == "hello"
    assert record.unread is True


def test_protocol_message_received_with_unknown_enum_drops_silently() -> None:
    from yoyopod.integrations.call.sidecar_protocol import (
        MessageReceived as ProtocolMessageReceived,
    )

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolMessageReceived(
            message_id="msg-43",
            peer_sip_address="sip:bob",
            sender_sip_address="sip:bob",
            recipient_sip_address="sip:alice",
            kind="not-a-real-kind",
            direction="incoming",
            delivery_state="delivered",
            created_at="x",
            updated_at="x",
        )
    )
    assert received == []


def test_protocol_message_delivery_changed_translates() -> None:
    from yoyopod.integrations.call.models import (
        MessageDeliveryChanged as BackendMessageDeliveryChanged,
        MessageDeliveryState,
    )
    from yoyopod.integrations.call.sidecar_protocol import (
        MessageDeliveryChanged as ProtocolMessageDeliveryChanged,
    )

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolMessageDeliveryChanged(
            message_id="client-msg-x",
            delivery_state="delivered",
            local_file_path="",
            error="",
        )
    )
    matches = [
        event for event in received if isinstance(event, BackendMessageDeliveryChanged)
    ]
    assert matches and matches[-1].message_id == "client-msg-x"
    assert matches[-1].delivery_state == MessageDeliveryState.DELIVERED


def test_protocol_message_failed_translates() -> None:
    from yoyopod.integrations.call.models import (
        MessageFailed as BackendMessageFailed,
    )
    from yoyopod.integrations.call.sidecar_protocol import (
        MessageFailed as ProtocolMessageFailed,
    )

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(
        ProtocolMessageFailed(message_id="client-msg-y", reason="peer offline")
    )
    matches = [event for event in received if isinstance(event, BackendMessageFailed)]
    assert matches and matches[-1].message_id == "client-msg-y"
    assert matches[-1].reason == "peer offline"


def test_protocol_only_events_are_ignored() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    for event in (
        Hello(version=1),
        Ready(),
        Pong(cmd_id=1),
        MediaStateChanged(call_id="x", mic_muted=False, speaker_volume=1.0),
        ProtocolLog(level="DEBUG", message="hi"),
    ):
        backend._on_protocol_event(event)
    assert received == []


def test_unknown_registration_state_logs_and_drops() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    received: list[VoIPEvent] = []
    backend.on_event(received.append)

    backend._on_protocol_event(ProtocolRegistrationStateChanged(state="bogus", reason=None))
    assert received == []


# ---------------------------------------------------------------------------
# Voice notes (Phase 2B.4b)
# ---------------------------------------------------------------------------


def test_start_voice_note_recording_sends_command_and_records_start_time() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    assert backend.start_voice_note_recording("/tmp/voice-1.wav") is True
    assert isinstance(fake.sent[-1], StartVoiceNoteRecording)
    assert fake.sent[-1].file_path == "/tmp/voice-1.wav"
    assert backend._recording_start_monotonic is not None


def test_start_voice_note_recording_returns_false_when_supervisor_send_fails() -> None:
    fake = _FakeSupervisor()
    fake.send_should_raise = RuntimeError("sidecar pipe closed")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    assert backend.start_voice_note_recording("/tmp/voice-1.wav") is False
    # Start time must not be recorded if the command did not even ship.
    assert backend._recording_start_monotonic is None


def test_stop_voice_note_recording_returns_optimistic_duration() -> None:
    """Duration is computed from monotonic-elapsed since start, in milliseconds."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    # Plant a known start time roughly 250ms in the past.
    fake_start = time.monotonic() - 0.25
    backend._recording_start_monotonic = fake_start

    duration = backend.stop_voice_note_recording()
    assert duration is not None
    # Small tolerance under 250ms to absorb floating-point rounding in int().
    assert duration >= 245
    # Generous upper bound for slow CI; 250ms baseline + any test scheduling jitter.
    assert duration < 5000
    assert isinstance(fake.sent[-1], StopVoiceNoteRecording)
    # Start time was consumed.
    assert backend._recording_start_monotonic is None


def test_stop_voice_note_recording_returns_none_when_no_start() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    assert backend.stop_voice_note_recording() is None
    # Nothing to stop -> no command shipped.
    assert not any(isinstance(cmd, StopVoiceNoteRecording) for cmd in fake.sent)


def test_stop_voice_note_recording_still_returns_duration_when_send_fails() -> None:
    """If the pipe drops between start and stop we still surface the optimistic duration.

    The recording exists locally on the sidecar's filesystem if it was
    actually started; the user already saw "recording" feedback. Returning
    a duration here lets the manager render the review screen / "too long"
    UX even when the cancel command itself cannot land.
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._recording_start_monotonic = time.monotonic() - 0.1

    fake.send_should_raise = RuntimeError("sidecar pipe closed mid-recording")
    duration = backend.stop_voice_note_recording()

    assert duration is not None
    # Floating-point rounding in ``int()`` can shave off a millisecond, so
    # leave a small tolerance below the 100ms seed.
    assert duration >= 95
    # And the start time still gets consumed so a follow-up stop returns None.
    assert backend._recording_start_monotonic is None
    assert backend.stop_voice_note_recording() is None


def test_cancel_voice_note_recording_clears_start_time_and_sends_command() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._recording_start_monotonic = time.monotonic()

    assert backend.cancel_voice_note_recording() is True
    assert backend._recording_start_monotonic is None
    assert isinstance(fake.sent[-1], CancelVoiceNoteRecording)


def test_cancel_voice_note_recording_returns_false_when_send_fails() -> None:
    fake = _FakeSupervisor()
    fake.send_should_raise = RuntimeError("sidecar pipe closed")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._recording_start_monotonic = time.monotonic()

    assert backend.cancel_voice_note_recording() is False
    # Local state is still cleared so a subsequent stop does not return a stale duration.
    assert backend._recording_start_monotonic is None


def test_send_voice_note_returns_client_id_and_sends_command() -> None:
    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    result = backend.send_voice_note(
        "sip:bob@example.com",
        file_path="/tmp/voice-1.wav",
        duration_ms=4200,
        mime_type="audio/wav",
    )
    assert result is not None
    assert result.startswith("client-msg-")
    assert isinstance(fake.sent[-1], SendVoiceNote)
    assert fake.sent[-1].uri == "sip:bob@example.com"
    assert fake.sent[-1].file_path == "/tmp/voice-1.wav"
    assert fake.sent[-1].duration_ms == 4200
    assert fake.sent[-1].mime_type == "audio/wav"
    assert fake.sent[-1].client_id == result


def test_send_voice_note_returns_none_when_supervisor_send_fails() -> None:
    fake = _FakeSupervisor()
    fake.send_should_raise = RuntimeError("sidecar pipe closed")
    backend = SupervisorBackedBackend(_config(), supervisor=fake)

    result = backend.send_voice_note(
        "sip:bob@example.com",
        file_path="/tmp/voice-1.wav",
        duration_ms=4200,
        mime_type="audio/wav",
    )
    assert result is None


def test_stop_clears_recording_state() -> None:
    """``stop()`` must reset any in-flight recording start time."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend.start()
    backend._recording_start_monotonic = time.monotonic()

    backend.stop()
    assert backend._recording_start_monotonic is None


def test_on_supervisor_ready_clears_recording_state_after_restart() -> None:
    """A transparent supervisor restart drops any in-flight recording.

    The fresh sidecar has no idea about the recording the previous
    sidecar was capturing, so retaining the start time would let
    ``stop_voice_note_recording`` return a duration measured against
    a recording that no longer exists. Reset on restart.
    """

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend.start()
    backend._recording_start_monotonic = time.monotonic()
    fake.sent.clear()

    backend._on_supervisor_ready()
    assert backend._recording_start_monotonic is None


def test_backend_stopped_error_clears_recording_state() -> None:
    """If the sidecar's backend dies mid-recording, drop the local start time."""

    fake = _FakeSupervisor()
    backend = SupervisorBackedBackend(_config(), supervisor=fake)
    backend._recording_start_monotonic = time.monotonic()

    backend._on_protocol_event(
        ProtocolError(code="backend_stopped", message="iterate failed", cmd_id=None)
    )
    assert backend._recording_start_monotonic is None


# ---------------------------------------------------------------------------
# Loopback integration test
# ---------------------------------------------------------------------------


# Module-level so the loopback-mode sidecar target can resolve the shared
# mock backend (loopback runs in-process so closures would also work, but
# keeping symmetry with the spawn case is cheap).
_TEST_BACKEND_HANDLE: dict[str, MockVoIPBackend] = {}


def _shared_mock_backend_factory(_config: VoIPConfig) -> MockVoIPBackend:
    return _TEST_BACKEND_HANDLE["backend"]


def _sidecar_target(conn: Connection) -> None:
    run_sidecar(conn, backend_factory=_shared_mock_backend_factory)


def _wait_for(pred, *, timeout: float = LOOPBACK_BUDGET_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_loopback_end_to_end_call_flow() -> None:
    """End-to-end: backend.start -> sidecar Configure+Register, dial, accept, hangup."""

    backend_inside_sidecar = MockVoIPBackend()
    _TEST_BACKEND_HANDLE["backend"] = backend_inside_sidecar
    try:
        supervisor = SidecarSupervisor(
            on_event=lambda _event: None,  # backend overrides this in __init__
            sidecar_target=_sidecar_target,
            use_loopback=True,
            handshake_timeout_seconds=LOOPBACK_BUDGET_SECONDS,
        )
        backend = SupervisorBackedBackend(_config(), supervisor=supervisor)
        received: list[VoIPEvent] = []
        backend.on_event(received.append)

        try:
            assert backend.start() is True
            assert _wait_for(lambda: backend_inside_sidecar.running)

            # Drive a registration state change inside the sidecar — should
            # surface as a VoIPEvent on the main side.
            backend_inside_sidecar.emit(BackendRegistrationStateChanged(state=RegistrationState.OK))
            assert _wait_for(
                lambda: any(
                    isinstance(event, BackendRegistrationStateChanged)
                    and event.state == RegistrationState.OK
                    for event in received
                )
            )

            # Drive an incoming-call flow.
            backend_inside_sidecar.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
            assert _wait_for(
                lambda: any(isinstance(event, IncomingCallDetected) for event in received)
            )
            assert _wait_for(lambda: backend._read_current_call_id() is not None)

            assert backend.answer_call() is True
            assert _wait_for(lambda: "answer" in backend_inside_sidecar.commands)

            assert backend.hangup() is True
            assert _wait_for(lambda: "terminate" in backend_inside_sidecar.commands)
        finally:
            backend.stop()
    finally:
        _TEST_BACKEND_HANDLE.clear()
