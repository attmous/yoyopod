"""Focus integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoyopod.integrations.focus.commands import ReleaseFocusCommand, RequestFocusCommand
from yoyopod.integrations.focus.handlers import release_focus, request_focus, seed_focus_state


@dataclass(slots=True)
class FocusIntegration:
    """Runtime handles owned by the scaffold focus integration."""

    owner: str | None = None


def setup(app: Any) -> FocusIntegration:
    """Register scaffold focus services and seed the focus owner state."""

    integration = FocusIntegration()
    app.integrations["focus"] = integration
    seed_focus_state(app)
    app.services.register(
        "focus",
        "request",
        lambda data: request_focus(app, integration, data),
    )
    app.services.register(
        "focus",
        "release",
        lambda data: release_focus(app, integration, data),
    )
    return integration


def teardown(app: Any) -> None:
    """Drop the scaffold focus integration handle."""

    app.integrations.pop("focus", None)


__all__ = [
    "FocusIntegration",
    "ReleaseFocusCommand",
    "RequestFocusCommand",
    "setup",
    "teardown",
]
