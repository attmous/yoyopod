"""App-facing seams for the communication domain."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.communication.calling.history import CallHistoryEntry, CallHistoryStore
    from yoyopod.communication.integrations.liblinphone import LiblinphoneBackend
    from yoyopod.communication.calling.manager import VoIPManager
    from yoyopod.communication.calling.mock_backend import MockVoIPBackend
    from yoyopod.communication.calling.voice_notes import VoiceNoteDraft
    from yoyopod.communication.calling.backend_protocol import VoIPBackend
    from yoyopod.communication.messaging import VoIPMessageStore
    from yoyopod.communication.models import (
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


_LAZY_EXPORTS = {
    "VoIPManager": "yoyopod.communication.calling.manager",
    "VoiceNoteDraft": "yoyopod.communication.calling.voice_notes",
    "VoIPMessageStore": "yoyopod.communication.messaging",
    "CallHistoryEntry": "yoyopod.communication.calling.history",
    "CallHistoryStore": "yoyopod.communication.calling.history",
    "VoIPBackend": "yoyopod.communication.calling.backend_protocol",
    "LiblinphoneBackend": "yoyopod.communication.integrations.liblinphone",
    "MockVoIPBackend": "yoyopod.communication.calling.mock_backend",
    "VoIPConfig": "yoyopod.communication.models",
    "VoIPMessageRecord": "yoyopod.communication.models",
    "RegistrationState": "yoyopod.communication.models",
    "CallState": "yoyopod.communication.models",
    "MessageKind": "yoyopod.communication.models",
    "MessageDirection": "yoyopod.communication.models",
    "MessageDeliveryState": "yoyopod.communication.models",
    "RegistrationStateChanged": "yoyopod.communication.models",
    "CallStateChanged": "yoyopod.communication.models",
    "IncomingCallDetected": "yoyopod.communication.models",
    "MessageReceived": "yoyopod.communication.models",
    "MessageDeliveryChanged": "yoyopod.communication.models",
    "MessageDownloadCompleted": "yoyopod.communication.models",
    "MessageFailed": "yoyopod.communication.models",
    "BackendStopped": "yoyopod.communication.models",
    "VoIPEvent": "yoyopod.communication.models",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name), name)


__all__ = [
    "VoIPManager",
    "VoiceNoteDraft",
    "VoIPMessageStore",
    "CallHistoryEntry",
    "CallHistoryStore",
    "VoIPBackend",
    "LiblinphoneBackend",
    "MockVoIPBackend",
    "VoIPConfig",
    "VoIPMessageRecord",
    "RegistrationState",
    "CallState",
    "MessageKind",
    "MessageDirection",
    "MessageDeliveryState",
    "RegistrationStateChanged",
    "CallStateChanged",
    "IncomingCallDetected",
    "MessageReceived",
    "MessageDeliveryChanged",
    "MessageDownloadCompleted",
    "MessageFailed",
    "BackendStopped",
    "VoIPEvent",
]
