"""Unit tests for the Liblinphone backend abstraction and manager facade."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cffi import FFI

from yoyopy.voip import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    LiblinphoneBackend,
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    MessageReceived,
    MockVoIPBackend,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPManager,
    VoIPMessageRecord,
)
from yoyopy.voip.liblinphone_binding import LiblinphoneBinding


class FakeBinding:
    """Minimal binding double for LiblinphoneBackend tests."""

    def __init__(self) -> None:
        self.started = False
        self.initialized = False
        self.stopped = False
        self.shutdown_called = False
        self.events: list[SimpleNamespace] = []
        self.calls: list[str] = []
        self.start_kwargs: dict[str, object] = {}

    def init(self) -> None:
        self.initialized = True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def start(self, **kwargs) -> None:
        self.start_kwargs = kwargs
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def iterate(self) -> None:
        return

    def poll_event(self):
        if not self.events:
            return None
        return self.events.pop(0)

    def make_call(self, sip_address: str) -> None:
        self.calls.append(f"call {sip_address}")

    def answer_call(self) -> None:
        self.calls.append("answer")

    def reject_call(self) -> None:
        self.calls.append("reject")

    def hangup(self) -> None:
        self.calls.append("hangup")

    def set_muted(self, muted: bool) -> None:
        self.calls.append(f"mute {muted}")

    def send_text_message(self, sip_address: str, text: str) -> str:
        self.calls.append(f"text {sip_address} {text}")
        return "text-1"

    def start_voice_recording(self, file_path: str) -> None:
        self.calls.append(f"record {file_path}")

    def stop_voice_recording(self) -> int:
        self.calls.append("stop-record")
        return 1800

    def cancel_voice_recording(self) -> None:
        self.calls.append("cancel-record")

    def send_voice_note(self, sip_address: str, *, file_path: str, duration_ms: int, mime_type: str) -> str:
        self.calls.append(f"voice {sip_address} {file_path} {duration_ms} {mime_type}")
        return "voice-1"


class FakeConfigManager:
    """Minimal contact lookup double for VoIP manager tests."""

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        self.contacts = contacts or {}

    def get_contact_by_address(self, sip_address: str):
        contact_name = self.contacts.get(sip_address)
        if contact_name is None:
            return None
        return SimpleNamespace(display_name=contact_name)


def build_config() -> VoIPConfig:
    """Create a small test configuration."""

    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_password_ha1="hash",
        sip_identity="sip:alice@sip.example.com",
        message_store_dir="data/test_messages",
        voice_note_store_dir="data/test_voice_notes",
    )


def native_event(**overrides) -> SimpleNamespace:
    """Create one fake native shim event."""

    base = {
        "type": 1,
        "registration_state": 0,
        "call_state": 0,
        "message_kind": 1,
        "message_direction": 1,
        "message_delivery_state": 1,
        "duration_ms": 0,
        "unread": 0,
        "message_id": "",
        "peer_sip_address": "",
        "sender_sip_address": "",
        "recipient_sip_address": "",
        "local_file_path": "",
        "mime_type": "",
        "text": "",
        "reason": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_liblinphone_backend_starts_and_drains_native_events() -> None:
    """LiblinphoneBackend should translate native shim events into typed events."""

    binding = FakeBinding()
    backend = LiblinphoneBackend(build_config(), binding=binding)
    events: list[object] = []
    backend.on_event(events.append)

    assert backend.start()

    binding.events = [
        native_event(type=1, registration_state=2),
        native_event(type=3, peer_sip_address="sip:parent@example.com"),
        native_event(type=2, call_state=6),
        native_event(
            type=5,
            message_id="msg-1",
            peer_sip_address="sip:parent@example.com",
            sender_sip_address="sip:parent@example.com",
            recipient_sip_address="sip:alice@example.com",
            message_kind=2,
            message_direction=1,
            message_delivery_state=4,
            local_file_path="data/voice.wav",
            duration_ms=2100,
            unread=1,
        ),
    ]
    backend.iterate()

    assert isinstance(events[0], RegistrationStateChanged)
    assert events[0].state == RegistrationState.OK
    assert isinstance(events[1], IncomingCallDetected)
    assert isinstance(events[2], CallStateChanged)
    assert events[2].state == CallState.CONNECTED
    assert isinstance(events[3], MessageReceived)
    assert events[3].message.kind == MessageKind.VOICE_NOTE
    assert events[3].message.unread is True
    assert binding.start_kwargs["factory_config_path"].endswith("config\\liblinphone_factory.conf") or binding.start_kwargs[
        "factory_config_path"
    ].endswith("config/liblinphone_factory.conf")


def test_liblinphone_binding_decodes_c_string_arrays() -> None:
    """Fixed-size C char arrays should decode through ffi.string on all platforms."""

    ffi = FFI()
    binding = object.__new__(LiblinphoneBinding)
    binding.ffi = ffi

    buffer = ffi.new("char[]", b"sip:parent@example.com")

    assert binding._decode_c_string(buffer) == "sip:parent@example.com"


def test_voip_manager_applies_backend_events_and_resolves_contact_names() -> None:
    """VoIPManager should stay app-facing while backend events remain typed and low-level."""

    backend = MockVoIPBackend()
    config_manager = FakeConfigManager({"sip:parent@example.com": "Parent"})
    manager = VoIPManager(build_config(), config_manager=config_manager, backend=backend)

    registration_states: list[RegistrationState] = []
    call_states: list[CallState] = []
    incoming_calls: list[tuple[str, str]] = []

    manager.on_registration_change(registration_states.append)
    manager.on_call_state_change(call_states.append)
    manager.on_incoming_call(lambda address, name: incoming_calls.append((address, name)))

    assert manager.start()

    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    backend.emit(CallStateChanged(state=CallState.INCOMING))
    backend.emit(IncomingCallDetected(caller_address="sip:parent@example.com"))

    assert manager.registered
    assert registration_states == [RegistrationState.OK]
    assert call_states == [CallState.INCOMING]
    assert incoming_calls == [("sip:parent@example.com", "Parent")]
    assert manager.get_caller_info()["display_name"] == "Parent"


def test_voip_manager_delegates_outgoing_commands_to_backend() -> None:
    """Outgoing call commands should be delegated through the backend boundary."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))

    assert manager.make_call("sip:bob@example.com", contact_name="Bob")
    assert backend.commands == ["call sip:bob@example.com"]
    assert manager.get_caller_info()["display_name"] == "Bob"


def test_voip_manager_tracks_voice_note_send_and_delivery() -> None:
    """Voice-note record/send flow should update the active draft and summary state."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")

    draft = manager.stop_voice_note_recording()
    assert draft is not None
    assert draft.send_state == "review"

    assert manager.send_active_voice_note()
    assert manager.get_active_voice_note().send_state == "sending"

    backend.emit(
        MessageDeliveryChanged(
            message_id="mock-note-1",
            delivery_state=MessageDeliveryState.SENT,
            local_file_path="data/voice.wav",
        )
    )

    assert manager.get_active_voice_note().send_state == "sent"


def test_voip_manager_surfaces_voice_note_failure_reason() -> None:
    """Voice-note send failures should preserve the backend reason for the UI."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note()

    backend.emit(MessageFailed(message_id="mock-note-1", reason="Upload failed"))

    assert manager.get_active_voice_note().send_state == "failed"
    assert manager.get_active_voice_note().status_text == "Upload failed"


def test_voip_manager_receives_incoming_voice_note_and_updates_summary() -> None:
    """Incoming voice notes should be persisted and exposed through Talk summaries."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    summary_events: list[tuple[int, dict[str, dict[str, str]]]] = []
    manager.on_message_summary_change(lambda unread, summary: summary_events.append((unread, summary)))

    assert manager.start()

    backend.emit(
        MessageReceived(
            message=VoIPMessageRecord(
                id="incoming-1",
                peer_sip_address="sip:mom@example.com",
                sender_sip_address="sip:mom@example.com",
                recipient_sip_address="sip:alice@example.com",
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.INCOMING,
                delivery_state=MessageDeliveryState.DELIVERED,
                created_at="2026-04-06T00:00:00+00:00",
                updated_at="2026-04-06T00:00:00+00:00",
                local_file_path="data/voice_notes/incoming.wav",
                duration_ms=2000,
                unread=True,
            )
        )
    )

    assert manager.unread_voice_note_count() == 1
    latest = manager.latest_voice_note_for_contact("sip:mom@example.com")
    assert latest is not None
    assert latest.local_file_path.endswith("incoming.wav")
    assert summary_events[-1][0] == 1


def test_voip_manager_builds_message_store_under_directory(tmp_path: Path) -> None:
    """The configured message store path should be treated as a directory, not a file."""

    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")

    manager = VoIPManager(config, backend=MockVoIPBackend())

    assert manager._message_store.store_dir == tmp_path / "messages"
    assert manager._message_store.index_file == tmp_path / "messages" / "messages.json"


def test_voip_manager_handles_backend_stop_event() -> None:
    """Unexpected backend stop should clear availability and registration state."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    backend.emit(BackendStopped(reason="native core stopped"))

    assert manager.running is False
    assert manager.registered is False
    assert manager.registration_state == RegistrationState.FAILED
