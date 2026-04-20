"""Core orchestration primitives for YoyoPod.

Legacy top-level modules such as ``yoyopod.app_context``, ``yoyopod.event_bus``,
``yoyopod.events``, ``yoyopod.fsm``, ``yoyopod.runtime_state``, and
``yoyopod.setup_contract`` remain as thin compatibility shims that re-export
these symbols.
"""

from yoyopod.core.app_context import AppContext
from yoyopod.core.event_bus import EventBus
from yoyopod.core.events import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    MusicAvailabilityChangedEvent,
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
    NetworkModemReadyEvent,
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkRegisteredEvent,
    NetworkSignalUpdateEvent,
    PlaybackStateChangedEvent,
    RecoveryAttemptCompletedEvent,
    RegistrationChangedEvent,
    ScreenChangedEvent,
    TrackChangedEvent,
    UserActivityEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopod.core.fsm import CallFSM, CallInterruptionPolicy, CallSessionState, MusicFSM, MusicState
from yoyopod.core.runtime_state import (
    ActiveVoiceNoteState,
    MediaRuntimeState,
    NetworkRuntimeState,
    PlaybackState,
    PowerRuntimeState,
    ScreenRuntimeState,
    TalkRuntimeState,
    VoiceInteractionState,
    VoiceState,
    VoipRuntimeState,
)
from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)

__all__ = [
    "ActiveVoiceNoteState",
    "AppContext",
    "CallEndedEvent",
    "CallFSM",
    "CallInterruptionPolicy",
    "CallSessionState",
    "CallStateChangedEvent",
    "EventBus",
    "IncomingCallEvent",
    "MediaRuntimeState",
    "MusicAvailabilityChangedEvent",
    "MusicFSM",
    "MusicState",
    "NetworkGpsFixEvent",
    "NetworkGpsNoFixEvent",
    "NetworkModemReadyEvent",
    "NetworkPppDownEvent",
    "NetworkPppUpEvent",
    "NetworkRegisteredEvent",
    "NetworkRuntimeState",
    "NetworkSignalUpdateEvent",
    "PlaybackState",
    "PlaybackStateChangedEvent",
    "PowerRuntimeState",
    "RUNTIME_REQUIRED_CONFIG_FILES",
    "RecoveryAttemptCompletedEvent",
    "RegistrationChangedEvent",
    "ScreenChangedEvent",
    "ScreenRuntimeState",
    "SETUP_TRACKED_CONFIG_FILES",
    "TalkRuntimeState",
    "TrackChangedEvent",
    "UserActivityEvent",
    "VoIPAvailabilityChangedEvent",
    "VoipRuntimeState",
    "VoiceInteractionState",
    "VoiceState",
]
