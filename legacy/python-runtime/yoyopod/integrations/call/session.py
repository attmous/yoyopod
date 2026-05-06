"""Canonical call-session orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from yoyopod_cli.pi.support.music_integration import MusicFSM


class CallSessionState(Enum):
    """High-level call session state."""

    IDLE = "idle"
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    ACTIVE = "active"


class CallFSM:
    """Small FSM for call orchestration."""

    _TRANSITIONS = {
        CallSessionState.IDLE: {
            "incoming": CallSessionState.INCOMING,
            "dial": CallSessionState.OUTGOING,
            "reset": CallSessionState.IDLE,
        },
        CallSessionState.INCOMING: {
            "incoming": CallSessionState.INCOMING,
            "connect": CallSessionState.ACTIVE,
            "end": CallSessionState.IDLE,
            "reset": CallSessionState.IDLE,
        },
        CallSessionState.OUTGOING: {
            "dial": CallSessionState.OUTGOING,
            "connect": CallSessionState.ACTIVE,
            "end": CallSessionState.IDLE,
            "reset": CallSessionState.IDLE,
        },
        CallSessionState.ACTIVE: {
            "connect": CallSessionState.ACTIVE,
            "end": CallSessionState.IDLE,
            "reset": CallSessionState.IDLE,
        },
    }

    def __init__(self, initial_state: CallSessionState = CallSessionState.IDLE) -> None:
        self.state = initial_state
        self.previous_state: CallSessionState | None = None

    def transition(self, trigger: str) -> bool:
        """Transition using a small trigger vocabulary."""

        target = self._TRANSITIONS.get(self.state, {}).get(trigger)
        if target is None:
            logger.warning("Invalid call transition: {} -> {}", self.state.value, trigger)
            return False

        if target == self.state:
            return True

        self.previous_state = self.state
        self.state = target
        logger.debug(
            "CallFSM: {} -> {} ({})",
            self.previous_state.value,
            self.state.value,
            trigger,
        )
        return True

    def sync(self, state: CallSessionState) -> None:
        """Force-sync to a known state."""

        if self.state == state:
            return

        self.previous_state = self.state
        self.state = state
        logger.debug("CallFSM synced to {}", self.state.value)

    @property
    def is_active(self) -> bool:
        """Return True when any call is in progress."""

        return self.state != CallSessionState.IDLE


@dataclass
class CallInterruptionPolicy:
    """Track whether a call interrupted playback and owns resume policy."""

    music_interrupted_by_call: bool = False

    def mark_paused_for_call(self, music_fsm: MusicFSM) -> None:
        """Record that a call successfully paused active playback."""

        self.music_interrupted_by_call = True
        music_fsm.transition("pause")

    def should_auto_resume(self, auto_resume: bool) -> bool:
        """Return True if interrupted playback should resume after call end."""

        return self.music_interrupted_by_call and auto_resume

    def clear(self) -> None:
        """Reset call interruption tracking after a call completes."""

        self.music_interrupted_by_call = False


__all__ = ["CallFSM", "CallInterruptionPolicy", "CallSessionState"]
