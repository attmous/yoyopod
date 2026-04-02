"""
Typed application events for YoyoPod orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from yoyopy.audio.mopidy_client import MopidyTrack
from yoyopy.connectivity.voip_manager import CallState, RegistrationState


@dataclass(frozen=True, slots=True)
class IncomingCallEvent:
    """Published when the VoIP stack reports an incoming call."""

    caller_address: str
    caller_name: str


@dataclass(frozen=True, slots=True)
class CallStateChangedEvent:
    """Published when the VoIP call state changes."""

    state: CallState


@dataclass(frozen=True, slots=True)
class CallEndedEvent:
    """Published when a call is released."""

    reason: str = "released"


@dataclass(frozen=True, slots=True)
class RegistrationChangedEvent:
    """Published when SIP registration changes."""

    state: RegistrationState


@dataclass(frozen=True, slots=True)
class ScreenChangedEvent:
    """Published when the active screen route changes."""

    screen_name: str | None


@dataclass(frozen=True, slots=True)
class RecoveryAttemptCompletedEvent:
    """Published when a background backend recovery attempt finishes."""

    manager: Literal["mopidy"]
    recovered: bool
    recovery_now: float


@dataclass(frozen=True, slots=True)
class VoIPAvailabilityChangedEvent:
    """Published when VoIP backend availability changes."""

    available: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TrackChangedEvent:
    """Published when the current Mopidy track changes."""

    track: Optional[MopidyTrack]


@dataclass(frozen=True, slots=True)
class PlaybackStateChangedEvent:
    """Published when Mopidy playback changes state."""

    state: str


@dataclass(frozen=True, slots=True)
class MusicAvailabilityChangedEvent:
    """Published when Mopidy connectivity changes."""

    available: bool
    reason: str = ""
