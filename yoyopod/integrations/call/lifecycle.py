"""Canonical call-session bookkeeping and history persistence helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping

from yoyopod.integrations.call.history import (
    CallDirection,
    CallHistoryEntry,
    CallHistoryStore,
    CallOutcome,
)
from yoyopod.integrations.call.models import CallState


def _party_display_name(party_info: Mapping[str, object] | None, *, fallback: str) -> str:
    """Return the best available display label for one call participant."""

    if not party_info:
        return fallback

    display_name = str(party_info.get("display_name") or party_info.get("name") or "").strip()
    return display_name or fallback


def _party_address(party_info: Mapping[str, object] | None, *, fallback: str) -> str:
    """Return the best available SIP address for one call participant."""

    if not party_info:
        return fallback

    return str(party_info.get("address") or fallback)


@dataclass(slots=True)
class ActiveCallSession:
    """One in-progress call tracked until teardown finishes."""

    direction: CallDirection
    display_name: str
    sip_address: str
    started_at: float = field(default_factory=time.time)
    answered: bool = False
    terminal_state: CallState | None = None
    local_end_action: str | None = None

    def apply_party_info(self, party_info: Mapping[str, object] | None) -> None:
        """Refresh participant details from the live VoIP manager."""

        self.display_name = _party_display_name(party_info, fallback=self.display_name)
        self.sip_address = _party_address(party_info, fallback=self.sip_address)

    def mark_answered(self) -> None:
        """Record that the call reached a connected media state."""

        self.answered = True

    def mark_terminal_state(
        self,
        state: CallState,
        *,
        local_end_action: str | None = None,
    ) -> None:
        """Record the terminal backend state and any local teardown action."""

        self.terminal_state = state
        self.local_end_action = local_end_action

    def history_outcome(self) -> CallOutcome:
        """Return the persisted call-history outcome for this session."""

        if self.answered:
            return "completed"
        if self.direction == "incoming" and self.local_end_action == "reject":
            return "rejected"
        if self.terminal_state == CallState.ERROR:
            return "failed"
        if self.direction == "incoming":
            return "missed"
        return "cancelled"


class CallSessionTracker:
    """Track active call facts and persist them into call history when needed."""

    def __init__(self, call_history_store: CallHistoryStore | None = None) -> None:
        self.call_history_store = call_history_store
        self._active_session: ActiveCallSession | None = None
        self._pending_incoming_call: tuple[str, str] | None = None

    @property
    def active_session(self) -> ActiveCallSession | None:
        """Return the in-progress call session, if any."""

        return self._active_session

    @property
    def pending_incoming_call(self) -> tuple[str, str] | None:
        """Return the caller metadata awaiting the incoming-call screen."""

        return self._pending_incoming_call

    @property
    def has_live_session(self) -> bool:
        """Return whether the tracker still owns an active call session."""

        return self._active_session is not None

    def begin_incoming_call(self, caller_address: str, caller_name: str) -> ActiveCallSession:
        """Start tracking a new incoming call and cache its caller metadata."""

        self._pending_incoming_call = (caller_address, caller_name)
        self._active_session = ActiveCallSession(
            direction="incoming",
            display_name=caller_name or "Unknown",
            sip_address=caller_address,
        )
        return self._active_session

    def ensure_outgoing_call(
        self,
        party_info: Mapping[str, object] | None = None,
    ) -> ActiveCallSession:
        """Ensure an outgoing call session exists and refresh its party details."""

        if self._active_session is None:
            self._active_session = ActiveCallSession(
                direction="outgoing",
                display_name=_party_display_name(party_info, fallback="Unknown"),
                sip_address=_party_address(party_info, fallback=""),
            )
        else:
            self._active_session.apply_party_info(party_info)
        return self._active_session

    def mark_answered(self) -> None:
        """Record that the active call reached a connected state."""

        if self._active_session is not None:
            self._active_session.mark_answered()

    def mark_terminal_state(
        self,
        state: CallState,
        *,
        local_end_action: str | None = None,
    ) -> None:
        """Record the terminal state for the active call session."""

        if self._active_session is not None:
            self._active_session.mark_terminal_state(
                state,
                local_end_action=local_end_action,
            )

    def clear_pending_incoming_call(self) -> None:
        """Drop caller metadata once the incoming-call UI is dismissed."""

        self._pending_incoming_call = None

    def finalize(self, *, call_duration_seconds: int = 0) -> CallHistoryEntry | None:
        """Persist the active call into history, then clear the live session."""

        session = self._active_session
        self._active_session = None

        if session is None or self.call_history_store is None:
            return None

        entry = CallHistoryEntry.create(
            direction=session.direction,
            display_name=session.display_name,
            sip_address=session.sip_address,
            outcome=session.history_outcome(),
            duration_seconds=call_duration_seconds,
        )
        self.call_history_store.add_entry(entry)
        return entry


__all__ = ["ActiveCallSession", "CallSessionTracker"]
