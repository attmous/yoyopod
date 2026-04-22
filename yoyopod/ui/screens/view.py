"""Backend-specific screen view lifecycle protocol."""

from __future__ import annotations

from typing import Protocol


class ScreenView(Protocol):
    """Lifecycle shared by backend-specific screen view implementations.

    destroy() is backend-managed teardown for permanently released retained views;
    the current runtime relies on backend clear/reset/cleanup rather than calling it
    during normal screen transitions.
    """

    def build(self) -> None:
        """Create widget/object state once for a retained backend view."""

    def sync(self) -> None:
        """Update and present an already-built view from controller state."""

    def destroy(self) -> None:
        """Backend-managed teardown hook, mainly exercised by lifecycle tests."""
