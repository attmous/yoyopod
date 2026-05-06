"""Tests for typed runtime bus subscription wiring."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core import ScreenChangedEvent, UserActivityEvent, WorkerMessageReceivedEvent
from yoyopod.core.event_subscriptions import RuntimeEventSubscriptions
from yoyopod.integrations.power.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)


def test_runtime_event_subscriptions_register_all_runtime_handlers() -> None:
    """App runtime wiring should subscribe the expected event handlers exactly once."""

    subscriptions: list[tuple[type[object], object]] = []
    app = SimpleNamespace(
        bus=SimpleNamespace(
            subscribe=lambda event_type, handler: subscriptions.append((event_type, handler))
        ),
        screen_power_service=SimpleNamespace(
            handle_screen_changed_event="screen_changed",
            handle_user_activity_event="user_activity",
            handle_low_battery_warning_event="low_battery",
        ),
        shutdown_service=SimpleNamespace(
            handle_graceful_shutdown_requested_event="shutdown_requested",
            handle_graceful_shutdown_cancelled_event="shutdown_cancelled",
        ),
        rust_ui_host=None,
    )

    RuntimeEventSubscriptions(app).register()

    assert subscriptions == [
        (ScreenChangedEvent, "screen_changed"),
        (UserActivityEvent, "user_activity"),
        (LowBatteryWarningRaised, "low_battery"),
        (GracefulShutdownRequested, "shutdown_requested"),
        (GracefulShutdownCancelled, "shutdown_cancelled"),
    ]


def test_runtime_event_subscriptions_register_rust_ui_host_when_present() -> None:
    subscriptions: list[tuple[type[object], object]] = []

    def rust_ui_message(_event: object) -> None:
        return None

    rust_ui_host = SimpleNamespace(handle_worker_message=rust_ui_message)
    app = SimpleNamespace(
        bus=SimpleNamespace(
            subscribe=lambda event_type, handler: subscriptions.append((event_type, handler))
        ),
        screen_power_service=SimpleNamespace(
            handle_screen_changed_event="screen_changed",
            handle_user_activity_event="user_activity",
            handle_low_battery_warning_event="low_battery",
        ),
        shutdown_service=SimpleNamespace(
            handle_graceful_shutdown_requested_event="shutdown_requested",
            handle_graceful_shutdown_cancelled_event="shutdown_cancelled",
        ),
        rust_ui_host=rust_ui_host,
    )

    RuntimeEventSubscriptions(app).register()

    assert (WorkerMessageReceivedEvent, rust_ui_message) in subscriptions
