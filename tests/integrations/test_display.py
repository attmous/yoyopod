"""Tests for the scaffold display integration."""

from __future__ import annotations

from types import SimpleNamespace

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.core import UserActivityEvent
from yoyopod.integrations.display import (
    SetBrightnessCommand,
    SetIdleTimeoutCommand,
    SleepDisplayCommand,
    WakeDisplayCommand,
    setup,
    teardown,
)


def test_display_setup_seeds_state_from_config_defaults() -> None:
    app = build_test_app()
    app.config = SimpleNamespace(
        display=SimpleNamespace(brightness=65, backlight_timeout_seconds=45),
        ui=SimpleNamespace(screen_timeout_seconds=300),
    )

    integration = setup(app)

    assert integration is app.integrations["display"]
    assert integration.brightness_percent == 65
    assert integration.idle_timeout_seconds == 45.0
    assert app.states.get_value("display.awake") is True
    assert app.states.get_value("display.brightness_percent") == 65


def test_display_services_update_state_and_runtime_values() -> None:
    app = build_test_app()
    integration = setup(app, brightness_percent=20, idle_timeout_seconds=10.0)

    slept = app.services.call("display", "sleep", SleepDisplayCommand(reason="idle"))
    brightness = app.services.call(
        "display",
        "set_brightness",
        SetBrightnessCommand(percent=120),
    )
    timeout = app.services.call(
        "display",
        "set_idle_timeout",
        SetIdleTimeoutCommand(timeout_seconds=-5.0),
    )
    woke = app.services.call("display", "wake", WakeDisplayCommand(reason="button"))

    assert slept is False
    assert woke is True
    assert brightness == 100
    assert timeout == 0.0
    assert integration.last_sleep_reason == "idle"
    assert integration.last_wake_reason == "button"
    assert integration.brightness_percent == 100
    assert integration.idle_timeout_seconds == 0.0
    assert app.states.get_value("display.awake") is True
    assert app.states.get_value("display.brightness_percent") == 100


def test_display_user_activity_wakes_sleeping_display() -> None:
    app = build_test_app()
    integration = setup(app, initial_awake=False, brightness_percent=55)

    app.bus.publish(UserActivityEvent(action_name="dial"))
    drain_all(app)

    assert app.states.get_value("display.awake") is True
    assert integration.last_user_activity_action == "dial"
    assert integration.last_user_activity_at is not None


def test_display_services_reject_wrong_payload_types() -> None:
    app = build_test_app()
    setup(app)

    try:
        app.services.call("display", "set_brightness", {"percent": 50})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "display.set_brightness expects SetBrightnessCommand"
    else:
        raise AssertionError("display.set_brightness accepted an untyped payload")

    teardown(app)
    assert "display" not in app.integrations
