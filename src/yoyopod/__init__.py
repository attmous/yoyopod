"""
YoyoPod package.

Integrated Raspberry Pi application for button-driven music playback and SIP calling.
"""

from yoyopod.event_bus import EventBus
from yoyopod.events import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    MusicAvailabilityChangedEvent,
    PlaybackStateChangedEvent,
    RegistrationChangedEvent,
    ScreenChangedEvent,
    TrackChangedEvent,
    UserActivityEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopod.fsm import CallFSM, CallInterruptionPolicy, CallSessionState, MusicFSM, MusicState

__version__ = "0.1.0"
__author__ = "YoyoPod Team"

__all__ = [
    "EventBus",
    "IncomingCallEvent",
    "CallStateChangedEvent",
    "CallEndedEvent",
    "RegistrationChangedEvent",
    "ScreenChangedEvent",
    "UserActivityEvent",
    "VoIPAvailabilityChangedEvent",
    "TrackChangedEvent",
    "PlaybackStateChangedEvent",
    "MusicAvailabilityChangedEvent",
    "MusicFSM",
    "MusicState",
    "CallFSM",
    "CallSessionState",
    "CallInterruptionPolicy",
]
