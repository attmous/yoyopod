"""Unit tests for the VoIP backend abstraction and manager facade."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopy.connectivity import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    LinphonecBackend,
    MockVoIPBackend,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPManager,
)


class FakeConfigManager:
    """Minimal contact lookup double for VoIP manager tests."""

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        self.contacts = contacts or {}

    def get_contact_by_address(self, sip_address: str):
        """Return a fake contact object when the address is known."""

        contact_name = self.contacts.get(sip_address)
        if contact_name is None:
            return None
        return SimpleNamespace(name=contact_name)


class StopEmittingMockVoIPBackend(MockVoIPBackend):
    """Backend double that emits a stop event while the manager is tearing down."""

    def stop(self) -> None:
        self.emit(BackendStopped(reason="process_terminated"))
        super().stop()


def build_config() -> VoIPConfig:
    """Create a small test configuration."""

    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_password_ha1="hash",
        sip_identity="sip:alice@sip.example.com",
        linphonec_path="/usr/bin/linphonec",
    )


def test_linphone_backend_parses_registration_and_incoming_call_events() -> None:
    """The Linphone backend should translate stdout lines into typed events."""

    backend = LinphonecBackend(build_config())

    assert backend._parse_output_line("LinphoneRegistrationOk, reason none") == [
        RegistrationStateChanged(state=RegistrationState.OK)
    ]
    assert backend._parse_output_line("New incoming call from [sip:parent@example.com]") == [
        CallStateChanged(state=CallState.INCOMING),
        IncomingCallDetected(caller_address="sip:parent@example.com"),
    ]


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


def test_voip_manager_resets_call_state_after_release() -> None:
    """Releasing a call should stop timers and clear caller metadata."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    manager.caller_address = "sip:bob@example.com"
    manager.caller_name = "Bob"

    backend.emit(CallStateChanged(state=CallState.CONNECTED))
    assert manager.call_start_time is not None

    backend.emit(CallStateChanged(state=CallState.RELEASED))

    assert manager.call_state == CallState.RELEASED
    assert manager.call_start_time is None
    assert manager.call_duration == 0
    assert manager.get_caller_info()["display_name"] == "Unknown"


def test_voip_manager_stop_can_suppress_teardown_callbacks() -> None:
    """Intentional shutdown should not emit release or availability callbacks."""
    backend = StopEmittingMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    manager.running = True
    manager.registered = True
    manager.call_state = CallState.CONNECTED
    manager.caller_address = "sip:bob@example.com"
    manager.caller_name = "Bob"

    call_states: list[CallState] = []
    availability_events: list[tuple[bool, str]] = []
    manager.on_call_state_change(call_states.append)
    manager.on_availability_change(
        lambda available, reason: availability_events.append((available, reason))
    )

    manager.stop(notify_events=False)

    assert call_states == []
    assert availability_events == []
    assert manager.call_state == CallState.RELEASED
    assert manager.call_start_time is None
    assert manager.get_caller_info()["display_name"] == "Unknown"
