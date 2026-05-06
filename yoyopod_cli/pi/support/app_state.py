"""Minimal app-state contracts used by CLI-owned music support."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class AppRuntimeState(Enum):
    """Derived application states referenced by CLI support modules."""

    PLAYING_WITH_VOIP = "playing_with_voip"


class _StateChange(Protocol):
    def entered(self, state: AppRuntimeState) -> bool:
        """Return whether this update entered the provided state."""


class AppStateRuntime(Protocol):
    """Runtime methods consumed by CLI-owned music support."""

    call_fsm: object
    call_interruption_policy: object
    music_fsm: object

    def sync_app_state(self, trigger: str = "sync") -> _StateChange:
        """Refresh the derived runtime state."""


__all__ = ["AppRuntimeState", "AppStateRuntime"]
