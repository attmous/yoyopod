"""Core orchestration primitives for YoyoPod.

Legacy top-level modules such as ``yoyopod.app_context``, ``yoyopod.event_bus``,
``yoyopod.events``, ``yoyopod.fsm``, ``yoyopod.runtime_state``, and
``yoyopod.setup_contract`` remain as thin compatibility shims that re-export
these symbols.
"""

from yoyopod.core.app_shell import YoyoPodAppShell
from yoyopod.core.app_context import AppContext
from yoyopod.core.bus import Bus
from yoyopod.core.event_bus import EventBus
from yoyopod.core.events import (
    AudioFocusGrantedEvent,
    AudioFocusLostEvent,
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    LifecycleEvent,
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
    StateChangedEvent,
    TrackChangedEvent,
    UserActivityEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopod.core.fsm import CallFSM, CallInterruptionPolicy, CallSessionState, MusicFSM, MusicState
from yoyopod.core.logbuffer import LogBuffer
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
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.services import Services
from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)
from yoyopod.core.states import StateValue, States
from yoyopod.core.testing import assert_events_contain, build_test_app, drain_all

__all__ = [
    "ActiveVoiceNoteState",
    "AudioFocusGrantedEvent",
    "AudioFocusLostEvent",
    "AppContext",
    "assert_events_contain",
    "Bus",
    "CallEndedEvent",
    "CallFSM",
    "CallInterruptionPolicy",
    "CallSessionState",
    "CallStateChangedEvent",
    "EventBus",
    "IncomingCallEvent",
    "LifecycleEvent",
    "LogBuffer",
    "MainThreadScheduler",
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
    "StateChangedEvent",
    "StateValue",
    "States",
    "Services",
    "TalkRuntimeState",
    "TrackChangedEvent",
    "UserActivityEvent",
    "VoIPAvailabilityChangedEvent",
    "VoipRuntimeState",
    "VoiceInteractionState",
    "VoiceState",
    "build_test_app",
    "drain_all",
    "YoyoPodAppShell",
]
