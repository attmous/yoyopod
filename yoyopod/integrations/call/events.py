"""Typed events owned by the canonical call integration."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.integrations.call.models import CallState, RegistrationState


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
class VoIPAvailabilityChangedEvent:
    """Published when VoIP backend availability changes."""

    available: bool
    reason: str = ""
    registration_state: RegistrationState = RegistrationState.NONE


@dataclass(frozen=True, slots=True)
class CallHistoryUpdatedEvent:
    """Published when missed-call history counters change."""

    unread_count: int
    recent_preview: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VoiceNoteSummaryChangedEvent:
    """Published when voice-note unread counts or summaries change."""

    unread_count: int
    unread_by_address: dict[str, int]
    latest_by_contact: dict[str, dict[str, object]]


__all__ = [
    "CallEndedEvent",
    "CallHistoryUpdatedEvent",
    "CallStateChangedEvent",
    "IncomingCallEvent",
    "RegistrationChangedEvent",
    "VoiceNoteSummaryChangedEvent",
    "VoIPAvailabilityChangedEvent",
]
