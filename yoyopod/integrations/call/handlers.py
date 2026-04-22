"""State and service helpers for the scaffold call integration."""

from __future__ import annotations

from typing import Any

from yoyopod.core.events import BackendStoppedEvent
from yoyopod.integrations.call.events import (
    CallStateChangedEvent,
    IncomingCallEvent,
    RegistrationChangedEvent,
    VoIPAvailabilityChangedEvent,
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
from yoyopod.integrations.call.models import CallState, RegistrationState
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
    """Seed the scaffold call entities from the manager and history store."""

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


def handle_incoming_call_event(app: Any, integration: Any, event: IncomingCallEvent) -> None:
    """Mirror incoming-call metadata into the state store and focus/ringer helpers."""

    integration.session_tracker.begin_incoming_call(event.caller_address, event.caller_name)
    _request_focus(app)
    _start_ringer(app, integration)
    app.states.set(
        "call.state",
        "incoming",
        {
            "raw_state": CallState.INCOMING.value,
            "caller_address": event.caller_address,
            "caller_name": event.caller_name or event.caller_address,
        },
    )
    app.states.set("call.muted", False, {})


def handle_call_state_changed_event(
    app: Any,
    integration: Any,
    event: CallStateChangedEvent,
) -> None:
    """Mirror one call-state transition and apply history/focus side effects."""

    manager = integration.manager
    state = event.state

    if state in _OUTGOING_STATES:
        _request_focus(app)
        integration.session_tracker.ensure_outgoing_call(_caller_info(manager))
        _stop_ringer(integration)
    elif state == CallState.INCOMING:
        _request_focus(app)
        pending = integration.session_tracker.pending_incoming_call
        if pending is None:
            caller = _caller_info(manager)
            integration.session_tracker.begin_incoming_call(
                str(caller.get("address") or ""),
                str(caller.get("display_name") or caller.get("name") or ""),
            )
        _start_ringer(app, integration)
    elif state in _ACTIVE_STATES:
        _request_focus(app)
        integration.session_tracker.mark_answered()
        _stop_ringer(integration)
    elif state in _TERMINAL_STATES:
        _stop_ringer(integration)
        integration.session_tracker.mark_terminal_state(
            state,
            local_end_action=_consume_pending_terminal_action(manager),
        )
        integration.session_tracker.clear_pending_incoming_call()
        integration.session_tracker.finalize(
            call_duration_seconds=_call_duration_seconds(manager)
        )
        publish_call_history_updated(app, integration)
        _release_focus_if_owned(app)

    _apply_call_state(app, manager, state)
    app.states.set("call.muted", bool(getattr(manager, "is_muted", False)), {})


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
    if not event.available and event.reason in {"backend_stopped", "start_failed"}:
        app.bus.publish(BackendStoppedEvent(domain="call", reason=event.reason))
    if not event.available:
        _stop_ringer(integration)


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
        str(address): max(0, int(count))
        for address, count in event.unread_by_address.items()
    }
    integration.last_voice_note_summary = {
        str(address): dict(summary)
        for address, summary in event.latest_by_contact.items()
    }


def dial(app: Any, integration: Any, command: DialCommand) -> bool:
    """Place an outgoing call and seed optimistic outgoing state."""

    if not isinstance(command, DialCommand):
        raise TypeError("call.dial expects DialCommand")
    success = bool(integration.manager.make_call(command.sip_address, command.contact_name))
    if not success:
        return False
    _request_focus(app)
    integration.session_tracker.ensure_outgoing_call(
        {
            "address": command.sip_address,
            "display_name": command.contact_name,
            "name": command.contact_name,
        }
    )
    app.states.set(
        "call.state",
        "outgoing",
        {
            "raw_state": CallState.OUTGOING.value,
            "caller_address": command.sip_address,
            "caller_name": command.contact_name or command.sip_address,
        },
    )
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


def mute(app: Any, integration: Any, command: MuteCommand) -> bool:
    """Mute the active call and mirror the new mute flag."""

    if not isinstance(command, MuteCommand):
        raise TypeError("call.mute expects MuteCommand")
    success = bool(integration.manager.mute())
    if success:
        app.states.set("call.muted", True, {})
    return success


def unmute(app: Any, integration: Any, command: UnmuteCommand) -> bool:
    """Unmute the active call and mirror the new mute flag."""

    if not isinstance(command, UnmuteCommand):
        raise TypeError("call.unmute expects UnmuteCommand")
    success = bool(integration.manager.unmute())
    if success:
        app.states.set("call.muted", False, {})
    return success


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
        raise TypeError(
            "call.start_voice_note_recording expects StartVoiceNoteRecordingCommand"
        )
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
        raise TypeError(
            "call.cancel_voice_note_recording expects CancelVoiceNoteRecordingCommand"
        )
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
    if integration.history_store is None:
        publish_call_history_updated(app, integration)
        return 0
    integration.history_store.mark_all_seen()
    publish_call_history_updated(app, integration)
    return integration.history_store.missed_count()


def publish_call_history_updated(app: Any, integration: Any) -> None:
    """Publish one typed history-summary update event."""

    history_store = integration.history_store
    unread_count = 0 if history_store is None else history_store.missed_count()
    recent_preview = () if history_store is None else tuple(history_store.recent_preview())
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


def _consume_pending_terminal_action(manager: Any) -> str | None:
    consume_pending_terminal_action = getattr(manager, "consume_pending_terminal_action", None)
    if not callable(consume_pending_terminal_action):
        return None
    return consume_pending_terminal_action()


def _call_duration_seconds(manager: Any) -> int:
    get_call_duration = getattr(manager, "get_call_duration", None)
    if not callable(get_call_duration):
        return 0
    return max(0, int(get_call_duration() or 0))


def _as_registration_state(value: object) -> RegistrationState:
    if isinstance(value, RegistrationState):
        return value
    try:
        return RegistrationState(str(value or RegistrationState.NONE.value))
    except ValueError:
        return RegistrationState.NONE
