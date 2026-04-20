"""Compatibility exports for relocated typed application events."""

from dataclasses import dataclass
from typing import Literal, Optional

from yoyopod.audio.music.models import Track
from yoyopod.communication import CallState, RegistrationState
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
