"""Typed bus subscription wiring for core-owned runtime helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.core import ScreenChangedEvent, UserActivityEvent
from yoyopod.integrations.location.events import (
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
)
from yoyopod.integrations.network.events import (
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkSignalUpdateEvent,
)
from yoyopod.integrations.power.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class RuntimeEventSubscriptions:
    """Register typed runtime event handlers on the shared bus."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def register(self) -> None:
        """Subscribe runtime services and handlers to the shared bus."""

        bus = self.app.bus
        bus.subscribe(
            ScreenChangedEvent,
            self.app.screen_power_service.handle_screen_changed_event,
        )
        bus.subscribe(
            UserActivityEvent,
            self.app.screen_power_service.handle_user_activity_event,
        )
        bus.subscribe(
            LowBatteryWarningRaised,
            self.app.screen_power_service.handle_low_battery_warning_event,
        )
        bus.subscribe(
            GracefulShutdownRequested,
            self.app.shutdown_service.handle_graceful_shutdown_requested_event,
        )
        bus.subscribe(
            GracefulShutdownCancelled,
            self.app.shutdown_service.handle_graceful_shutdown_cancelled_event,
        )
        bus.subscribe(NetworkPppUpEvent, self.app.network_events.handle_network_ppp_up)
        bus.subscribe(
            NetworkSignalUpdateEvent,
            self.app.network_events.handle_network_signal_update,
        )
        bus.subscribe(
            NetworkGpsFixEvent,
            self.app.network_events.handle_network_gps_fix,
        )
        bus.subscribe(
            NetworkGpsNoFixEvent,
            self.app.network_events.handle_network_gps_no_fix,
        )
        bus.subscribe(
            NetworkPppDownEvent,
            self.app.network_events.handle_network_ppp_down,
        )


__all__ = ["RuntimeEventSubscriptions"]
