"""Canonical display integration surface."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from yoyopod.core.events import UserActivityEvent
from yoyopod.integrations.display.commands import (
    SetBrightnessCommand,
    SetIdleTimeoutCommand,
    SleepDisplayCommand,
    WakeDisplayCommand,
)
from yoyopod.integrations.display.handlers import (
    handle_user_activity,
    resolve_idle_timeout_seconds,
    resolve_initial_brightness_percent,
    seed_display_state,
    set_brightness,
    set_idle_timeout,
    sleep_display,
    wake_display,
)
from yoyopod.integrations.display.service import ScreenPowerService


@dataclass(slots=True)
class DisplayIntegration:
    """Runtime handles owned by the scaffold display integration."""

    brightness_percent: int
    idle_timeout_seconds: float
    last_user_activity_at: float | None = None
    last_user_activity_action: str | None = None
    last_wake_reason: str = ""
    last_sleep_reason: str = ""


def setup(
    app: Any,
    *,
    initial_awake: bool = True,
    brightness_percent: int | None = None,
    idle_timeout_seconds: float | None = None,
    monotonic: Any = None,
) -> DisplayIntegration:
    """Register display services and seed initial display state."""

    actual_monotonic = monotonic or time.monotonic
    actual_brightness = (
        resolve_initial_brightness_percent(app.config)
        if brightness_percent is None
        else max(0, min(100, int(brightness_percent)))
    )
    actual_timeout = (
        resolve_idle_timeout_seconds(app.config)
        if idle_timeout_seconds is None
        else max(0.0, float(idle_timeout_seconds))
    )

    integration = DisplayIntegration(
        brightness_percent=actual_brightness,
        idle_timeout_seconds=actual_timeout,
    )
    app.integrations["display"] = integration
    seed_display_state(
        app,
        awake=initial_awake,
        brightness_percent=actual_brightness,
    )
    integration.last_user_activity_at = actual_monotonic()

    app.bus.subscribe(
        UserActivityEvent,
        lambda event: handle_user_activity(
            app,
            integration,
            event,
            now=actual_monotonic(),
        ),
    )
    app.services.register("display", "wake", lambda data: wake_display(app, integration, data))
    app.services.register("display", "sleep", lambda data: sleep_display(app, integration, data))
    app.services.register(
        "display",
        "set_brightness",
        lambda data: set_brightness(app, integration, data),
    )
    app.services.register(
        "display",
        "set_idle_timeout",
        lambda data: set_idle_timeout(integration, data),
    )
    return integration


def teardown(app: Any) -> None:
    """Drop the scaffold display integration handle."""

    app.integrations.pop("display", None)


__all__ = [
    "DisplayIntegration",
    "SetBrightnessCommand",
    "SetIdleTimeoutCommand",
    "SleepDisplayCommand",
    "WakeDisplayCommand",
    "ScreenPowerService",
    "setup",
    "teardown",
]
