"""Music-focused finite-state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger


class MusicState(Enum):
    """Music playback state."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"


class MusicFSM:
    """Small FSM for music playback orchestration."""

    _TRANSITIONS = {
        MusicState.IDLE: {"play": MusicState.PLAYING, "stop": MusicState.IDLE},
        MusicState.PLAYING: {
            "play": MusicState.PLAYING,
            "pause": MusicState.PAUSED,
            "stop": MusicState.IDLE,
        },
        MusicState.PAUSED: {
            "play": MusicState.PLAYING,
            "pause": MusicState.PAUSED,
            "stop": MusicState.IDLE,
        },
    }

    def __init__(self, initial_state: MusicState = MusicState.IDLE) -> None:
        self.state = initial_state
        self.previous_state: Optional[MusicState] = None

    def transition(self, trigger: str) -> bool:
        """Transition using a small trigger vocabulary."""
        target = self._TRANSITIONS.get(self.state, {}).get(trigger)
        if target is None:
            logger.warning(f"Invalid music transition: {self.state.value} -> {trigger}")
            return False

        if target == self.state:
            return True

        self.previous_state = self.state
        self.state = target
        logger.debug(
            "MusicFSM: {} -> {} ({})",
            self.previous_state.value,
            self.state.value,
            trigger,
        )
        return True

    def sync(self, state: MusicState) -> None:
        """Force-sync to a known state."""
        if self.state == state:
            return

        self.previous_state = self.state
        self.state = state
        logger.debug("MusicFSM synced to {}", self.state.value)

