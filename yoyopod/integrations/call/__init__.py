"""Canonical public seam and scaffold setup for call-domain ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.backends.voip.protocol import VoIPIterateMetrics
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
    from yoyopod.integrations.call.events import (
        CallEndedEvent,
        CallHistoryUpdatedEvent,
        CallStateChangedEvent,
        IncomingCallEvent,
        RegistrationChangedEvent,
        VoiceNoteSummaryChangedEvent,
        VoIPAvailabilityChangedEvent,
    )
    from yoyopod.integrations.call.runtime import CallRuntime
    from yoyopod.integrations.call.history import CallHistoryEntry, CallHistoryStore
    from yoyopod.integrations.call.lifecycle import ActiveCallSession, CallSessionTracker
    from yoyopod.integrations.call.messaging import MessagingService
    from yoyopod.integrations.call.message_store import VoIPMessageStore
    from yoyopod.integrations.call.manager import VoIPManager
    from yoyopod.integrations.call.ringer import CallRinger
    from yoyopod.integrations.call.session import (
        CallFSM,
        CallInterruptionPolicy,
        CallSessionState,
    )
    from yoyopod.integrations.call.status import is_voip_configured, sync_context_voip_status
    from yoyopod.integrations.call.models import (
        BackendRecovered,
        BackendStopped,
        CallState,
        CallStateChanged,
        IncomingCallDetected,
        MessageDeliveryChanged,
        MessageDeliveryState,
        MessageDirection,
        MessageDownloadCompleted,
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
    from yoyopod.integrations.call.voice_notes import VoiceNoteDraft, VoiceNoteService


_PUBLIC_EXPORTS = {
    "AnswerCommand": ("yoyopod.integrations.call.commands", "AnswerCommand"),
    "ActiveCallSession": ("yoyopod.integrations.call.lifecycle", "ActiveCallSession"),
    "CancelVoiceNoteRecordingCommand": (
        "yoyopod.integrations.call.commands",
        "CancelVoiceNoteRecordingCommand",
    ),
    "CallFSM": ("yoyopod.integrations.call.session", "CallFSM"),
    "CallRuntime": ("yoyopod.integrations.call.runtime", "CallRuntime"),
    "CallEndedEvent": ("yoyopod.integrations.call.events", "CallEndedEvent"),
    "CallHistoryUpdatedEvent": ("yoyopod.integrations.call.events", "CallHistoryUpdatedEvent"),
    "CallInterruptionPolicy": ("yoyopod.integrations.call.session", "CallInterruptionPolicy"),
    "CallStateChangedEvent": ("yoyopod.integrations.call.events", "CallStateChangedEvent"),
    "CallSessionState": ("yoyopod.integrations.call.session", "CallSessionState"),
    "CallSessionTracker": ("yoyopod.integrations.call.lifecycle", "CallSessionTracker"),
    "CallHistoryEntry": ("yoyopod.integrations.call.history", "CallHistoryEntry"),
    "CallHistoryStore": ("yoyopod.integrations.call.history", "CallHistoryStore"),
    "CallRinger": ("yoyopod.integrations.call.ringer", "CallRinger"),
    "DialCommand": ("yoyopod.integrations.call.commands", "DialCommand"),
    "HangupCommand": ("yoyopod.integrations.call.commands", "HangupCommand"),
    "IncomingCallEvent": ("yoyopod.integrations.call.events", "IncomingCallEvent"),
    "is_voip_configured": ("yoyopod.integrations.call.status", "is_voip_configured"),
    "MarkHistorySeenCommand": ("yoyopod.integrations.call.commands", "MarkHistorySeenCommand"),
    "MuteCommand": ("yoyopod.integrations.call.commands", "MuteCommand"),
    "PlayLatestVoiceNoteCommand": (
        "yoyopod.integrations.call.commands",
        "PlayLatestVoiceNoteCommand",
    ),
    "RejectCommand": ("yoyopod.integrations.call.commands", "RejectCommand"),
    "SendActiveVoiceNoteCommand": (
        "yoyopod.integrations.call.commands",
        "SendActiveVoiceNoteCommand",
    ),
    "SendTextMessageCommand": (
        "yoyopod.integrations.call.commands",
        "SendTextMessageCommand",
    ),
    "StartVoiceNoteRecordingCommand": (
        "yoyopod.integrations.call.commands",
        "StartVoiceNoteRecordingCommand",
    ),
    "StopVoiceNoteRecordingCommand": (
        "yoyopod.integrations.call.commands",
        "StopVoiceNoteRecordingCommand",
    ),
    "sync_context_voip_status": ("yoyopod.integrations.call.status", "sync_context_voip_status"),
    "CallState": ("yoyopod.integrations.call.models", "CallState"),
    "RegistrationState": ("yoyopod.integrations.call.models", "RegistrationState"),
    "MessageKind": ("yoyopod.integrations.call.models", "MessageKind"),
    "MessageDirection": ("yoyopod.integrations.call.models", "MessageDirection"),
    "MessageDeliveryState": ("yoyopod.integrations.call.models", "MessageDeliveryState"),
    "VoIPConfig": ("yoyopod.integrations.call.models", "VoIPConfig"),
    "VoIPLifecycleSnapshot": (
        "yoyopod.integrations.call.models",
        "VoIPLifecycleSnapshot",
    ),
    "VoIPMessageSnapshot": ("yoyopod.integrations.call.models", "VoIPMessageSnapshot"),
    "VoIPMessageRecord": ("yoyopod.integrations.call.models", "VoIPMessageRecord"),
    "VoIPRuntimeSnapshot": ("yoyopod.integrations.call.models", "VoIPRuntimeSnapshot"),
    "VoIPRuntimeSnapshotChanged": (
        "yoyopod.integrations.call.models",
        "VoIPRuntimeSnapshotChanged",
    ),
    "VoIPVoiceNoteSnapshot": (
        "yoyopod.integrations.call.models",
        "VoIPVoiceNoteSnapshot",
    ),
    "RegistrationChangedEvent": (
        "yoyopod.integrations.call.events",
        "RegistrationChangedEvent",
    ),
    "RegistrationStateChanged": (
        "yoyopod.integrations.call.models",
        "RegistrationStateChanged",
    ),
    "CallStateChanged": ("yoyopod.integrations.call.models", "CallStateChanged"),
    "IncomingCallDetected": ("yoyopod.integrations.call.models", "IncomingCallDetected"),
    "BackendRecovered": ("yoyopod.integrations.call.models", "BackendRecovered"),
    "BackendStopped": ("yoyopod.integrations.call.models", "BackendStopped"),
    "MessageReceived": ("yoyopod.integrations.call.models", "MessageReceived"),
    "MessageDeliveryChanged": (
        "yoyopod.integrations.call.models",
        "MessageDeliveryChanged",
    ),
    "MessageDownloadCompleted": (
        "yoyopod.integrations.call.models",
        "MessageDownloadCompleted",
    ),
    "MessageFailed": ("yoyopod.integrations.call.models", "MessageFailed"),
    "VoIPEvent": ("yoyopod.integrations.call.models", "VoIPEvent"),
    "MessagingService": ("yoyopod.integrations.call.messaging", "MessagingService"),
    "VoIPMessageStore": ("yoyopod.integrations.call.message_store", "VoIPMessageStore"),
    "VoIPIterateMetrics": ("yoyopod.backends.voip.protocol", "VoIPIterateMetrics"),
    "VoIPManager": ("yoyopod.integrations.call.manager", "VoIPManager"),
    "VoIPAvailabilityChangedEvent": (
        "yoyopod.integrations.call.events",
        "VoIPAvailabilityChangedEvent",
    ),
    "VoiceNoteDraft": ("yoyopod.integrations.call.voice_notes", "VoiceNoteDraft"),
    "VoiceNoteEventHandler": ("yoyopod.integrations.call.voice_notes", "VoiceNoteEventHandler"),
    "VoiceNoteService": ("yoyopod.integrations.call.voice_notes", "VoiceNoteService"),
    "VoiceNoteSummaryChangedEvent": (
        "yoyopod.integrations.call.events",
        "VoiceNoteSummaryChangedEvent",
    ),
    "UnmuteCommand": ("yoyopod.integrations.call.commands", "UnmuteCommand"),
}


@dataclass(slots=True)
class CallIntegration:
    """Runtime handles owned by the scaffold call integration."""

    manager: object
    history_store: object | None
    session_tracker: object
    ringer: object
    last_voice_note_unread_count: int = 0
    last_voice_note_unread_by_address: dict[str, int] = field(default_factory=dict)
    last_voice_note_summary: dict[str, dict[str, object]] = field(default_factory=dict)


def setup(
    app: Any,
    *,
    config: object | None = None,
    manager: object | None = None,
    backend: object | None = None,
    people_directory: object | None = None,
    message_store: object | None = None,
    call_history_store: object | None = None,
    ringer: object | None = None,
    background_iterate_enabled: bool = False,
    start_manager: bool = True,
) -> CallIntegration:
    """Register scaffold call services, state mirroring, and recovery hooks."""

    from yoyopod.integrations.call.events import (
        CallHistoryUpdatedEvent,
        CallStateChangedEvent,
        IncomingCallEvent,
        RegistrationChangedEvent,
        VoiceNoteSummaryChangedEvent,
        VoIPAvailabilityChangedEvent,
    )
    from yoyopod.integrations.call.handlers import (
        answer,
        cancel_voice_note_recording,
        dial,
        handle_availability_changed_event,
        handle_call_history_updated_event,
        handle_call_state_changed_event,
        handle_incoming_call_event,
        handle_registration_changed_event,
        handle_voice_note_summary_changed_event,
        hangup,
        mark_history_seen,
        mute,
        play_latest_voice_note,
        reject,
        seed_call_state,
        send_active_voice_note,
        send_text_message,
        start_voice_note_recording,
        stop_voice_note_recording,
        unmute,
    )
    from yoyopod.integrations.call.history import CallHistoryStore
    from yoyopod.integrations.call.lifecycle import CallSessionTracker
    from yoyopod.integrations.call.manager import VoIPManager
    from yoyopod.integrations.call.ringer import CallRinger

    actual_config = None
    if config is not None or manager is None or call_history_store is None:
        actual_config = _resolve_voip_config(app, explicit=config)
    actual_people_directory = people_directory or _lookup_people_directory(app)
    actual_history_store = call_history_store or CallHistoryStore(actual_config.call_history_file)
    actual_manager = manager or VoIPManager(
        actual_config,
        people_directory=actual_people_directory,
        backend=backend,
        message_store=message_store,
        event_scheduler=app.scheduler.run_on_main,
        background_iterate_enabled=background_iterate_enabled,
    )
    actual_ringer = ringer or CallRinger()
    integration = CallIntegration(
        manager=actual_manager,
        history_store=actual_history_store,
        session_tracker=CallSessionTracker(actual_history_store),
        ringer=actual_ringer,
    )

    app.integrations["call"] = integration
    app.voip_manager = actual_manager
    app.call_history_store = actual_history_store
    app.call_session_tracker = integration.session_tracker
    app.call_ringer = actual_ringer
    app.get_call_duration = lambda: actual_manager.get_call_duration()

    app.bus.subscribe(
        IncomingCallEvent,
        lambda event: handle_incoming_call_event(app, integration, event),
    )
    app.bus.subscribe(
        CallStateChangedEvent,
        lambda event: handle_call_state_changed_event(app, integration, event),
    )
    app.bus.subscribe(
        RegistrationChangedEvent,
        lambda event: handle_registration_changed_event(app, integration, event),
    )
    app.bus.subscribe(
        VoIPAvailabilityChangedEvent,
        lambda event: handle_availability_changed_event(app, integration, event),
    )
    app.bus.subscribe(
        CallHistoryUpdatedEvent,
        lambda event: handle_call_history_updated_event(app, integration, event),
    )
    app.bus.subscribe(
        VoiceNoteSummaryChangedEvent,
        lambda event: handle_voice_note_summary_changed_event(app, integration, event),
    )

    actual_manager.on_incoming_call(
        lambda caller_address, caller_name: app.bus.publish(
            IncomingCallEvent(caller_address=caller_address, caller_name=caller_name)
        )
    )
    actual_manager.on_call_state_change(
        lambda state: app.bus.publish(CallStateChangedEvent(state=state))
    )
    actual_manager.on_registration_change(
        lambda state: app.bus.publish(RegistrationChangedEvent(state=state))
    )
    actual_manager.on_availability_change(
        lambda available, reason, registration_state: app.bus.publish(
            VoIPAvailabilityChangedEvent(
                available=available,
                reason=reason,
                registration_state=registration_state,
            )
        )
    )
    actual_manager.on_message_summary_change(
        lambda unread_count, latest_by_contact: app.bus.publish(
            VoiceNoteSummaryChangedEvent(
                unread_count=max(0, int(unread_count)),
                unread_by_address=_voice_note_unread_by_address(actual_manager),
                latest_by_contact={
                    str(address): dict(summary) for address, summary in latest_by_contact.items()
                },
            )
        )
    )

    app.services.register("call", "dial", lambda data: dial(app, integration, data))
    app.services.register("call", "answer", lambda data: answer(app, integration, data))
    app.services.register("call", "hangup", lambda data: hangup(integration, data))
    app.services.register("call", "reject", lambda data: reject(integration, data))
    app.services.register("call", "mute", lambda data: mute(app, integration, data))
    app.services.register("call", "unmute", lambda data: unmute(app, integration, data))
    app.services.register(
        "call",
        "send_text_message",
        lambda data: send_text_message(integration, data),
    )
    app.services.register(
        "call",
        "start_voice_note_recording",
        lambda data: start_voice_note_recording(integration, data),
    )
    app.services.register(
        "call",
        "stop_voice_note_recording",
        lambda data: stop_voice_note_recording(integration, data),
    )
    app.services.register(
        "call",
        "cancel_voice_note_recording",
        lambda data: cancel_voice_note_recording(integration, data),
    )
    app.services.register(
        "call",
        "send_active_voice_note",
        lambda data: send_active_voice_note(integration, data),
    )
    app.services.register(
        "call",
        "play_latest_voice_note",
        lambda data: play_latest_voice_note(integration, data),
    )
    app.services.register(
        "call",
        "mark_history_seen",
        lambda data: mark_history_seen(app, integration, data),
    )

    started = bool(getattr(actual_manager, "running", False))
    if start_manager:
        started = bool(actual_manager.start())
        if started and getattr(actual_manager, "background_iterate_enabled", False):
            ensure_background_iterate_running = getattr(
                actual_manager,
                "ensure_background_iterate_running",
                None,
            )
            if callable(ensure_background_iterate_running):
                ensure_background_iterate_running()

    if hasattr(app, "recovery_supervisor"):
        app.recovery_supervisor.register_retry_handler(
            "call",
            lambda: _restart_manager(actual_manager),
        )

    seed_call_state(app, integration, available=started)
    return integration


def teardown(app: Any) -> None:
    """Stop the scaffold VoIP manager and drop exposed integration helpers."""

    integration = app.integrations.pop("call", None)
    if integration is None:
        return

    stop = getattr(integration.ringer, "stop", None)
    if callable(stop):
        stop()
    _stop_manager(integration.manager)

    for attribute in (
        "voip_manager",
        "call_history_store",
        "call_session_tracker",
        "call_ringer",
        "get_call_duration",
    ):
        if hasattr(app, attribute):
            delattr(app, attribute)


def _resolve_voip_config(app: Any, *, explicit: object | None) -> Any:
    if explicit is not None:
        return explicit

    if getattr(app, "config_manager", None) is not None:
        from yoyopod.integrations.call.models import VoIPConfig

        return VoIPConfig.from_config_manager(app.config_manager)

    from yoyopod.integrations.call.models import VoIPConfig

    defaults = VoIPConfig()
    config = getattr(app, "config", None)
    communication = getattr(config, "communication", None)
    calling = getattr(communication, "calling", None)
    messaging = getattr(communication, "messaging", None)
    audio = getattr(communication, "audio", None)
    integrations = getattr(communication, "integrations", None)
    secrets = getattr(communication, "secrets", None)
    account = getattr(calling, "account", None)
    network = getattr(calling, "network", None)

    return VoIPConfig(
        sip_server=str(getattr(account, "sip_server", defaults.sip_server)),
        sip_username=str(getattr(account, "sip_username", "")),
        sip_password=str(getattr(secrets, "sip_password", "")),
        sip_password_ha1=str(getattr(secrets, "sip_password_ha1", "")),
        sip_identity=str(getattr(account, "sip_identity", "")),
        factory_config_path=str(
            getattr(
                integrations,
                "liblinphone_factory_config_path",
                defaults.factory_config_path,
            )
        ),
        transport=str(getattr(account, "transport", defaults.transport)),
        stun_server=str(getattr(network, "stun_server", "")),
        conference_factory_uri=str(getattr(messaging, "conference_factory_uri", "")),
        file_transfer_server_url=str(getattr(messaging, "file_transfer_server_url", "")),
        lime_server_url=str(getattr(messaging, "lime_server_url", "")),
        iterate_interval_ms=int(
            getattr(messaging, "iterate_interval_ms", defaults.iterate_interval_ms)
        ),
        message_store_dir=str(getattr(messaging, "message_store_dir", defaults.message_store_dir)),
        voice_note_store_dir=str(
            getattr(messaging, "voice_note_store_dir", defaults.voice_note_store_dir)
        ),
        call_history_file=str(getattr(calling, "call_history_file", defaults.call_history_file)),
        voice_note_max_duration_seconds=int(
            getattr(
                messaging,
                "voice_note_max_duration_seconds",
                defaults.voice_note_max_duration_seconds,
            )
        ),
        auto_download_incoming_voice_recordings=bool(
            getattr(
                messaging,
                "auto_download_incoming_voice_recordings",
                defaults.auto_download_incoming_voice_recordings,
            )
        ),
        playback_dev_id=str(getattr(audio, "playback_device_id", defaults.playback_dev_id)),
        ringer_dev_id=str(getattr(audio, "ringer_device_id", defaults.ringer_dev_id)),
        capture_dev_id=str(getattr(audio, "capture_device_id", defaults.capture_dev_id)),
        media_dev_id=str(getattr(audio, "media_device_id", defaults.media_dev_id)),
        mic_gain=int(getattr(audio, "mic_gain", defaults.mic_gain)),
        output_volume=int(getattr(config, "default_volume", defaults.output_volume)),
    )


def _lookup_people_directory(app: Any) -> object | None:
    contacts_integration = getattr(app, "integrations", {}).get("contacts")
    if contacts_integration is not None:
        directory = getattr(contacts_integration, "directory", None)
        if directory is not None:
            return directory
    return getattr(app, "people_directory", None)


def _restart_manager(manager: object) -> bool:
    _stop_manager(manager)
    start = getattr(manager, "start", None)
    if not callable(start):
        return False
    started = bool(start())
    if started:
        ensure_background_iterate_running = getattr(
            manager, "ensure_background_iterate_running", None
        )
        if callable(ensure_background_iterate_running):
            ensure_background_iterate_running()
    return started


def _voice_note_unread_by_address(manager: object) -> dict[str, int]:
    unread_by_address = getattr(manager, "unread_voice_note_counts_by_contact", None)
    if not callable(unread_by_address):
        return {}
    raw_counts = unread_by_address()
    if not isinstance(raw_counts, dict):
        return {}
    return {
        str(address): max(0, int(count))
        for address, count in raw_counts.items()
        if str(address).strip()
    }


def _stop_manager(manager: object) -> None:
    stop = getattr(manager, "stop", None)
    if not callable(stop):
        return
    try:
        stop(notify_events=False)
    except TypeError:
        stop()


def __getattr__(name: str) -> Any:
    """Load public call exports lazily to keep communication imports acyclic."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = [
    "AnswerCommand",
    "ActiveCallSession",
    "CallIntegration",
    "CallEndedEvent",
    "CallFSM",
    "CallRuntime",
    "CallHistoryUpdatedEvent",
    "CallInterruptionPolicy",
    "CallStateChangedEvent",
    "CallSessionState",
    "CallSessionTracker",
    "CancelVoiceNoteRecordingCommand",
    "CallHistoryEntry",
    "CallHistoryStore",
    "CallRinger",
    "DialCommand",
    "HangupCommand",
    "IncomingCallEvent",
    "is_voip_configured",
    "MarkHistorySeenCommand",
    "MuteCommand",
    "PlayLatestVoiceNoteCommand",
    "RejectCommand",
    "SendActiveVoiceNoteCommand",
    "SendTextMessageCommand",
    "StartVoiceNoteRecordingCommand",
    "StopVoiceNoteRecordingCommand",
    "sync_context_voip_status",
    "CallState",
    "RegistrationState",
    "MessageKind",
    "MessageDirection",
    "MessageDeliveryState",
    "VoIPConfig",
    "VoIPLifecycleSnapshot",
    "VoIPMessageSnapshot",
    "VoIPMessageRecord",
    "VoIPRuntimeSnapshot",
    "VoIPRuntimeSnapshotChanged",
    "VoIPVoiceNoteSnapshot",
    "RegistrationChangedEvent",
    "RegistrationStateChanged",
    "CallStateChanged",
    "IncomingCallDetected",
    "BackendRecovered",
    "BackendStopped",
    "MessageReceived",
    "MessageDeliveryChanged",
    "MessageDownloadCompleted",
    "MessageFailed",
    "VoIPEvent",
    "MessagingService",
    "VoIPMessageStore",
    "VoIPIterateMetrics",
    "VoIPManager",
    "VoIPAvailabilityChangedEvent",
    "VoiceNoteDraft",
    "VoiceNoteEventHandler",
    "VoiceNoteService",
    "VoiceNoteSummaryChangedEvent",
    "UnmuteCommand",
    "setup",
    "teardown",
]
