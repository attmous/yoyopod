"""Cross-screen overlay contracts and runtime ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class CrossScreenOverlay(Protocol):
    """Protocol for one long-lived cross-screen overlay renderer."""

    name: str
    priority: int

    def is_active(self, now: float) -> bool:
        """Return whether this overlay should be active without mutating overlay state."""
        ...

    def render(self, now: float) -> None:
        """Render this overlay on top of the currently active screen."""
        ...

    def on_deactivate(self, now: float) -> None:
        """Reconcile overlay-owned state while this overlay is not the active winner."""
        ...


@dataclass(slots=True)
class CrossScreenOverlayRuntime:
    """Evaluate registered overlays once per tick and render the active winner."""

    _overlays: list[CrossScreenOverlay] = field(default_factory=list)
    _active_overlay: CrossScreenOverlay | None = None
    _last_active_overlay_name: str | None = None
    _last_evaluated_at: float | None = None

    def register(self, overlay: CrossScreenOverlay) -> None:
        """Register a long-lived overlay implementation."""

        if any(existing.name == overlay.name for existing in self._overlays):
            raise ValueError(f"Duplicate overlay registration: {overlay.name}")

        self._overlays.append(overlay)
        self._overlays.sort(key=lambda entry: entry.priority, reverse=True)

    def evaluate(self, now: float) -> bool:
        """Evaluate active overlay state once for the current runtime tick."""

        if self._last_evaluated_at == now:
            return self._active_overlay is not None

        active_overlay = next(
            (overlay for overlay in self._overlays if overlay.is_active(now)),
            None,
        )
        for overlay in self._overlays:
            if overlay is active_overlay:
                continue
            overlay.on_deactivate(now)

        self._active_overlay = active_overlay
        self._last_active_overlay_name = active_overlay.name if active_overlay else None
        self._last_evaluated_at = now
        return active_overlay is not None

    def render_active(self, now: float) -> bool:
        """Render the cached active overlay, evaluating once when needed."""

        if not self.evaluate(now):
            return False

        assert self._active_overlay is not None
        self._active_overlay.render(now)
        return True

    def update(self, now: float, *, render: bool) -> bool:
        """Compatibility wrapper for older callers using the combined update API."""

        if render:
            return self.render_active(now)
        return self.evaluate(now)

    @property
    def last_active_overlay_name(self) -> str | None:
        """Return the most recent active overlay key, if any."""

        return self._last_active_overlay_name
