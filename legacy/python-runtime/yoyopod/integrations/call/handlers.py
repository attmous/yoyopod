"""State and service helpers for the scaffold call integration."""

from __future__ import annotations

from typing import Any

from yoyopod.core.events import BackendStoppedEvent
from yoyopod.integrations.call.events import (
    RegistrationChangedEvent,
    VoIPAvailabilityChangedEvent,
    VoIPRuntimeSnapshotChangedEvent,
)
from yoyopod.integrations.call.commands import (
    AnswerCommand,
    CancelVoiceNoteRecordingCommand,
    DialCommand,
    HangupCommand,
    MarkHistorySeenCommand,
    MuteCommand,
    PlayLatestVoiceNoteCommand,
    RejectCommand,
    SendActiveVoiceNoteCommand,
    SendTextMessageCommand,
    StartVoiceNoteRecordingCommand,
    StopVoiceNoteRecordingCommand,
    UnmuteCommand,
)
from yoyopod.integrations.call.events import CallHistoryUpdatedEvent, VoiceNoteSummaryChangedEvent
from yoyopod_cli.pi.support.call_models import (
    CallState,
    RegistrationState,
    VoIPCallSessionSnapshot,
    VoIPRuntimeSnapshot,
)
from yoyopod.core.focus import ReleaseFocusCommand, RequestFocusCommand

_OUTGOING_STATES = {
    CallState.OUTGOING,
    CallState.OUTGOING_PROGRESS,
    CallState.OUTGOING_RINGING,
    CallState.OUTGOING_EARLY_MEDIA,
}
_ACTIVE_STATES = {
    CallState.CONNECTED,
    CallState.STREAMS_RUNNING,
    CallState.PAUSED,
    CallState.PAUSED_BY_REMOTE,
    CallState.UPDATED_BY_REMOTE,
}
_TERMINAL_STATES = {
    CallState.IDLE,
    CallState.RELEASED,
    CallState.END,
    CallState.ERROR,
}


def seed_call_state(app: Any, integration: Any, *, available: bool) -> None:
    """Seed the scaffold call entities from the Rust snapshot manager."""

    manager = integration.manager
    registration_state = _as_registration_state(getattr(manager, "registration_state", None))
    app.states.set(
        "call.registration",
        registration_state.value,
        {"reason": "startup"},
    )
    app.states.set(
        "call.backend_available",
        bool(available),
        {
            "reason": "startup",
            "registration_state": registration_state.value,
        },
    )
    _apply_call_state(app, manager, getattr(manager, "call_state", CallState.IDLE))
    app.states.set("call.muted", bool(getattr(manager, "is_muted", False)), {})
    publish_call_history_updated(app, integration)


def handle_registration_changed_event(
    app: Any,
    _integration: Any,
    event: RegistrationChangedEvent,
) -> None:
    """Mirror one registration-state change into the state store."""

    app.states.set("call.registration", event.state.value, {"reason": "registration_changed"})


def handle_availability_changed_event(
    app: Any,
    integration: Any,
    event: VoIPAvailabilityChangedEvent,
) -> None:
    """Mirror backend availability and forward unexpected stop signals to recovery."""

    app.states.set(
        "call.backend_available",
        bool(event.available),
        {
            "reason": event.reason,
            "registration_state": event.registration_state.value,
        },
    )
    app.states.set(
        "call.registration",
        event.registration_state.value,
        {"reason": event.reason or "availability_changed"},
    )
    if not event.available and _should_request_call_recovery(event.reason):
        app.bus.publish(BackendStoppedEvent(domain="call", reason=event.reason))
    if not event.available:
        _stop_ringer(integration)


def handle_runtime_snapshot_changed_event(
    app: Any,
    integration: Any,
    event: VoIPRuntimeSnapshotChangedEvent,
) -> None:
    """Mirror Rust-owned runtime facts that may change without a call-state transition."""

    _apply_rust_call_session_side_effects(app, integration, event.snapshot)
    _apply_call_state(app, integration.manager, event.snapshot.call_state)
    app.states.set("call.muted", bool(event.snapshot.muted), {})
    publish_call_history_updated(app, integration)


def _apply_rust_call_session_side_effects(
    app: Any,
    integration: Any,
    snapshot: VoIPRuntimeSnapshot,
) -> None:
    session = snapshot.call_session
    state = snapshot.call_state
    _prune_finalized_rust_call_sessions(integration, session)

    if session.active:
        if state in _OUTGOING_STATES:
            _request_focus(app)
            _stop_ringer(integration)
        elif state == CallState.INCOMING:
            _request_focus(app)
            _start_ringer(app, integration)
        elif state in _ACTIVE_STATES:
            _request_focus(app)
            _stop_ringer(integration)
        return

    if _rust_call_session_is_terminal(session):
        _stop_ringer(integration)
        _release_focus_if_owned(app)


def _rust_call_session_is_terminal(session: VoIPCallSessionSnapshot) -> bool:
    return bool(session.session_id and session.history_outcome and session.terminal_state)


def _prune_finalized_rust_call_sessions(
    integration: Any,
    session: VoIPCallSessionSnapshot,
) -> None:
    finalized_sessions = getattr(integration, "finalized_rust_call_sessions", None)
    if not isinstance(finalized_sessions, set):
        return
    if session.active or not _rust_call_session_is_terminal(session):
        finalized_sessions.clear()


def _clear_finalized_rust_call_sessions(integration: Any) -> None:
    finalized_sessions = getattr(integration, "finalized_rust_call_sessions", None)
    if isinstance(finalized_sessions, set):
        finalized_sessions.clear()


def handle_call_history_updated_event(
    app: Any,
    _integration: Any,
    event: CallHistoryUpdatedEvent,
) -> None:
    """Mirror missed-call history counters into the state store."""

    app.states.set(
        "call.history_unread_count",
        int(event.unread_count),
        {"recent_preview": list(event.recent_preview)},
    )


def handle_voice_note_summary_changed_event(
    _app: Any,
    integration: Any,
    event: VoiceNoteSummaryChangedEvent,
) -> None:
    """Cache the latest voice-note summary snapshot for other integrations."""

    integration.last_voice_note_unread_count = max(0, int(event.unread_count))
    integration.last_voice_note_unread_by_address = {
        str(address): max(0, int(count)) for address, count in event.unread_by_address.items()
    }
    integration.last_voice_note_summary = {
        str(address): dict(summary) for address, summary in event.latest_by_contact.items()
    }


def dial(_app: Any, integration: Any, command: DialCommand) -> bool:
    """Place an outgoing call and wait for Rust snapshots to mirror state."""

    if not isinstance(command, DialCommand):
        raise TypeError("call.dial expects DialCommand")
    success = bool(integration.manager.make_call(command.sip_address, command.contact_name))
    if not success:
        return False
    _clear_finalized_rust_call_sessions(integration)
    return True


def answer(app: Any, integration: Any, command: AnswerCommand) -> bool:
    """Answer the active incoming call."""

    if not isinstance(command, AnswerCommand):
        raise TypeError("call.answer expects AnswerCommand")
    success = bool(integration.manager.answer_call())
    if success:
        _request_focus(app)
        _stop_ringer(integration)
    return success


def hangup(integration: Any, command: HangupCommand) -> bool:
    """Hang up the active call."""

    if not isinstance(command, HangupCommand):
        raise TypeError("call.hangup expects HangupCommand")
    return bool(integration.manager.hangup())


def reject(integration: Any, command: RejectCommand) -> bool:
    """Reject the active incoming call."""

    if not isinstance(command, RejectCommand):
        raise TypeError("call.reject expects RejectCommand")
    _stop_ringer(integration)
    return bool(integration.manager.reject_call())


def mute(_app: Any, integration: Any, command: MuteCommand) -> bool:
    """Mute the active call and wait for Rust snapshots to mirror state."""

    if not isinstance(command, MuteCommand):
        raise TypeError("call.mute expects MuteCommand")
    return bool(integration.manager.mute())


def unmute(_app: Any, integration: Any, command: UnmuteCommand) -> bool:
    """Unmute the active call and wait for Rust snapshots to mirror state."""

    if not isinstance(command, UnmuteCommand):
        raise TypeError("call.unmute expects UnmuteCommand")
    return bool(integration.manager.unmute())


def send_text_message(integration: Any, command: SendTextMessageCommand) -> bool:
    """Send one text message through the canonical call seam."""

    if not isinstance(command, SendTextMessageCommand):
        raise TypeError("call.send_text_message expects SendTextMessageCommand")
    return bool(
        integration.manager.send_text_message(
            command.sip_address,
            command.text,
            command.display_name,
        )
    )


def start_voice_note_recording(
    integration: Any,
    command: StartVoiceNoteRecordingCommand,
) -> bool:
    """Start recording one voice note draft."""

    if not isinstance(command, StartVoiceNoteRecordingCommand):
        raise TypeError("call.start_voice_note_recording expects StartVoiceNoteRecordingCommand")
    return bool(
        integration.manager.start_voice_note_recording(
            command.recipient_address,
            command.recipient_name,
        )
    )


def stop_voice_note_recording(integration: Any, command: StopVoiceNoteRecordingCommand) -> object:
    """Stop the active voice-note recording and return the draft."""

    if not isinstance(command, StopVoiceNoteRecordingCommand):
        raise TypeError("call.stop_voice_note_recording expects StopVoiceNoteRecordingCommand")
    return integration.manager.stop_voice_note_recording()


def cancel_voice_note_recording(
    integration: Any,
    command: CancelVoiceNoteRecordingCommand,
) -> bool:
    """Cancel the active voice-note draft."""

    if not isinstance(command, CancelVoiceNoteRecordingCommand):
        raise TypeError("call.cancel_voice_note_recording expects CancelVoiceNoteRecordingCommand")
    return bool(integration.manager.cancel_voice_note_recording())


def send_active_voice_note(integration: Any, command: SendActiveVoiceNoteCommand) -> bool:
    """Send the current voice-note draft."""

    if not isinstance(command, SendActiveVoiceNoteCommand):
        raise TypeError("call.send_active_voice_note expects SendActiveVoiceNoteCommand")
    return bool(integration.manager.send_active_voice_note())


def play_latest_voice_note(integration: Any, command: PlayLatestVoiceNoteCommand) -> bool:
    """Play the latest voice note for one contact."""

    if not isinstance(command, PlayLatestVoiceNoteCommand):
        raise TypeError("call.play_latest_voice_note expects PlayLatestVoiceNoteCommand")
    return bool(integration.manager.play_latest_voice_note(command.sip_address))


def mark_history_seen(app: Any, integration: Any, command: MarkHistorySeenCommand) -> int:
    """Mark missed-call history rows seen and refresh the mirrored state."""

    if not isinstance(command, MarkHistorySeenCommand):
        raise TypeError("call.mark_history_seen expects MarkHistorySeenCommand")
    mark_seen = getattr(integration.manager, "mark_call_history_seen", None)
    marked = bool(mark_seen("")) if callable(mark_seen) else False
    unread_count = 0 if marked else _runtime_call_history_unread_count(integration.manager)
    _publish_call_history_updated(
        app,
        unread_count,
        _runtime_call_history_preview(integration.manager),
    )
    return unread_count


def publish_call_history_updated(app: Any, integration: Any) -> None:
    """Publish one typed history-summary update event."""

    unread_count = _runtime_call_history_unread_count(integration.manager)
    _publish_call_history_updated(
        app,
        unread_count,
        _runtime_call_history_preview(integration.manager),
    )


def _publish_call_history_updated(
    app: Any, unread_count: int, recent_preview: tuple[str, ...]
) -> None:
    app.bus.publish(
        CallHistoryUpdatedEvent(
            unread_count=unread_count,
            recent_preview=recent_preview,
        )
    )


def _apply_call_state(app: Any, manager: Any, state: CallState) -> str:
    normalized = _normalize_call_state(state)
    attrs = {"raw_state": state.value}
    caller = _caller_info(manager)
    caller_address = str(caller.get("address") or "").strip()
    caller_name = str(caller.get("display_name") or caller.get("name") or "").strip()
    if caller_address:
        attrs["caller_address"] = caller_address
    if caller_name:
        attrs["caller_name"] = caller_name
    call_id = getattr(manager, "current_call_id", None)
    if call_id:
        attrs["call_id"] = str(call_id)
    app.states.set("call.state", normalized, attrs)
    return normalized


def _normalize_call_state(state: CallState) -> str:
    if state == CallState.INCOMING:
        return "incoming"
    if state in _OUTGOING_STATES:
        return "outgoing"
    if state in _ACTIVE_STATES:
        return "active"
    return "idle"


def _request_focus(app: Any) -> bool:
    try:
        return bool(app.services.call("focus", "request", RequestFocusCommand(owner="call")))
    except KeyError:
        return False


def _release_focus_if_owned(app: Any) -> None:
    if app.states.get_value("focus.owner") != "call":
        return
    try:
        app.services.call("focus", "release", ReleaseFocusCommand(owner="call"))
    except KeyError:
        return


def _start_ringer(app: Any, integration: Any) -> None:
    integration.ringer.start(getattr(app, "config_manager", None))


def _stop_ringer(integration: Any) -> None:
    integration.ringer.stop()


def _caller_info(manager: Any) -> dict[str, object]:
    get_caller_info = getattr(manager, "get_caller_info", None)
    if callable(get_caller_info):
        info = get_caller_info()
        if isinstance(info, dict):
            return dict(info)
    return {}


def _extract_username(sip_address: str) -> str:
    if not sip_address:
        return "Unknown"
    if "@" not in sip_address:
        return sip_address
    username_part = sip_address.split("@", 1)[0]
    if ":" in username_part:
        return username_part.split(":")[-1]
    return username_part


def _runtime_call_history_unread_count(manager: Any) -> int:
    unread_count = getattr(manager, "call_history_unread_count", None)
    if not callable(unread_count):
        return 0
    return max(0, int(unread_count() or 0))


def _runtime_call_history_preview(manager: Any) -> tuple[str, ...]:
    recent_preview = getattr(manager, "call_history_recent_preview", None)
    if not callable(recent_preview):
        return ()
    raw_preview = recent_preview()
    if not isinstance(raw_preview, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw_preview if str(value).strip())


def _as_registration_state(value: object) -> RegistrationState:
    if isinstance(value, RegistrationState):
        return value
    try:
        return RegistrationState(str(value or RegistrationState.NONE.value))
    except ValueError:
        return RegistrationState.NONE


def _should_request_call_recovery(reason: str) -> bool:
    normalized = str(reason or "").strip()
    if normalized in {
        "backend_stopped",
        "process_exited",
        "restart_failed",
        "start_failed",
        "max_restarts_exceeded",
        "worker_ready_reconfigure_failed",
    }:
        return True
    return normalized.startswith("voip.")
