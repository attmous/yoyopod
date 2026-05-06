"""CLI-owned event contracts used by Pi validation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserActivityEvent:
    """Published when simulated user input should wake or keep the screen alive."""

    action_name: str | None = None


__all__ = ["UserActivityEvent"]
