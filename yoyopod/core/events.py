"""Typed application events for YoYoPod orchestration and scaffold work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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
class BackendStoppedEvent:
    """Published when one integration-owned backend becomes unavailable."""

    domain: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WorkerDomainStateChangedEvent:
    """Published when one worker-backed domain changes availability."""

    domain: str
    state: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WorkerMessageReceivedEvent:
    """Published when a worker emits a protocol event or result."""

    domain: str
    kind: str
    type: str
    request_id: str | None
    payload: dict[str, Any]


__all__ = [
    "AudioFocusGrantedEvent",
    "AudioFocusLostEvent",
    "BackendStoppedEvent",
    "FocusOwner",
    "LifecycleEvent",
    "RecoveryAttemptCompletedEvent",
    "ScreenChangedEvent",
    "StateChangedEvent",
    "UserActivityEvent",
    "WorkerDomainStateChangedEvent",
    "WorkerMessageReceivedEvent",
]
