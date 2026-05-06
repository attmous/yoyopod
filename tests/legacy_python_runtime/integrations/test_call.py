"""Tests for the Rust snapshot-owned call integration."""

from __future__ import annotations

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.core.events import BackendStoppedEvent
from yoyopod.core.focus import setup as setup_focus
from yoyopod.integrations.call import (
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


class FakeVoipManager:
    """Minimal Rust snapshot-owned manager double for scaffold call tests."""

    def __init__(self, *, runtime_snapshot_owned: bool = True) -> None:
        self.running = False
        self.registration_state = RegistrationState.NONE
        self.call_state = CallState.IDLE
        self.current_call_id = None
        self.is_muted = False
        self.caller_address = ""
        self.caller_name = ""
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
        self.availability_callbacks = []
        self.message_summary_callbacks = []
        self.runtime_snapshot_callbacks = []
        self.runtime_snapshot_owned = runtime_snapshot_owned

    def start(self) -> bool:
        self.start_calls += 1
        self.running = True
        for callback in self.availability_callbacks:
            callback(True, "started", RegistrationState.NONE)
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
        return True

    def reject_call(self) -> bool:
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

    def on_registration_change(self, callback) -> None:
        self.registration_callbacks.append(callback)

    def on_availability_change(self, callback) -> None:
        self.availability_callbacks.append(callback)

    def on_message_summary_change(self, callback) -> None:
        self.message_summary_callbacks.append(callback)

    def on_runtime_snapshot_change(self, callback) -> None:
        self.runtime_snapshot_callbacks.append(callback)

    def owns_runtime_snapshot(self) -> bool:
        return self.runtime_snapshot_owned

    def emit_availability(self, available: bool, reason: str) -> None:
        for callback in self.availability_callbacks:
            callback(available, reason, RegistrationState.FAILED)

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


def _snapshot(
    state: CallState,
    *,
    peer: str = "sip:ada@example.com",
    session_active: bool = True,
    history_outcome: str = "",
    unseen_call_history: int = 0,
    muted: bool = False,
) -> VoIPRuntimeSnapshot:
    session_id = "call-1" if peer else ""
    return VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=state,
        active_call_id=session_id if session_active else "",
        active_call_peer=peer if session_active else "",
        muted=muted,
        unseen_call_history=unseen_call_history,
        recent_call_history=(
            {
                "session_id": session_id,
                "peer_sip_address": peer,
                "direction": "incoming",
                "outcome": history_outcome or "missed",
                "duration_seconds": 0,
                "seen": False,
            },
        )
        if unseen_call_history
        else (),
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=session_active,
            session_id=session_id,
            direction="incoming",
            peer_sip_address=peer,
            terminal_state="" if session_active else state.value,
            history_outcome=history_outcome,
        ),
    )


def test_call_setup_seeds_snapshot_manager_without_python_history_store() -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()

    integration = setup(app, manager=manager, ringer=FakeRinger())
    drain_all(app)

    assert isinstance(integration, CallIntegration)
    assert integration is app.integrations["call"]
    assert app.voip_manager is manager
    assert app.call_history_store is None
    assert not hasattr(app, "call_session_tracker")
    assert app.states.get_value("call.state") == "idle"
    assert app.states.get_value("call.backend_available") is True
    assert app.states.get_value("call.registration") == "none"
    assert app.states.get_value("call.history_unread_count") == 0
    assert callable(app.get_call_duration)

    teardown(app)
    assert "call" not in app.integrations


def test_call_setup_rejects_non_snapshot_managers() -> None:
    app = build_test_app()
    manager = FakeVoipManager(runtime_snapshot_owned=False)

    try:
        setup(app, manager=manager, ringer=FakeRinger())
    except ValueError as exc:
        assert str(exc) == "Call integration requires a Rust runtime snapshot manager"
    else:
        raise AssertionError("call setup accepted a Python-owned VoIP manager")


def test_unexpected_call_worker_exit_requests_recovery() -> None:
    app = build_test_app()
    stopped_events: list[BackendStoppedEvent] = []
    app.bus.subscribe(BackendStoppedEvent, stopped_events.append)
    manager = FakeVoipManager()
    setup(app, manager=manager, ringer=FakeRinger())
    drain_all(app)

    manager.emit_availability(False, "process_exited")
    drain_all(app)

    assert stopped_events == [BackendStoppedEvent(domain="call", reason="process_exited")]


def test_call_commands_wait_for_runtime_snapshots_before_mirroring_state() -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()
    setup(app, manager=manager, ringer=FakeRinger())
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

    manager.emit_runtime_snapshot(_snapshot(CallState.OUTGOING))
    drain_all(app)

    assert app.states.get_value("focus.owner") == "call"
    assert app.states.get_value("call.state") == "outgoing"
    assert app.states.get("call.state").attrs["caller_address"] == "sip:ada@example.com"


def test_mute_waits_for_snapshot_before_mirroring_state() -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()
    setup(app, manager=manager, ringer=FakeRinger())
    drain_all(app)

    assert app.services.call("call", "mute", MuteCommand()) is True
    drain_all(app)
    assert app.states.get_value("call.muted") is False

    manager.emit_runtime_snapshot(_snapshot(CallState.STREAMS_RUNNING, muted=True))
    drain_all(app)

    assert app.states.get_value("call.muted") is True
    assert app.states.get_value("call.state") == "active"
    assert app.services.call("call", "unmute", UnmuteCommand()) is True


def test_terminal_snapshot_releases_focus_and_uses_rust_history_summary() -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()
    ringer = FakeRinger()
    setup(app, manager=manager, ringer=ringer)
    drain_all(app)

    manager.emit_runtime_snapshot(_snapshot(CallState.INCOMING))
    drain_all(app)
    assert app.states.get_value("focus.owner") == "call"
    assert ringer.start_calls >= 1

    manager.emit_runtime_snapshot(
        _snapshot(
            CallState.RELEASED,
            peer="sip:bob@example.com",
            session_active=False,
            history_outcome="missed",
            unseen_call_history=1,
        )
    )
    drain_all(app)

    assert app.states.get_value("focus.owner") is None
    assert app.states.get_value("call.state") == "idle"
    assert app.states.get_value("call.history_unread_count") == 1
    assert app.states.get("call.history_unread_count").attrs == {"recent_preview": ["bob"]}
    assert ringer.stop_calls >= 1

    assert app.services.call("call", "mark_history_seen", MarkHistorySeenCommand()) == 0
    drain_all(app)
    assert manager.mark_history_calls == [""]


def test_call_message_and_voice_note_services_update_manager_and_summary_cache() -> None:
    app = build_test_app()
    setup_focus(app)
    manager = FakeVoipManager()
    integration = setup(app, manager=manager, ringer=FakeRinger())
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


def test_call_service_rejects_wrong_payload_type() -> None:
    app = build_test_app()
    setup_focus(app)
    setup(app, manager=FakeVoipManager(), ringer=FakeRinger())
    drain_all(app)

    try:
        app.services.call("call", "hangup", {"unexpected": True})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "call.hangup expects HangupCommand"
    else:
        raise AssertionError("call.hangup accepted an untyped payload")
