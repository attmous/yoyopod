"""App-facing seams for the communication domain."""

from yoyopod.communication.calling import CallHistoryEntry, CallHistoryStore, VoIPManager, VoiceNoteDraft
from yoyopod.communication.calling.backend import LiblinphoneBackend, MockVoIPBackend, VoIPBackend
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
