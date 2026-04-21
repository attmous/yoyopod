"""Typed commands for the scaffold focus integration."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.core.events import FocusOwner


@dataclass(frozen=True, slots=True)
class RequestFocusCommand:
    """Request audio focus for one owner, optionally allowing preemption."""

    owner: FocusOwner
    allow_preempt: bool = True


@dataclass(frozen=True, slots=True)
class ReleaseFocusCommand:
    """Release audio focus for one owner."""

    owner: FocusOwner
