"""Typed application events for YoyoPod orchestration and scaffold work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from yoyopod.audio.music.models import Track
from yoyopod.communication.models import CallState, RegistrationState

FocusOwner = Literal["call", "music", "voice"]


@dataclass(frozen=True, slots=True)
class StateChangedEvent:
    """Published when one entity changes in the Phase A scaffold state store."""

    entity: str
    old: Any
    new: Any
    attrs: dict[str, Any]
    last_changed_at: float


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """Published when the scaffold app shell changes lifecycle phase."""

    phase: str
    detail: str = ""


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
class UserActivityEvent:
    """Published when user input activity should wake or keep the screen alive."""

    action_name: str | None = None


@dataclass(frozen=True, slots=True)
class AudioFocusGrantedEvent:
    """Published when one domain is granted audio focus."""

    owner: FocusOwner
    preempted: FocusOwner | None = None


@dataclass(frozen=True, slots=True)
class AudioFocusLostEvent:
    """Published when one domain loses audio focus."""

    owner: FocusOwner
    preempted_by: FocusOwner | None = None


@dataclass(frozen=True, slots=True)
class RecoveryAttemptCompletedEvent:
    """Published when a background backend recovery attempt finishes."""

    manager: Literal["music", "network"]
    recovered: bool
    recovery_now: float


@dataclass(frozen=True, slots=True)
class VoIPAvailabilityChangedEvent:
    """Published when VoIP backend availability changes."""

    available: bool
    reason: str = ""
    registration_state: RegistrationState = RegistrationState.NONE


@dataclass(frozen=True, slots=True)
class TrackChangedEvent:
    """Published when the current track changes."""

    track: Optional[Track]


@dataclass(frozen=True, slots=True)
class PlaybackStateChangedEvent:
    """Published when playback changes state."""

    state: str


@dataclass(frozen=True, slots=True)
class MusicAvailabilityChangedEvent:
    """Published when music-backend connectivity changes."""

    available: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class NetworkModemReadyEvent:
    """Published when the modem is initialized and registered."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkRegisteredEvent:
    """Published when the modem attaches to a cellular network."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkPppUpEvent:
    """Published when PPP data session is established."""

    connection_type: str = "4g"


@dataclass(frozen=True, slots=True)
class NetworkPppDownEvent:
    """Published when PPP data session drops."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class NetworkSignalUpdateEvent:
    """Published when signal strength changes."""

    bars: int = 0
    csq: int = 0


@dataclass(frozen=True, slots=True)
class NetworkGpsFixEvent:
    """Published when a GPS coordinate is obtained."""

    lat: float = 0.0
    lng: float = 0.0
    altitude: float = 0.0
    speed: float = 0.0


@dataclass(frozen=True, slots=True)
class NetworkGpsNoFixEvent:
    """Published when a GPS query completes without an active fix."""

    reason: str = ""
