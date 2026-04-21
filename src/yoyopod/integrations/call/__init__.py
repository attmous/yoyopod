"""Canonical public seam for call-domain runtime ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.backends.voip.protocol import VoIPIterateMetrics
    from yoyopod.integrations.call.history import CallHistoryEntry, CallHistoryStore
    from yoyopod.integrations.call.messaging import MessagingService
    from yoyopod.integrations.call.message_store import VoIPMessageStore
    from yoyopod.integrations.call.manager import VoIPManager
    from yoyopod.integrations.call.models import (
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
        VoIPMessageRecord,
    )
    from yoyopod.integrations.call.voice_notes import VoiceNoteDraft, VoiceNoteService


_PUBLIC_EXPORTS = {
    "CallHistoryEntry": ("yoyopod.integrations.call.history", "CallHistoryEntry"),
    "CallHistoryStore": ("yoyopod.integrations.call.history", "CallHistoryStore"),
    "CallState": ("yoyopod.integrations.call.models", "CallState"),
    "RegistrationState": ("yoyopod.integrations.call.models", "RegistrationState"),
    "MessageKind": ("yoyopod.integrations.call.models", "MessageKind"),
    "MessageDirection": ("yoyopod.integrations.call.models", "MessageDirection"),
    "MessageDeliveryState": ("yoyopod.integrations.call.models", "MessageDeliveryState"),
    "VoIPConfig": ("yoyopod.integrations.call.models", "VoIPConfig"),
    "VoIPMessageRecord": ("yoyopod.integrations.call.models", "VoIPMessageRecord"),
    "RegistrationStateChanged": (
        "yoyopod.integrations.call.models",
        "RegistrationStateChanged",
    ),
    "CallStateChanged": ("yoyopod.integrations.call.models", "CallStateChanged"),
    "IncomingCallDetected": ("yoyopod.integrations.call.models", "IncomingCallDetected"),
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
    "VoiceNoteDraft": ("yoyopod.integrations.call.voice_notes", "VoiceNoteDraft"),
    "VoiceNoteService": ("yoyopod.integrations.call.voice_notes", "VoiceNoteService"),
}


def __getattr__(name: str) -> Any:
    """Load public call exports lazily to keep communication imports acyclic."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = [
    "CallHistoryEntry",
    "CallHistoryStore",
    "CallState",
    "RegistrationState",
    "MessageKind",
    "MessageDirection",
    "MessageDeliveryState",
    "VoIPConfig",
    "VoIPMessageRecord",
    "RegistrationStateChanged",
    "CallStateChanged",
    "IncomingCallDetected",
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
    "VoiceNoteDraft",
    "VoiceNoteService",
]
