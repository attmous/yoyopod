"""Unit tests for the Rust VoIP backend adapter and manager facade."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from yoyopod.backends.voip import MockVoIPBackend
from yoyopod.backends.voip.rust_host import _runtime_snapshot
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
        self.runtime_snapshot: VoIPRuntimeSnapshot | None = None

    def get_runtime_snapshot(self) -> VoIPRuntimeSnapshot | None:
        return self.runtime_snapshot

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
        self.mark_seen_addresses: list[str] = []
        self.marked_call_history_addresses: list[str] = []
        self.played_voice_notes: list[str] = []
        self.stopped_playback = 0

    def get_runtime_snapshot(self) -> VoIPRuntimeSnapshot | None:
        return self.runtime_snapshot

    def mark_voice_notes_seen(self, sip_address: str) -> bool:
        self.mark_seen_addresses.append(sip_address)
        return True

    def mark_call_history_seen(self, sip_address: str) -> bool:
        self.marked_call_history_addresses.append(sip_address)
        return True

    def play_voice_note(self, file_path: str) -> bool:
        self.played_voice_notes.append(file_path)
        return True

    def stop_voice_note_playback(self) -> bool:
        self.stopped_playback += 1
        return True


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


def test_voip_manager_requires_explicit_backend_in_rust_only_runtime() -> None:
    """The Python facade must not construct a legacy liblinphone backend itself."""

    with pytest.raises(ValueError, match="requires an explicit VoIP backend"):
        VoIPManager(build_config())


def test_voip_manager_requires_rust_runtime_snapshot_backend() -> None:
    """Production VoIPManager should not accept a Python-owned runtime backend."""

    with pytest.raises(ValueError, match="Rust runtime snapshot"):
        VoIPManager(build_config(), backend=MockVoIPBackend())


def test_voip_manager_does_not_construct_python_runtime_owners() -> None:
    """The app-facing facade should not own Python message or voice-note stores."""

    manager = VoIPManager(build_config(), backend=SnapshotOwnedMockVoIPBackend())

    assert manager.owns_runtime_snapshot() is True
    assert not hasattr(manager, "_message_store")
    assert not hasattr(manager, "_messaging_service")
    assert not hasattr(manager, "_voice_note_service")


def wait_for_condition(predicate: Callable[[], bool], *, timeout_seconds: float = 1.0) -> bool:
    """Poll a test condition until it becomes true or the timeout expires."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_voip_manager_skips_backend_start_when_identity_missing() -> None:
    """VoIPManager should fail fast before touching the backend when SIP identity is absent."""

    backend = SnapshotOwnedMockVoIPBackend()
    config = build_config()
    config.sip_identity = ""
    manager = VoIPManager(config, backend=backend)

    assert manager.start() is False
    assert backend.running is False
    assert manager.registration_state == RegistrationState.FAILED


def test_voip_manager_applies_backend_events_and_resolves_contact_names() -> None:
    """VoIPManager should stay app-facing while backend events remain typed and low-level."""

    backend = SnapshotOwnedMockVoIPBackend()
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

    backend = SnapshotOwnedMockVoIPBackend()
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

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    call_states: list[CallState] = []

    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    manager.on_call_state_change(call_states.append)

    assert manager.make_call("sip:bob@example.com", contact_name="Bob")
    assert backend.commands == ["call sip:bob@example.com"]
    assert call_states == []
    assert manager.call_state == CallState.IDLE
    assert manager.get_caller_info()["display_name"] == "Unknown"


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


def test_rust_runtime_snapshot_parses_message_summary_fields() -> None:
    """Rust snapshot summaries should survive Python parsing without Python store reads."""

    snapshot = _runtime_snapshot(
        {
            "configured": True,
            "registered": True,
            "registration_state": "ok",
            "unread_voice_notes": 2,
            "unread_voice_notes_by_contact": {"sip:mom@example.com": 2},
            "latest_voice_note_by_contact": {
                "sip:mom@example.com": {
                    "message_id": "note-2",
                    "direction": "incoming",
                    "delivery_state": "delivered",
                    "local_file_path": "/tmp/note-2.wav",
                    "duration_ms": 2400,
                    "unread": True,
                    "display_name": "Mom",
                }
            },
        }
    )

    assert snapshot.unread_voice_notes == 2
    assert snapshot.unread_voice_notes_by_contact == {"sip:mom@example.com": 2}
    assert snapshot.latest_voice_note_by_contact == {
        "sip:mom@example.com": {
            "message_id": "note-2",
            "direction": "incoming",
            "delivery_state": "delivered",
            "local_file_path": "/tmp/note-2.wav",
            "duration_ms": 2400,
            "unread": True,
            "display_name": "Mom",
        }
    }


def test_rust_runtime_snapshot_parses_call_history_fields() -> None:
    """Rust call-history summaries should survive Python parsing without Python storage."""

    snapshot = _runtime_snapshot(
        {
            "configured": True,
            "registered": True,
            "registration_state": "ok",
            "unseen_call_history": 1,
            "recent_call_history": [
                {
                    "session_id": "call-1",
                    "peer_sip_address": "sip:mom@example.com",
                    "direction": "incoming",
                    "outcome": "missed",
                    "duration_seconds": 0,
                    "seen": False,
                }
            ],
        }
    )

    assert snapshot.unseen_call_history == 1
    assert snapshot.recent_call_history == (
        {
            "session_id": "call-1",
            "peer_sip_address": "sip:mom@example.com",
            "direction": "incoming",
            "outcome": "missed",
            "duration_seconds": 0,
            "seen": False,
        },
    )


def test_voip_manager_uses_rust_owned_voice_note_summary_snapshot() -> None:
    """Rust-host mode should expose voice-note summaries from snapshots, not Python storage."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    summary_events: list[tuple[int, dict[str, dict[str, object]]]] = []
    manager.on_message_summary_change(
        lambda unread, summary: summary_events.append((unread, dict(summary)))
    )

    assert manager.start()
    snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        unread_voice_notes=1,
        unread_voice_notes_by_contact={"sip:mom@example.com": 1},
        latest_voice_note_by_contact={
            "sip:mom@example.com": {
                "message_id": "note-1",
                "direction": "incoming",
                "delivery_state": "delivered",
                "local_file_path": "/tmp/note-1.wav",
                "duration_ms": 1800,
                "unread": True,
                "display_name": "Mom",
            }
        },
    )

    backend.runtime_snapshot = snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))
    manager.mark_voice_notes_seen("sip:mom@example.com")

    assert manager.unread_voice_note_count() == 1
    assert manager.unread_voice_note_counts_by_contact() == {"sip:mom@example.com": 1}
    assert manager.latest_voice_note_summary()["sip:mom@example.com"]["message_id"] == "note-1"
    assert summary_events == [(1, snapshot.latest_voice_note_by_contact)]
    assert backend.mark_seen_addresses == ["sip:mom@example.com"]


def test_voip_manager_routes_rust_owned_playback_to_backend() -> None:
    """Voice-note playback is a Rust runtime command, not a Python subprocess."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        latest_voice_note_by_contact={
            "sip:mom@example.com": {
                "message_id": "note-1",
                "direction": "incoming",
                "delivery_state": "delivered",
                "local_file_path": "/tmp/note-1.wav",
                "duration_ms": 1800,
                "unread": True,
                "display_name": "Mom",
            }
        },
    )

    assert manager.start()
    backend.runtime_snapshot = snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))

    assert manager.play_latest_voice_note("sip:mom@example.com") is True
    assert backend.played_voice_notes == ["/tmp/note-1.wav"]


def test_voip_manager_stops_rust_owned_playback_through_backend() -> None:
    """Call activity should ask Rust to stop playback when Rust owns the runtime."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    manager._update_call_state(CallState.INCOMING)

    assert backend.stopped_playback == 1


def test_voip_manager_does_not_persist_rust_owned_message_events_to_python_store(
    tmp_path: Path,
) -> None:
    """Rust-host message events should not repopulate the legacy Python message store."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(tmp_path), backend=backend)

    assert manager.start()
    backend.emit(
        MessageReceived(
            message=VoIPMessageRecord(
                id="incoming-note-1",
                peer_sip_address="sip:mom@example.com",
                sender_sip_address="sip:mom@example.com",
                recipient_sip_address="sip:alice@example.com",
                kind=MessageKind.VOICE_NOTE,
                direction=MessageDirection.INCOMING,
                delivery_state=MessageDeliveryState.DELIVERED,
                created_at="2026-04-29T00:00:00+00:00",
                updated_at="2026-04-29T00:00:00+00:00",
                local_file_path="/tmp/note.wav",
                mime_type="audio/wav",
                duration_ms=1000,
                unread=True,
            )
        )
    )

    assert not hasattr(manager, "_message_store")


def test_voip_manager_derives_rust_owned_active_voice_note_from_snapshot() -> None:
    """Rust snapshots should be enough to expose active voice-note UI state."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        voice_note=VoIPVoiceNoteSnapshot(
            state="recording",
            file_path="/tmp/rust-note.wav",
            mime_type="audio/wav",
        ),
    )
    backend.runtime_snapshot = snapshot
    backend.emit(VoIPRuntimeSnapshotChanged(snapshot=snapshot))

    active = manager.get_active_voice_note()
    assert active is not None
    assert active.file_path == "/tmp/rust-note.wav"
    assert active.send_state == "recording"
    assert active.status_text == "Recording..."


def test_voip_manager_sends_rust_owned_voice_note_without_python_message_store(
    tmp_path: Path,
) -> None:
    """Rust-owned voice-note sends should not create Python message records."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(tmp_path), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    draft = manager.stop_voice_note_recording()
    assert draft is not None

    assert manager.send_active_voice_note() is True

    assert backend.commands == [
        f"record-start {draft.file_path}",
        "record-stop",
        f"voice-note sip:mom@example.com {Path(draft.file_path).name} 1500 audio/wav",
    ]
    assert manager.get_active_voice_note().send_state == "sending"
    assert not hasattr(manager, "_message_store")


def test_voip_manager_ignores_direct_delivery_events_when_rust_owns_voice_notes(
    tmp_path: Path,
) -> None:
    """Rust-owned voice-note delivery state should change only through snapshots."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(tmp_path), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True

    backend.emit(
        MessageDeliveryChanged(
            message_id="mock-note-1",
            delivery_state=MessageDeliveryState.SENT,
            local_file_path="/tmp/rust-note.wav",
        )
    )

    assert manager.get_active_voice_note().send_state == "sending"
    assert not hasattr(manager, "_message_store")


def test_voip_manager_marks_rust_owned_voice_note_failed_from_command_error(
    tmp_path: Path,
) -> None:
    """Rust command failures should unblock the active compatibility draft."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(tmp_path), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True

    backend.emit(MessageFailed(message_id="mock-note-1", reason="Upload failed"))

    active = manager.get_active_voice_note()
    assert active is not None
    assert active.send_state == "failed"
    assert active.status_text == "Upload failed"
    assert active.send_started_at == 0.0
    assert not hasattr(manager, "_message_store")


def test_voip_manager_skips_python_send_timeout_when_rust_owns_voice_notes(
    tmp_path: Path,
) -> None:
    """Rust runtime recovery owns stuck voice-note sends in snapshot mode."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(tmp_path), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True

    active = manager.get_active_voice_note()
    assert active is not None
    active.send_started_at = time.monotonic() - 30.0

    assert manager.iterate() == 0
    assert manager.get_active_voice_note().send_state == "sending"
    assert not hasattr(manager, "_message_store")


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

    backend = SnapshotOwnedMockVoIPBackend()
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

    backend = SnapshotOwnedMockVoIPBackend()
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

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")

    draft = manager.stop_voice_note_recording()
    assert draft is not None
    assert draft.send_state == "review"

    assert manager.send_active_voice_note()
    assert manager.get_active_voice_note().send_state == "sending"

    backend.emit(
        VoIPRuntimeSnapshotChanged(
            snapshot=VoIPRuntimeSnapshot(
                voice_note=VoIPVoiceNoteSnapshot(
                    state="sent",
                    file_path=draft.file_path,
                    duration_ms=draft.duration_ms,
                    mime_type=draft.mime_type,
                    message_id=draft.message_id,
                )
            )
        )
    )

    assert manager.get_active_voice_note().send_state == "sent"


def test_voip_manager_routes_rust_runtime_snapshot_to_voice_note_and_message_mirrors() -> None:
    """VoIPManager should fan Rust snapshots into its compatibility services."""

    backend = SnapshotOwnedMockVoIPBackend()
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
                latest_voice_note_by_contact={
                    "sip:mom@example.com": {
                        "message_id": draft.message_id,
                        "direction": MessageDirection.OUTGOING.value,
                        "delivery_state": MessageDeliveryState.DELIVERED.value,
                        "local_file_path": draft.file_path,
                        "duration_ms": draft.duration_ms,
                        "display_name": "Mom",
                    }
                },
            )
        )
    )

    active = manager.get_active_voice_note()
    assert active is not None
    assert active.send_state == "sent"
    stored = manager.latest_voice_note_for_contact("sip:mom@example.com")
    assert stored is not None
    assert stored.delivery_state == MessageDeliveryState.DELIVERED


def test_voip_manager_delegates_voice_note_send_without_transfer_server() -> None:
    """Rust owns transfer-server validation instead of a Python preflight."""

    backend = SnapshotOwnedMockVoIPBackend()
    config = build_config()
    config.file_transfer_server_url = ""
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None

    assert manager.send_active_voice_note() is True
    assert manager.get_active_voice_note().send_state == "sending"


def test_voip_manager_allows_voice_note_send_for_hosted_linphone_account_without_explicit_url() -> (
    None
):
    """Hosted Linphone accounts should use inferred upload settings instead of failing immediately."""

    backend = SnapshotOwnedMockVoIPBackend()
    config = build_config()
    config.sip_server = "sip.linphone.org"
    config.file_transfer_server_url = ""
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True
    assert manager.get_active_voice_note().send_state == "sending"


def test_voip_manager_does_not_timeout_rust_owned_voice_note_send() -> None:
    """Rust runtime recovery owns stuck voice-note sends."""

    backend = SnapshotOwnedMockVoIPBackend()
    config = build_config()
    config.file_transfer_server_url = "https://transfer.example.com"
    manager = VoIPManager(config, backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note() is True

    manager.get_active_voice_note().send_started_at = time.monotonic() - 30.0
    drained_events = manager.iterate()

    assert manager.get_active_voice_note().send_state == "sending"
    assert drained_events == 0


def test_voip_manager_rejects_voice_note_recording_during_active_call() -> None:
    """Voice-note recording should be blocked while a call is active."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)
    manager.call_state = CallState.CONNECTED

    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom") is False
    assert manager.get_active_voice_note() is None


def test_voip_manager_stops_voice_note_playback_when_call_enters_active_state() -> None:
    """Incoming or active call phases should stop any local voice-note playback."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    manager._update_call_state(CallState.INCOMING)

    assert backend.stopped_playback == 1


def test_voip_manager_queues_backend_events_back_to_main_thread(tmp_path: Path) -> None:
    """App-mode VoIP events should be marshaled back through the main-thread scheduler."""

    backend = SnapshotOwnedMockVoIPBackend()
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

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    assert manager.start_voice_note_recording("sip:mom@example.com", recipient_name="Mom")
    assert manager.stop_voice_note_recording() is not None
    assert manager.send_active_voice_note()

    backend.emit(MessageFailed(message_id="mock-note-1", reason="Upload failed"))

    assert manager.get_active_voice_note().send_state == "failed"
    assert manager.get_active_voice_note().status_text == "Upload failed"


def test_voip_manager_receives_voice_note_summary_from_runtime_snapshot(tmp_path: Path) -> None:
    """Incoming voice notes should be exposed through Rust-owned snapshot summaries."""

    backend = SnapshotOwnedMockVoIPBackend()
    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")
    manager = VoIPManager(config, backend=backend)
    summary_events: list[tuple[int, dict[str, dict[str, object]]]] = []
    manager.on_message_summary_change(
        lambda unread, summary: summary_events.append((unread, summary))
    )

    assert manager.start()

    backend.emit(
        VoIPRuntimeSnapshotChanged(
            snapshot=VoIPRuntimeSnapshot(
                unread_voice_notes=1,
                unread_voice_notes_by_contact={"sip:mom@example.com": 1},
                latest_voice_note_by_contact={
                    "sip:mom@example.com": {
                        "message_id": "incoming-1",
                        "direction": MessageDirection.INCOMING.value,
                        "delivery_state": MessageDeliveryState.DELIVERED.value,
                        "local_file_path": "data/voice_notes/incoming.wav",
                        "duration_ms": 2000,
                        "unread": True,
                        "display_name": "Mom",
                    }
                },
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


def test_voip_manager_ignores_raw_incoming_message_events_without_snapshot(
    tmp_path: Path,
) -> None:
    """Rust snapshots, not Python message parsing, own incoming message state."""

    backend = SnapshotOwnedMockVoIPBackend()
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

    assert manager.latest_voice_note_for_contact("sip:mom@example.com") is None
    assert manager.latest_voice_note_summary() == {}


def test_voip_manager_leaves_message_store_directory_to_rust(tmp_path: Path) -> None:
    """The Python facade should not create a legacy message-store directory."""

    config = build_config()
    config.message_store_dir = str(tmp_path / "messages")

    manager = VoIPManager(config, backend=SnapshotOwnedMockVoIPBackend())

    assert not hasattr(manager, "_message_store")
    assert not (tmp_path / "messages").exists()


def test_voip_manager_handles_backend_stop_event() -> None:
    """Unexpected backend stop should clear availability and registration state."""

    backend = SnapshotOwnedMockVoIPBackend()
    manager = VoIPManager(build_config(), backend=backend)

    assert manager.start()
    backend.emit(RegistrationStateChanged(state=RegistrationState.OK))
    backend.emit(BackendStopped(reason="native core stopped"))

    assert manager.running is False
    assert manager.registered is False
    assert manager.registration_state == RegistrationState.FAILED


def test_voip_manager_marks_available_after_backend_recovery() -> None:
    """A recovered worker should restore availability after an unexpected stop."""

    backend = SnapshotOwnedMockVoIPBackend()
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
