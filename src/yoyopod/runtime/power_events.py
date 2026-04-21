"""Power-domain EventBus handlers for the runtime layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.power.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class PowerEventHandler:
    """Own app-facing power warning and shutdown event handlers."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def handle_low_battery_warning_event(self, event: LowBatteryWarningRaised) -> None:
        self.app.screen_power_service.handle_low_battery_warning_event(event)

    def handle_graceful_shutdown_requested_event(
        self,
        event: GracefulShutdownRequested,
    ) -> None:
        self.app.shutdown_service.handle_graceful_shutdown_requested_event(event)

    def handle_graceful_shutdown_cancelled_event(
        self,
        event: GracefulShutdownCancelled,
    ) -> None:
        self.app.shutdown_service.handle_graceful_shutdown_cancelled_event(event)
