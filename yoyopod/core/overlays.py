"""Cross-screen overlay contracts and runtime ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class CrossScreenOverlay(Protocol):
    """Protocol for one long-lived cross-screen overlay renderer."""

    name: str
    priority: int

    def is_active(self, now: float) -> bool:
        """Return whether this overlay should be active at the given timestamp."""
        ...

    def render(self, now: float) -> None:
        """Render this overlay on top of the currently active screen."""
        ...


@dataclass(slots=True)
class CrossScreenOverlayRuntime:
    """Evaluate registered overlays and render the highest-priority active one."""

    _overlays: list[CrossScreenOverlay] = field(default_factory=list)
    _last_active_overlay_name: str | None = None

    def register(self, overlay: CrossScreenOverlay) -> None:
        """Register a long-lived overlay implementation."""

        if any(existing.name == overlay.name for existing in self._overlays):
            raise ValueError(f"Duplicate overlay registration: {overlay.name}")

        self._overlays.append(overlay)
        self._overlays.sort(key=lambda entry: entry.priority, reverse=True)

    def update(self, now: float, *, render: bool) -> bool:
        """Refresh active overlay state and optionally render the top active overlay."""

        active_overlay: CrossScreenOverlay | None = None
        for overlay in self._overlays:
            if overlay.is_active(now) and active_overlay is None:
                active_overlay = overlay

        self._last_active_overlay_name = active_overlay.name if active_overlay else None
        if active_overlay is not None and render:
            active_overlay.render(now)
        return active_overlay is not None

    @property
    def last_active_overlay_name(self) -> str | None:
        """Return the most recent active overlay key, if any."""

        return self._last_active_overlay_name
