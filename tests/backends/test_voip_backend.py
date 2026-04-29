"""Unit tests for the Liblinphone backend abstraction and manager facade."""

from __future__ import annotations

import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from cffi import FFI

from yoyopod.backends.voip import LiblinphoneBackend, LiblinphoneBinding, MockVoIPBackend
from yoyopod.integrations.call.models import (
    BackendRecovered,
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageFailed,
    MessageKind,
    MessageReceived,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
    VoIPLifecycleSnapshot,
    VoIPMessageSnapshot,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
    VoIPRuntimeSnapshotChanged,
    VoIPVoiceNoteSnapshot,
)
from yoyopod.integrations.call import VoIPManager


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

    def send_voice_note(
        self, sip_address: str, *, file_path: str, duration_ms: int, mime_type: str
    ) -> str:
        self.calls.append(f"voice {sip_address} {file_path} {duration_ms} {mime_type}")
        return "voice-1"


class FakePeopleDirectory:
    """Minimal people-directory double for VoIP manager tests."""

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        self.contacts = contacts or {}

    def get_contact_by_address(self, sip_address: str):
        contact_name = self.contacts.get(sip_address)
        if contact_name is None:
            return None
        return SimpleNamespace(display_name=contact_name)


class BackgroundIterateMockVoIPBackend(MockVoIPBackend):
    """Mock backend that cooperates with the manager's real background iterate thread."""

    def __init__(
        self,
        *,
        event_to_emit: VoIPEvent | None = None,
        metrics_error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.event_to_emit = event_to_emit
        self.metrics_error = metrics_error
        self.iterate_calls = 0
        self.iterate_started = threading.Event()

    def iterate(self) -> int:
        self.iterate_started.set()
        self.iterate_calls += 1
        if self.iterate_calls == 1 and self.event_to_emit is not None:
            self.emit(self.event_to_emit)
            return 1
        return 0

    def get_iterate_metrics(self) -> object | None:
        if self.metrics_error is not None:
            raise self.metrics_error
        return SimpleNamespace(
            native_duration_seconds=0.0,
            event_drain_duration_seconds=0.0,
        )


class SnapshotOwnedMockVoIPBackend(MockVoIPBackend):
    """Mock backend that marks runtime facts as Rust-snapshot owned."""

    def __init__(self) -> None:
        super().__init__()
        self.runtime_snapshot: VoIPRuntimeSnapshot | None = None

    def get_runtime_snapshot(self) -> VoIPRuntimeSnapshot | None:
        return self.runtime_snapshot


def build_config(storage_root: Path | None = None) -> VoIPConfig:
    """Create a small test configuration with isolated on-disk storage."""

    root = storage_root or Path(tempfile.mkdtemp(prefix="yoyopod-voip-tests-"))

    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_password_ha1="hash",
        sip_identity="sip:alice@sip.example.com",
        file_transfer_server_url="https://transfer.example.com",
        message_store_dir=str(root / "messages"),
        voice_note_store_dir=str(root / "voice_notes"),
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


def wait_for_condition(predicate: Callable[[], bool], *, timeout_seconds: float = 1.0) -> bool:
    """Poll a test condition until it becomes true or the timeout expires."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


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
    drained_events = backend.iterate()

    assert isinstance(events[0], RegistrationStateChanged)
    assert events[0].state == RegistrationState.OK
    assert isinstance(events[1], IncomingCallDetected)
    assert isinstance(events[2], CallStateChanged)
    assert events[2].state == CallState.CONNECTED
    assert isinstance(events[3], MessageReceived)
    assert events[3].message.kind == MessageKind.VOICE_NOTE
    assert events[3].message.unread is True
    assert drained_events == 4
    assert binding.start_kwargs["conference_factory_uri"] == ""
    assert binding.start_kwargs["file_transfer_server_url"] == "https://transfer.example.com"
    assert binding.start_kwargs["lime_server_url"] == ""
    assert binding.start_kwargs["mic_gain"] == 0
    assert binding.start_kwargs["output_volume"] == 100
    assert (
        binding.start_kwargs["factory_config_path"]
        .replace("\\", "/")
        .endswith("config/communication/integrations/liblinphone_factory.conf")
    )


def test_voip_manager_skips_backend_start_when_identity_missing() -> None:
    """VoIPManager should fail fast before touching the backend when SIP identity is absent."""

    binding = FakeBinding()
    config = build_config()
    config.sip_identity = ""
    manager = VoIPManager(config, backend=LiblinphoneBackend(config, binding=binding))

    assert manager.start() is False
    assert binding.initialized is False
    assert binding.started is False
    assert manager.registration_state == RegistrationState.FAILED


def test_liblinphone_backend_infers_linphone_hosted_servers() -> None:
    """Hosted Linphone accounts should inherit the same messaging defaults as the official client."""

    binding = FakeBinding()
    config = build_config()
    config.sip_server = "sip.linphone.org"
    config.file_transfer_server_url = ""
    config.lime_server_url = ""
    backend = LiblinphoneBackend(config, binding=binding)

    assert backend.start()
    assert (
        binding.start_kwargs["conference_factory_uri"] == "sip:conference-factory@sip.linphone.org"
    )
    assert binding.start_kwargs["file_transfer_server_url"] == "https://files.linphone.org/lft.php"
    assert (
        binding.start_kwargs["lime_server_url"]
        == "https://lime.linphone.org/lime-server/lime-server.php"
    )


def test_liblinphone_backend_records_native_iterate_timings(monkeypatch) -> None:
    """Keep-alive diagnostics should separate native iterate time from event-drain time."""

    binding = FakeBinding()
    binding.events = [native_event(type=1, registration_state=2)]
    backend = LiblinphoneBackend(build_config(), binding=binding)
    warnings: list[tuple[object, ...]] = []
    monotonic_values = iter([10.0, 10.0, 10.18, 10.18, 10.29, 10.31])

    monkeypatch.setattr(
        "yoyopod.backends.voip.liblinphone.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        "yoyopod.backends.voip.liblinphone.logger.warning",
        lambda *args: warnings.append(args),
    )

    assert backend.start()

    drained_events = backend.iterate()
    metrics = backend.get_iterate_metrics()

    assert drained_events == 1
    assert metrics is not None
    assert metrics.native_duration_seconds == pytest.approx(0.18)
    assert metrics.event_drain_duration_seconds == pytest.approx(0.11)
    assert metrics.total_duration_seconds == pytest.approx(0.31)
    assert metrics.drained_events == 1
    assert warnings[0][0].startswith("VoIP keep-alive native iterate slow:")
    assert warnings[1][0].startswith("VoIP keep-alive event drain slow:")


def test_liblinphone_backend_uses_shared_output_volume_and_capture_only_alsa(monkeypatch) -> None:
    """VoIP startup should inherit app output volume but only touch capture-path mixers."""

    commands: list[str] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess[str]:
        if command == ["arecord", "-l"]:
            stdout = (
                "**** List of CAPTURE Hardware Devices ****\n"
                "card 0: wm8960soundcard [wm8960-soundcard], device 0: foo [bar]\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("yoyopod.backends.voip.liblinphone.subprocess.run", fake_run)

    binding = FakeBinding()
    config = build_config()
    config.output_volume = 73
    backend = LiblinphoneBackend(config, binding=binding)

    assert backend.start()
    assert binding.start_kwargs["output_volume"] == 73
    assert all("Speaker" not in command for command in commands)
    assert all("Headphone" not in command for command in commands)
    assert all("Playback" not in command for command in commands)
    assert any("Capture" in command for command in commands)
    assert any("ADC PCM" in command for command in commands)
    assert any("sset 'Capture' 26" in command for command in commands)
    assert all("-c 0" in command for command in commands)


def test_liblinphone_backend_matches_wm8960_card_from_capture_device(monkeypatch) -> None:
    """The ALSA capture mixer should target the card matching the configured device name."""

    commands: list[str] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess[str]:
        if command == ["arecord", "-l"]:
            stdout = (
                "**** List of CAPTURE Hardware Devices ****\n"
                "card 2: other [Other Card], device 0: foo [bar]\n"
                "card 0: wm8960soundcard [wm8960-soundcard], device 0: foo [bar]\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("yoyopod.backends.voip.liblinphone.subprocess.run", fake_run)

    backend = LiblinphoneBackend(build_config(), binding=FakeBinding())

    backend._configure_alsa_capture_path()

    assert commands
    assert all("-c 0" in command for command in commands)


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
    people_directory = FakePeopleDirectory({"sip:parent@example.com": "Parent"})
    manager = VoIPManager(build_config(), people_directory=people_directory, backend=backend)

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


def test_voip_manager_mirrors_rust_runtime_snapshot_without_duplicate_callbacks() -> None:
    """Rust-owned runtime snapshots should become the app-facing live VoIP state."""

    backend = MockVoIPBackend()
    people_directory = FakePeopleDirectory({"sip:bob@example.com": "Bob"})
    manager = VoIPManager(build_config(), people_directory=people_directory, backend=backend)
    registration_states: list[RegistrationState] = []
    call_states: list[CallState] = []
    manager.on_registration_change(registration_states.append)
    manager.on_call_state_change(call_states.append)

    assert manager.start()
    snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.STREAMS_RUNNING,
        active_call_id="call-1",
        active_call_peer="sip:bob@example.com",
        pending_outbound_messages=1,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )

    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))

    assert manager.running is True
    assert manager.registered is True
    assert manager.registration_state == RegistrationState.OK
    assert manager.call_state == CallState.STREAMS_RUNNING
    assert manager.current_call_id == "call-1"
    assert manager.caller_address == "sip:bob@example.com"
    assert manager.get_caller_info()["display_name"] == "Bob"
    assert registration_states == [RegistrationState.OK]
    assert call_states == [CallState.STREAMS_RUNNING]


def test_voip_manager_delegates_outgoing_commands_to_backend() -> None:
    """Outgoing commands should not invent local call phases before backend events arrive."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    call_states: list[CallState] = []

    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    manager.on_call_state_change(call_states.append)

    assert manager.make_call("sip:bob@example.com", contact_name="Bob")
    assert backend.commands == ["call sip:bob@example.com"]
    assert call_states == []
    assert manager.call_state == CallState.IDLE
    assert manager.get_caller_info()["display_name"] == "Bob"


def test_voip_manager_waits_for_rust_snapshot_before_call_identity() -> None:
    """Rust-host mode should not invent active-call identity before Rust reports it."""

    backend = SnapshotOwnedMockVoIPBackend()
    people_directory = FakePeopleDirectory({"sip:bob@example.com": "Bob"})
    manager = VoIPManager(build_config(), people_directory=people_directory, backend=backend)

    assert manager.start()
    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))

    assert manager.make_call("sip:bob@example.com", contact_name="Bob")
    assert backend.commands == ["call sip:bob@example.com"]
    assert manager.caller_address is None
    assert manager.caller_name is None
    assert manager.get_caller_info()["display_name"] == "Unknown"

    snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.OUTGOING,
        active_call_id="call-1",
        active_call_peer="sip:bob@example.com",
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )
    backend.runtime_snapshot = snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))

    assert manager.current_call_id == "call-1"
    assert manager.caller_address == "sip:bob@example.com"
    assert manager.get_caller_info()["display_name"] == "Bob"


def test_voip_manager_waits_for_rust_snapshot_before_mute_state() -> None:
    """Rust-host mode should mirror mute state only after Rust snapshots report it."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.is_muted is False

    assert manager.mute()
    assert backend.commands == ["mute"]
    assert manager.is_muted is False

    muted_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        muted=True,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )
    backend.runtime_snapshot = muted_snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=muted_snapshot))

    assert manager.is_muted is True

    assert manager.unmute()
    assert backend.commands == ["mute", "unmute"]
    assert manager.is_muted is True

    unmuted_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        muted=False,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )
    backend.runtime_snapshot = unmuted_snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=unmuted_snapshot))

    assert manager.is_muted is False


def test_voip_manager_publishes_runtime_snapshot_callbacks_without_call_state_change() -> None:
    """Rust snapshots should surface facts that do not emit call-state callbacks."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    snapshots: list[VoIPRuntimeSnapshot] = []
    call_states: list[CallState] = []
    manager.on_runtime_snapshot_change(snapshots.append)
    manager.on_call_state_change(call_states.append)

    assert manager.start()
    muted_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        muted=True,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )

    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=muted_snapshot))

    assert snapshots == [muted_snapshot]
    assert call_states == []
    assert manager.is_muted is True


def test_voip_manager_derives_availability_from_rust_lifecycle_snapshots() -> None:
    """Rust lifecycle snapshots should drive recovery availability without side events."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    availability_changes: list[tuple[bool, str, RegistrationState]] = []
    manager.on_availability_change(
        lambda available, reason, registration_state: availability_changes.append(
            (available, reason, registration_state)
        )
    )

    assert manager.start()
    availability_changes.clear()

    failed_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=False,
        registration_state=RegistrationState.FAILED,
        lifecycle=VoIPLifecycleSnapshot(
            state="failed",
            reason="process_exited",
            backend_available=False,
        ),
    )
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=failed_snapshot))

    assert manager.running is False
    assert manager.registered is False
    assert availability_changes == [
        (False, "process_exited", RegistrationState.FAILED),
    ]

    recovered_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
    )
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=recovered_snapshot))

    assert manager.running is True
    assert manager.registered is True
    assert availability_changes[-1] == (True, "registered", RegistrationState.OK)


def test_voip_manager_starts_timer_on_streams_running_without_connected() -> None:
    """Streams-running callbacks should start live duration tracking on their own."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    started: list[bool] = []
    manager._start_call_timer = lambda: started.append(True)  # type: ignore[method-assign]

    assert manager.start()

    backend.emit(CallStateChanged(state=CallState.STREAMS_RUNNING))

    assert started == [True]


def test_voip_manager_derives_live_call_duration_without_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Call duration should come from the current clock and stored start time."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    now = 1_000.9
    monkeypatch.setattr(time, "time", lambda: now)
    manager.call_start_time = 940.0
    manager.call_state = CallState.CONNECTED

    assert not hasattr(manager, "duration_thread")
    assert not hasattr(VoIPManager, "_track_duration")
    assert manager.get_call_duration() == 60


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


def test_voip_manager_routes_rust_runtime_snapshot_to_voice_note_and_message_mirrors() -> None:
    """VoIPManager should fan Rust snapshots into its compatibility services."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note()
    draft = manager.get_active_voice_note()
    assert draft is not None

    backend.emit(
        VoIPRuntimeSnapshotChanged(
            snapshot=VoIPRuntimeSnapshot(
                voice_note=VoIPVoiceNoteSnapshot(
                    state="sent",
                    file_path=draft.file_path,
                    duration_ms=draft.duration_ms,
                    mime_type=draft.mime_type,
                    message_id=draft.message_id,
                ),
                last_message=VoIPMessageSnapshot(
                    message_id=draft.message_id,
                    kind=MessageKind.VOICE_NOTE,
                    direction=MessageDirection.OUTGOING,
                    delivery_state=MessageDeliveryState.DELIVERED,
                    local_file_path=draft.file_path,
                ),
            )
        )
    )

    active = manager.get_active_voice_note()
    assert active is not None
    assert active.send_state == "sent"
    stored = manager.latest_voice_note_for_contact("sip:mom@example.com")
    assert stored is not None
    assert stored.delivery_state == MessageDeliveryState.DELIVERED


def test_voip_manager_fails_voice_note_send_without_transfer_server() -> None:
    """Voice-note sending should fail immediately when file transfer is not configured."""

    backend = MockVoIPBackend()
    config = build_config()
    config.file_transfer_server_url = ""
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None

    assert manager.send_active_voice_note() is False
    assert manager.get_active_voice_note().send_state == "failed"
    assert manager.get_active_voice_note().status_text == "Voice notes unavailable"


def test_voip_manager_allows_voice_note_send_for_hosted_linphone_account_without_explicit_url() -> (
    None
):
    """Hosted Linphone accounts should use inferred upload settings instead of failing immediately."""

    backend = MockVoIPBackend()
    config = build_config()
    config.sip_server = "sip.linphone.org"
    config.file_transfer_server_url = ""
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True
    assert manager.get_active_voice_note().send_state == "sending"


def test_voip_manager_times_out_stuck_voice_note_send() -> None:
    """Voice-note sends should not remain in sending forever without delivery callbacks."""

    backend = MockVoIPBackend()
    config = build_config()
    config.file_transfer_server_url = "https://transfer.example.com"
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True

    manager.get_active_voice_note().send_started_at = time.monotonic() - 30.0
    drained_events = manager.iterate()

    assert manager.get_active_voice_note().send_state == "failed"
    assert manager.get_active_voice_note().status_text == "Send timed out"
    assert drained_events == 0


def test_voip_manager_rejects_voice_note_recording_during_active_call() -> None:
    """Voice-note recording should be blocked while a call is active."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    manager.call_state = CallState.CONNECTED

    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom") is False
    assert manager.get_active_voice_note() is None


def test_voip_manager_stops_voice_note_playback_when_call_enters_active_state() -> None:
    """Incoming or active call phases should stop any local voice-note playback."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    stopped: list[str] = []
    manager._voice_note_service.stop_voice_note_playback = lambda: stopped.append("stop")

    manager._update_call_state(CallState.INCOMING)

    assert stopped == ["stop"]


def test_voip_manager_queues_backend_events_back_to_main_thread(tmp_path: Path) -> None:
    """App-mode VoIP events should be marshaled back through the main-thread scheduler."""

    backend = MockVoIPBackend()
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    config.voice_note_store_dir = str(tmp_path / "voice_notes")
    queued_callbacks: list[Callable[[], None]] = []
    manager = VoIPManager(
        config,
        backend=backend,
        event_scheduler=queued_callbacks.append,
        background_iterate_enabled=True,
    )

    backend.emit(CallStateChanged(state=CallState.CONNECTED))

    assert manager.background_iterate_enabled is True
    assert manager.call_state == CallState.IDLE
    assert len(queued_callbacks) == 1

    queued_callbacks.pop()()

    assert manager.call_state == CallState.CONNECTED


def test_voip_manager_background_iterate_thread_queues_events_and_stops_cleanly(
    tmp_path: Path,
) -> None:
    """The dedicated iterate worker should queue callbacks back to the coordinator thread."""

    backend = BackgroundIterateMockVoIPBackend(
        event_to_emit=CallStateChanged(state=CallState.CONNECTED)
    )
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    config.voice_note_store_dir = str(tmp_path / "voice_notes")
    scheduled_callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
    manager = VoIPManager(
        config,
        backend=backend,
        event_scheduler=scheduled_callbacks.put,
        background_iterate_enabled=True,
    )

    assert manager.start()
    try:
        manager.ensure_background_iterate_running()

        assert wait_for_condition(backend.iterate_started.is_set)
        assert manager._iterate_thread is not None
        worker_thread = manager._iterate_thread

        assert wait_for_condition(lambda: not scheduled_callbacks.empty())
        assert manager.call_state == CallState.IDLE

        scheduled_callbacks.get_nowait()()

        assert manager.call_state == CallState.CONNECTED
        assert backend.iterate_calls >= 1

        manager._stop_background_iterate_loop()

        assert manager._iterate_thread is None
        assert worker_thread is not None
        assert worker_thread.is_alive() is False
    finally:
        manager.stop(notify_events=False)


def test_voip_manager_background_iterate_worker_surfaces_unexpected_failure(
    tmp_path: Path,
) -> None:
    """Unexpected worker-loop failures should be converted into a backend-stopped event."""

    backend = BackgroundIterateMockVoIPBackend(metrics_error=RuntimeError("metrics exploded"))
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    config.voice_note_store_dir = str(tmp_path / "voice_notes")
    scheduled_callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
    availability_changes: list[tuple[bool, str, RegistrationState]] = []
    manager = VoIPManager(
        config,
        backend=backend,
        event_scheduler=scheduled_callbacks.put,
        background_iterate_enabled=True,
    )
    manager.on_availability_change(
        lambda available, reason, registration_state: availability_changes.append(
            (available, reason, registration_state)
        )
    )

    assert manager.start()
    try:
        manager.ensure_background_iterate_running()

        assert wait_for_condition(backend.iterate_started.is_set)
        assert wait_for_condition(lambda: not scheduled_callbacks.empty())

        scheduled_callbacks.get_nowait()()

        assert manager.running is False
        assert manager.registered is False
        assert manager.registration_state == RegistrationState.FAILED
        assert availability_changes[-1] == (
            False,
            "metrics exploded",
            RegistrationState.FAILED,
        )

        worker_thread = manager._iterate_thread
        assert worker_thread is not None
        assert wait_for_condition(lambda: worker_thread.is_alive() is False)

        manager._stop_background_iterate_loop()

        assert manager._iterate_thread is None
    finally:
        manager.stop(notify_events=False)


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


def test_voip_manager_receives_incoming_voice_note_and_updates_summary(tmp_path: Path) -> None:
    """Incoming voice notes should be persisted and exposed through Talk summaries."""

    backend = MockVoIPBackend()
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    manager = VoIPManager(config, backend=backend)
    summary_events: list[tuple[int, dict[str, dict[str, str]]]] = []
    manager.on_message_summary_change(
        lambda unread, summary: summary_events.append((unread, summary))
    )

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
    assert manager.unread_voice_note_counts_by_contact() == {"sip:mom@example.com": 1}
    latest = manager.latest_voice_note_for_contact("sip:mom@example.com")
    assert latest is not None
    assert latest.local_file_path.endswith("incoming.wav")
    assert summary_events[-1][0] == 1


def test_voip_manager_uses_ffplay_for_containerized_voice_notes() -> None:
    """Compressed/containerized incoming notes should not be sent to aplay as raw PCM."""

    assert VoIPManager._build_voice_note_playback_command("data/voice_notes/incoming.mka") == [
        "ffplay",
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "error",
        "-af",
        "volume=12.0dB",
        "data/voice_notes/incoming.mka",
    ]
    assert VoIPManager._build_voice_note_playback_command("data/voice_notes/incoming.wav") == [
        "aplay",
        "-q",
        "data/voice_notes/incoming.wav",
    ]


def test_voip_manager_coerces_rcs_voice_note_envelope_into_voice_note_record(
    tmp_path: Path,
) -> None:
    """Incoming GSMA file-transfer envelopes for voice recordings should not be stored as plain text."""

    backend = MockVoIPBackend()
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    manager = VoIPManager(config, backend=backend)

    assert manager.start()

    backend.emit(
        MessageReceived(
            message=VoIPMessageRecord(
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
        )
    )

    latest = manager.latest_voice_note_for_contact("sip:mom@example.com")
    assert latest is not None
    assert latest.kind == MessageKind.VOICE_NOTE
    assert latest.mime_type == "audio/wav"
    assert latest.duration_ms == 4046
    assert latest.text == ""
    assert latest.local_file_path == "/tmp/incoming-envelope.mka"


def test_voip_manager_builds_message_store_under_directory(tmp_path: Path) -> None:
    """The configured message store path should be treated as a directory, not a file."""

    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")

    manager = VoIPManager(config, backend=MockVoIPBackend())

    assert manager._message_store.store_dir == tmp_path / "messages"
    assert manager._message_store.index_file == tmp_path / "messages" / "messages.json"


def test_liblinphone_shim_records_voice_notes_as_wav() -> None:
    """The native recorder shim should explicitly match the .wav files used by the app."""

    shim_source = Path("yoyopod/backends/voip/shim_native/liblinphone_shim.c").read_text(
        encoding="utf-8"
    )

    assert (
        "linphone_recorder_params_set_file_format(params, LinphoneRecorderFileFormatWav);"
        in shim_source
    )


def test_liblinphone_shim_wires_incoming_message_debug_paths() -> None:
    """The native shim should cover aggregated and undecryptable incoming message paths."""

    shim_source = Path("yoyopod/backends/voip/shim_native/liblinphone_shim.c").read_text(
        encoding="utf-8"
    )

    assert (
        "linphone_core_cbs_set_messages_received(g_state.core_cbs, yoyopod_on_messages_received);"
        in shim_source
    )
    assert (
        "linphone_core_set_chat_messages_aggregation_enabled(g_state.core, FALSE);" in shim_source
    )
    assert "linphone_core_cbs_set_message_received_unable_decrypt(" in shim_source
    assert "linphone_account_params_enable_cpim_in_basic_chat_room(params, TRUE);" in shim_source
    assert (
        "linphone_account_params_set_conference_factory_address(params, conference_factory_address);"
        in shim_source
    )
    assert "linphone_account_params_set_lime_server_url(params, lime_server_url);" in shim_source
    assert "linphone_factory_create_chat_room_cbs(g_state.factory);" in shim_source
    assert "linphone_chat_room_add_callbacks(chat_room, g_state.chat_room_cbs);" in shim_source
    assert (
        "linphone_chat_room_cbs_set_message_received(g_state.chat_room_cbs, yoyopod_on_chat_room_message_received);"
        in shim_source
    )
    assert "linphone_logging_service_set_log_level_mask(" in shim_source
    assert 'yoyopod_log_account_diagnostics("registration_ok");' in shim_source
    assert "linphone_core_search_chat_room(" in shim_source
    assert "linphone_core_create_chat_room_6(" in shim_source
    assert (
        "linphone_chat_room_params_set_backend(params, LinphoneChatRoomBackendFlexisipChat);"
        in shim_source
    )
    assert (
        "linphone_chat_room_params_set_backend(params, LinphoneChatRoomBackendBasic);"
        in shim_source
    )
    assert "linphone_chat_room_params_enable_encryption(params, FALSE);" in shim_source
    assert "voice-recording=yes" in shim_source
    assert (
        "linphone_core_enable_auto_download_voice_recordings(g_state.core, FALSE);" in shim_source
    )
    assert 'linphone_chat_room_params_set_subject(params, "YoYoPod");' in shim_source
    assert "linphone_core_delete_chat_room(g_state.core, chat_room);" in shim_source
    assert shim_source.count("chat_room = yoyopod_get_direct_chat_room(sip_address);") >= 2


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


def test_voip_manager_marks_available_after_backend_recovery() -> None:
    """A recovered worker should restore availability after an unexpected stop."""

    backend = MockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    availability_changes: list[tuple[bool, str, RegistrationState]] = []
    manager.on_availability_change(
        lambda available, reason, registration_state: availability_changes.append(
            (available, reason, registration_state)
        )
    )

    assert manager.start()
    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    backend.emit(BackendStopped(reason="process_exited"))
    backend.emit(BackendRecovered(reason="worker_ready"))

    assert manager.running is True
    assert manager.registration_state == RegistrationState.PROGRESS
    assert availability_changes[-2:] == [
        (False, "process_exited", RegistrationState.FAILED),
        (True, "worker_ready", RegistrationState.PROGRESS),
    ]
