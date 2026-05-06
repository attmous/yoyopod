"""CLI-owned event contracts used by Pi validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoyopod_cli.pi.support.focus import FocusOwner


@dataclass(frozen=True, slots=True)
class StateChangedEvent:
    """Published when one scaffold state entity changes."""

    entity: str
    old: Any
    new: Any
    attrs: dict[str, Any]
    last_changed_at: float


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


@dataclass(frozen=True, slots=True)
class VoiceNoteSummaryChangedEvent:
    """Published when Rust-owned voice-note summary data changes."""

    unread_count: int
    unread_by_address: dict[str, int]
    latest_by_contact: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class UserActivityEvent:
    """Published when simulated user input should wake or keep the screen alive."""

    action_name: str | None = None


__all__ = [
    "AudioFocusGrantedEvent",
    "AudioFocusLostEvent",
    "StateChangedEvent",
    "UserActivityEvent",
    "VoiceNoteSummaryChangedEvent",
    "WorkerDomainStateChangedEvent",
    "WorkerMessageReceivedEvent",
]
