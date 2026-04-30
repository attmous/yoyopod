"""Tests for the scaffold call integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.core.events import BackendStoppedEvent
from yoyopod.integrations.call import (
    CallHistoryEntry,
    CallHistoryStore,
    CallIntegration,
    CallState,
    DialCommand,
    MarkHistorySeenCommand,
    MuteCommand,
    PlayLatestVoiceNoteCommand,
    RegistrationState,
    SendActiveVoiceNoteCommand,
    SendTextMessageCommand,
    StartVoiceNoteRecordingCommand,
    StopVoiceNoteRecordingCommand,
    UnmuteCommand,
    VoIPCallSessionSnapshot,
    VoIPLifecycleSnapshot,
    VoIPRuntimeSnapshot,
    VoiceNoteSummaryChangedEvent,
    setup,
    teardown,
)
from yoyopod.core.focus import setup as setup_focus


class FakeVoipManager:
    """Minimal manager double for scaffold call integration tests."""

    def __init__(self, *, runtime_snapshot_owned: bool = False) -> None:
        self.running = False
        self.registration_state = "none"
        self.call_state = CallState.IDLE
        self.current_call_id = None
        self.is_muted = False
        self.caller_address = ""
        self.caller_name = ""
        self.pending_terminal_action = None
        self.call_duration_seconds = 0
        self.runtime_snapshot = None
        self.start_calls = 0
        self.stop_calls = 0
        self.background_iterate_enabled = False
        self.dial_calls: list[tuple[str, str]] = []
        self.text_messages: list[tuple[str, str, str]] = []
        self.voice_note_commands: list[tuple[str, str]] = []
        self.mark_history_calls: list[str] = []
        self.voice_note_unread_by_address: dict[str, int] = {}
        self.registration_callbacks = []
        self.call_state_callbacks = []
        self.incoming_call_callbacks = []
        self.availability_callbacks = []
        self.message_summary_callbacks = []
        self.runtime_snapshot_callbacks = []
        self.runtime_snapshot_owned = runtime_snapshot_owned

    def start(self) -> bool:
        self.start_calls += 1
        self.running = True
        for callback in self.availability_callbacks:
            callback(True, "started", SimpleNamespace(value="none"))
        for callback in self.message_summary_callbacks:
            callback(0, {})
        return True

    def stop(self, notify_events: bool = True) -> None:
        self.stop_calls += 1
        self.running = False

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        self.caller_address = sip_address
        self.caller_name = contact_name or sip_address
        self.dial_calls.append((sip_address, contact_name or ""))
        return True

    def answer_call(self) -> bool:
        return True

    def hangup(self) -> bool:
        self.pending_terminal_action = "hangup"
        return True

    def reject_call(self) -> bool:
        self.pending_terminal_action = "reject"
        return True

    def mute(self) -> bool:
        self.is_muted = True
        return True

    def unmute(self) -> bool:
        self.is_muted = False
        return True

    def send_text_message(self, sip_address: str, text: str, display_name: str = "") -> bool:
        self.text_messages.append((sip_address, text, display_name))
        return True

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.voice_note_commands.append(("start", recipient_address))
        return True

    def stop_voice_note_recording(self) -> object:
        self.voice_note_commands.append(("stop", ""))
        return {"status": "review"}

    def cancel_voice_note_recording(self) -> bool:
        self.voice_note_commands.append(("cancel", ""))
        return True

    def send_active_voice_note(self) -> bool:
        self.voice_note_commands.append(("send", ""))
        return True

    def play_latest_voice_note(self, sip_address: str) -> bool:
        self.voice_note_commands.append(("play", sip_address))
        return True

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        self.voice_note_unread_by_address.pop(sip_address, None)

    def mark_call_history_seen(self, sip_address: str = "") -> bool:
        self.mark_history_calls.append(sip_address)
        return True

    def call_history_unread_count(self) -> int:
        if self.runtime_snapshot is None:
            return 0
        return max(0, int(self.runtime_snapshot.unseen_call_history))

    def call_history_recent_preview(self) -> tuple[str, ...]:
        if self.runtime_snapshot is None:
            return ()
        preview: list[str] = []
        for entry in self.runtime_snapshot.recent_call_history:
            address = str(entry.get("peer_sip_address", "") or "")
            username = address.split("@", 1)[0].split(":")[-1] if address else ""
            if username:
                preview.append(username)
        return tuple(preview)

    def unread_voice_note_counts_by_contact(self) -> dict[str, int]:
        return dict(self.voice_note_unread_by_address)

    def get_call_duration(self) -> int:
        return self.call_duration_seconds

    def get_caller_info(self) -> dict[str, str]:
        return {
            "address": self.caller_address,
            "name": self.caller_name or self.caller_address,
            "display_name": self.caller_name or self.caller_address,
        }

    def consume_pending_terminal_action(self) -> str | None:
        action = self.pending_terminal_action
        self.pending_terminal_action = None
        return action

    def on_registration_change(self, callback) -> None:
        self.registration_callbacks.append(callback)

    def on_call_state_change(self, callback) -> None:
        self.call_state_callbacks.append(callback)

    def on_incoming_call(self, callback) -> None:
        self.incoming_call_callbacks.append(callback)

    def on_availability_change(self, callback) -> None:
        self.availability_callbacks.append(callback)

    def on_message_summary_change(self, callback) -> None:
        self.message_summary_callbacks.append(callback)

    def on_runtime_snapshot_change(self, callback) -> None:
        self.runtime_snapshot_callbacks.append(callback)

    def owns_runtime_snapshot(self) -> bool:
        return self.runtime_snapshot_owned

    def emit_incoming_call(self, caller_address: str, caller_name: str) -> None:
        self.caller_address = caller_address
        self.caller_name = caller_name
        for callback in self.incoming_call_callbacks:
            callback(caller_address, caller_name)

    def emit_call_state(self, state: CallState) -> None:
        self.call_state = state
        for callback in self.call_state_callbacks:
            callback(state)

    def emit_availability(self, available: bool, reason: str) -> None:
        for callback in self.availability_callbacks:
            callback(available, reason, SimpleNamespace(value="failed"))

    def emit_message_summary(
        self,
        unread_count: int,
        latest_by_contact: dict[str, dict[str, object]],
    ) -> None:
        for callback in self.message_summary_callbacks:
            callback(unread_count, latest_by_contact)

    def emit_runtime_snapshot(self, snapshot: VoIPRuntimeSnapshot) -> None:
        self.runtime_snapshot = snapshot
        self.call_state = snapshot.call_state
        self.current_call_id = snapshot.active_call_id or None
        self.caller_address = snapshot.active_call_peer
        self.caller_name = snapshot.active_call_peer
        self.is_muted = snapshot.muted
        for callback in self.runtime_snapshot_callbacks:
            callback(snapshot)


class FakeRinger:
    """Minimal ring-tone helper double."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self, _config_manager=None) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def test_call_setup_seeds_state_helpers_and_history(tmp_path: Path) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    history_store.add_entry(
        CallHistoryEntry.create(
            direction="incoming",
            display_name="Bob",
            sip_address="sip:bob@example.com",
            outcome="missed",
        )
    )
    manager = FakeVoipManager()

    integration = setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    assert isinstance(integration, CallIntegration)
    assert integration is app.integrations["call"]
    assert app.voip_manager is manager
    assert app.call_history_store is history_store
    assert app.states.get_value("call.state") == "idle"
    assert app.states.get_value("call.backend_available") is True
    assert app.states.get_value("call.registration") == "none"
    assert app.states.get_value("call.history_unread_count") == 1
    assert app.states.get("call.history_unread_count").attrs == {"recent_preview": ["Bob"]}
    assert callable(app.get_call_duration)
    assert app.get_call_duration() == 0

    teardown(app)
    assert "call" not in app.integrations


def test_unexpected_call_worker_exit_requests_recovery(tmp_path: Path) -> None:
    app = build_test_app()
    stopped_events: list[BackendStoppedEvent] = []
    app.bus.subscribe(BackendStoppedEvent, stopped_events.append)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager()
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    manager.emit_availability(False, "process_exited")
    drain_all(app)

    assert stopped_events == [BackendStoppedEvent(domain="call", reason="process_exited")]


def test_call_flow_updates_focus_mute_and_history(tmp_path: Path) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager()
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    assert app.services.call(
        "call",
        "dial",
        DialCommand(sip_address="sip:ada@example.com", contact_name="Ada"),
    )
    drain_all(app)
    assert manager.dial_calls == [("sip:ada@example.com", "Ada")]
    assert app.states.get_value("focus.owner") == "call"
    assert app.states.get_value("call.state") == "outgoing"

    manager.emit_call_state(CallState.CONNECTED)
    drain_all(app)
    assert app.states.get_value("call.state") == "active"

    assert app.services.call("call", "mute", MuteCommand()) is True
    assert app.states.get_value("call.muted") is True
    assert app.services.call("call", "unmute", UnmuteCommand()) is True
    assert app.states.get_value("call.muted") is False

    manager.call_duration_seconds = 17
    manager.emit_call_state(CallState.END)
    drain_all(app)

    assert app.states.get_value("call.state") == "idle"
    assert app.states.get_value("focus.owner") is None
    assert app.states.get_value("call.history_unread_count") == 0
    recent_entry = history_store.list_recent(1)[0]
    assert recent_entry.display_name == "Ada"
    assert recent_entry.outcome == "completed"
    assert recent_entry.duration_seconds == 17


def test_rust_owned_call_runtime_waits_for_snapshot_before_mirroring_state(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    assert app.services.call(
        "call",
        "dial",
        DialCommand(sip_address="sip:ada@example.com", contact_name="Ada"),
    )
    drain_all(app)

    assert manager.dial_calls == [("sip:ada@example.com", "Ada")]
    assert app.states.get_value("focus.owner") is None
    assert app.states.get_value("call.state") == "idle"

    manager.emit_runtime_snapshot(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.OUTGOING,
            active_call_id="call-1",
            active_call_peer="sip:ada@example.com",
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
            call_session=VoIPCallSessionSnapshot(
                active=True,
                session_id="call-1",
                direction="outgoing",
                peer_sip_address="sip:ada@example.com",
            ),
        )
    )
    manager.emit_call_state(CallState.OUTGOING)
    drain_all(app)

    assert app.states.get_value("focus.owner") == "call"
    assert app.states.get_value("call.state") == "outgoing"
    assert app.states.get("call.state").attrs["caller_address"] == "sip:ada@example.com"


def test_rust_owned_mute_waits_for_snapshot_before_mirroring_state(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    assert app.services.call("call", "mute", MuteCommand()) is True
    drain_all(app)
    assert app.states.get_value("call.muted") is False

    manager.emit_runtime_snapshot(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.STREAMS_RUNNING,
            active_call_id="call-1",
            active_call_peer="sip:ada@example.com",
            muted=True,
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
        )
    )
    drain_all(app)

    assert app.states.get_value("call.muted") is True
    assert app.states.get_value("call.state") == "active"


def test_rust_owned_terminal_session_snapshot_releases_focus_without_python_history(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    manager.emit_runtime_snapshot(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.STREAMS_RUNNING,
            active_call_id="call-1",
            active_call_peer="sip:ada@example.com",
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
            call_session=VoIPCallSessionSnapshot(
                active=True,
                session_id="call-1",
                direction="outgoing",
                peer_sip_address="sip:ada@example.com",
                answered=True,
            ),
        )
    )
    drain_all(app)
    assert app.states.get_value("focus.owner") == "call"
    assert history_store.list_recent(1) == []

    terminal_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.RELEASED,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=False,
            session_id="call-1",
            direction="outgoing",
            peer_sip_address="sip:ada@example.com",
            answered=True,
            terminal_state=CallState.RELEASED.value,
            local_end_action="hangup",
            duration_seconds=12,
            history_outcome="completed",
        ),
    )
    manager.emit_runtime_snapshot(terminal_snapshot)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)

    assert history_store.list_recent(2) == []
    assert app.states.get_value("focus.owner") is None
    assert app.states.get_value("call.history_unread_count") == 0


def test_rust_owned_call_history_uses_snapshot_without_python_store_sync(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    manager.emit_runtime_snapshot(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.IDLE,
            unseen_call_history=2,
            recent_call_history=(
                {
                    "session_id": "call-2",
                    "peer_sip_address": "sip:bob@example.com",
                    "direction": "incoming",
                    "outcome": "missed",
                    "duration_seconds": 0,
                    "seen": False,
                },
            ),
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
        )
    )
    drain_all(app)

    assert app.states.get_value("call.history_unread_count") == 2
    assert app.states.get("call.history_unread_count").attrs == {"recent_preview": ["bob"]}
    assert history_store.list_recent(1) == []

    assert app.services.call("call", "mark_history_seen", MarkHistorySeenCommand()) == 0
    drain_all(app)
    assert manager.mark_history_calls == [""]
    assert history_store.list_recent(1) == []

    manager.emit_runtime_snapshot(
        VoIPRuntimeSnapshot(
            configured=True,
            registered=True,
            registration_state=RegistrationState.OK,
            call_state=CallState.IDLE,
            lifecycle=VoIPLifecycleSnapshot(
                state="registered",
                reason="registered",
                backend_available=True,
            ),
        )
    )
    drain_all(app)
    assert history_store.list_recent(1) == []


def test_rust_owned_terminal_session_snapshot_does_not_write_python_history(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    active_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.INCOMING,
        active_call_peer="sip:bob@example.com",
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=True,
            session_id="sip:bob@example.com",
            direction="incoming",
            peer_sip_address="sip:bob@example.com",
        ),
    )
    terminal_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.RELEASED,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=False,
            session_id="sip:bob@example.com",
            direction="incoming",
            peer_sip_address="sip:bob@example.com",
            terminal_state=CallState.RELEASED.value,
            history_outcome="missed",
        ),
    )

    manager.emit_runtime_snapshot(active_snapshot)
    drain_all(app)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)

    manager.emit_runtime_snapshot(active_snapshot)
    drain_all(app)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)

    assert history_store.list_recent(3) == []


def test_rust_owned_terminal_only_snapshots_leave_python_history_empty(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup(app, manager=manager, call_history_store=history_store, ringer=FakeRinger())
    drain_all(app)

    terminal_snapshot = VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=CallState.RELEASED,
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=False,
            session_id="sip:bob@example.com",
            direction="incoming",
            peer_sip_address="sip:bob@example.com",
            terminal_state=CallState.RELEASED.value,
            history_outcome="missed",
        ),
    )

    manager.emit_incoming_call("sip:bob@example.com", "Bob")
    drain_all(app)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)

    manager.emit_incoming_call("sip:bob@example.com", "Bob")
    drain_all(app)
    manager.emit_runtime_snapshot(terminal_snapshot)
    drain_all(app)

    assert history_store.list_recent(3) == []


def test_incoming_calls_ring_and_history_can_be_marked_seen(tmp_path: Path) -> None:
    app = build_test_app()
    setup_focus(app)
    history_store = CallHistoryStore(tmp_path / "call_history.json")
    manager = FakeVoipManager()
    ringer = FakeRinger()
    setup(app, manager=manager, call_history_store=history_store, ringer=ringer)
    drain_all(app)

    manager.emit_incoming_call("sip:bob@example.com", "Bob")
    drain_all(app)
    manager.emit_call_state(CallState.INCOMING)
    drain_all(app)

    assert app.states.get_value("call.state") == "incoming"
    assert app.states.get("call.state").attrs["caller_address"] == "sip:bob@example.com"
    assert app.states.get_value("focus.owner") == "call"
    assert ringer.start_calls >= 1

    manager.emit_call_state(CallState.RELEASED)
    drain_all(app)
    assert history_store.list_recent(1)[0].outcome == "missed"
    assert app.states.get_value("call.history_unread_count") == 1

    assert app.services.call("call", "mark_history_seen", MarkHistorySeenCommand()) == 0
    drain_all(app)
    assert app.states.get_value("call.history_unread_count") == 0


def test_call_message_and_voice_note_services_update_manager_and_summary_cache(
    tmp_path: Path,
) -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()
    integration = setup(
        app,
        manager=manager,
        call_history_store=CallHistoryStore(tmp_path / "call_history.json"),
        ringer=FakeRinger(),
    )
    observed: list[VoiceNoteSummaryChangedEvent] = []
    app.bus.subscribe(VoiceNoteSummaryChangedEvent, observed.append)
    drain_all(app)

    assert app.services.call(
        "call",
        "send_text_message",
        SendTextMessageCommand(
            sip_address="sip:ada@example.com",
            text="hi",
            display_name="Ada",
        ),
    )
    assert manager.text_messages == [("sip:ada@example.com", "hi", "Ada")]

    assert app.services.call(
        "call",
        "start_voice_note_recording",
        StartVoiceNoteRecordingCommand(
            recipient_address="sip:ada@example.com",
            recipient_name="Ada",
        ),
    )
    assert app.services.call(
        "call",
        "stop_voice_note_recording",
        StopVoiceNoteRecordingCommand(),
    ) == {"status": "review"}
    assert app.services.call("call", "send_active_voice_note", SendActiveVoiceNoteCommand())
    assert app.services.call(
        "call",
        "play_latest_voice_note",
        PlayLatestVoiceNoteCommand(sip_address="sip:ada@example.com"),
    )

    manager.voice_note_unread_by_address = {"sip:ada@example.com": 2}
    manager.emit_message_summary(
        2,
        {
            "sip:ada@example.com": {
                "message_id": "note-1",
                "direction": "incoming",
            }
        },
    )
    drain_all(app)

    assert integration.last_voice_note_unread_count == 2
    assert integration.last_voice_note_unread_by_address == {"sip:ada@example.com": 2}
    assert integration.last_voice_note_summary == {
        "sip:ada@example.com": {
            "message_id": "note-1",
            "direction": "incoming",
        }
    }
    assert observed[-1].unread_count == 2
    assert manager.voice_note_commands == [
        ("start", "sip:ada@example.com"),
        ("stop", ""),
        ("send", ""),
        ("play", "sip:ada@example.com"),
    ]


def test_call_service_rejects_wrong_payload_type(tmp_path: Path) -> None:
    app = build_test_app()
    setup_focus(app)
    setup(
        app,
        manager=FakeVoipManager(),
        call_history_store=CallHistoryStore(tmp_path / "call_history.json"),
        ringer=FakeRinger(),
    )
    drain_all(app)

    try:
        app.services.call("call", "hangup", {"unexpected": True})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "call.hangup expects HangupCommand"
    else:
        raise AssertionError("call.hangup accepted an untyped payload")
