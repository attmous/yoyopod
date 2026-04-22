"""Handlers for the scaffold display integration."""

from __future__ import annotations

from typing import Any

from yoyopod.core.events import UserActivityEvent
from yoyopod.integrations.display.commands import (
    SetBrightnessCommand,
    SetIdleTimeoutCommand,
    SleepDisplayCommand,
    WakeDisplayCommand,
)


def seed_display_state(
    app: Any,
    *,
    awake: bool,
    brightness_percent: int,
) -> None:
    """Seed the scaffold display state rows."""

    app.states.set("display.awake", awake)
    app.states.set("display.brightness_percent", brightness_percent)


def wake_display(app: Any, integration: Any, command: WakeDisplayCommand) -> bool:
    """Wake the display and record the command reason."""

    if not isinstance(command, WakeDisplayCommand):
        raise TypeError("display.wake expects WakeDisplayCommand")
    integration.last_wake_reason = command.reason
    app.states.set("display.awake", True)
    return True


def sleep_display(app: Any, integration: Any, command: SleepDisplayCommand) -> bool:
    """Put the display to sleep and record the command reason."""

    if not isinstance(command, SleepDisplayCommand):
        raise TypeError("display.sleep expects SleepDisplayCommand")
    integration.last_sleep_reason = command.reason
    app.states.set("display.awake", False)
    return False


def set_brightness(app: Any, integration: Any, command: SetBrightnessCommand) -> int:
    """Update the in-memory display brightness and reflected scaffold state."""

    if not isinstance(command, SetBrightnessCommand):
        raise TypeError("display.set_brightness expects SetBrightnessCommand")
    integration.brightness_percent = _normalize_brightness_percent(command.percent)
    app.states.set("display.brightness_percent", integration.brightness_percent)
    return integration.brightness_percent


def set_idle_timeout(integration: Any, command: SetIdleTimeoutCommand) -> float:
    """Update the in-memory display idle timeout."""

    if not isinstance(command, SetIdleTimeoutCommand):
        raise TypeError("display.set_idle_timeout expects SetIdleTimeoutCommand")
    integration.idle_timeout_seconds = max(0.0, float(command.timeout_seconds))
    return integration.idle_timeout_seconds


def handle_user_activity(
    app: Any,
    integration: Any,
    event: UserActivityEvent,
    *,
    now: float,
) -> None:
    """Record user activity and wake the display if it is asleep."""

    integration.last_user_activity_at = now
    integration.last_user_activity_action = event.action_name
    if not app.states.get_value("display.awake", False):
        app.states.set("display.awake", True)


def resolve_initial_brightness_percent(config: object | None, fallback: int = 80) -> int:
    """Resolve the initial brightness from scaffold config or a fallback."""

    display = getattr(config, "display", None)
    value = getattr(display, "brightness", fallback)
    return _normalize_brightness_percent(value)


def resolve_idle_timeout_seconds(config: object | None, fallback: float = 300.0) -> float:
    """Resolve the effective display timeout using the live runtime precedence."""

    display = getattr(config, "display", None)
    ui = getattr(config, "ui", None)
    display_timeout = max(
        0.0,
        float(getattr(display, "backlight_timeout_seconds", 0.0) or 0.0),
    )
    if display_timeout > 0.0:
        return display_timeout
    return max(
        0.0,
        float(getattr(ui, "screen_timeout_seconds", fallback) or fallback),
    )


def _normalize_brightness_percent(value: object) -> int:
    return max(0, min(100, int(value)))
