"""Audio focus command contracts used by CLI-owned support modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FocusOwner = Literal["call", "music", "voice"]


@dataclass(frozen=True, slots=True)
class RequestFocusCommand:
    """Request audio focus for one owner, optionally allowing preemption."""

    owner: FocusOwner
    allow_preempt: bool = True


@dataclass(frozen=True, slots=True)
class ReleaseFocusCommand:
    """Release audio focus for one owner."""

    owner: FocusOwner


__all__ = ["FocusOwner", "ReleaseFocusCommand", "RequestFocusCommand"]
