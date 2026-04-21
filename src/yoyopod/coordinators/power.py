"""
Power telemetry coordination for YoyoPod.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.core import AppContext
from yoyopod.coordinators.registry import CoordinatorRuntime
from yoyopod.coordinators.screen import ScreenCoordinator
from yoyopod.core import EventBus
from yoyopod.power.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
    PowerAvailabilityChanged,
    PowerSnapshotUpdated,
)
from yoyopod.power.models import PowerSnapshot
from yoyopod.power.policies import PowerSafetyPolicy

if TYPE_CHECKING:
    from yoyopod.cloud import CloudManager


class PowerCoordinator:
    """Own power event publishing and UI/runtime power sync."""

    def __init__(
        self,
        runtime: CoordinatorRuntime,
        screen_coordinator: ScreenCoordinator,
        context: AppContext,
        now_provider: Callable[[], float] | None = None,
        cloud_manager: "CloudManager | None" = None,
    ) -> None:
        self.runtime = runtime
        self.screen_coordinator = screen_coordinator
        self.context = context
        self.cloud_manager = cloud_manager
        power_config = runtime.power_manager.config if runtime.power_manager is not None else None
        self.policy = PowerSafetyPolicy(power_config) if power_config is not None else None
        self.now_provider = now_provider or time.monotonic
        self._event_bus: EventBus | None = None
        self._bound = False

    def bind(self, event_bus: EventBus) -> None:
        """Bind typed power event subscriptions once."""
        if self._bound:
            return

        self._event_bus = event_bus
        event_bus.subscribe(PowerSnapshotUpdated, self._on_snapshot_updated)
        event_bus.subscribe(PowerAvailabilityChanged, self._on_availability_changed)
        self._bound = True

    def publish_snapshot(self, snapshot: PowerSnapshot) -> None:
        """Publish a refreshed power snapshot onto the event bus."""
        if self._event_bus is None:
            raise RuntimeError("PowerCoordinator is not bound to an EventBus")

        self._event_bus.publish(PowerSnapshotUpdated(snapshot=snapshot))

    def publish_availability_change(self, available: bool, reason: str = "") -> None:
        """Publish power backend availability changes onto the event bus."""
        if self._event_bus is None:
            raise RuntimeError("PowerCoordinator is not bound to an EventBus")

        self._event_bus.publish(PowerAvailabilityChanged(available=available, reason=reason))

    def _on_snapshot_updated(self, event: PowerSnapshotUpdated) -> None:
        self.handle_snapshot_updated(event.snapshot)

    def _on_availability_changed(self, event: PowerAvailabilityChanged) -> None:
        self.handle_availability_change(event.available, event.reason)

    def handle_snapshot_updated(self, snapshot: PowerSnapshot) -> None:
        """Apply the latest power telemetry to runtime and UI state."""
        previous_signature = self._snapshot_signature(self.runtime.power_snapshot)
        current_screen = (
            self.runtime.screen_manager.get_current_screen()
            if self.runtime.screen_manager is not None
            else None
        )
        current_route_name = current_screen.route_name if current_screen is not None else None

        self.runtime.set_power_snapshot(snapshot)
        self.context.update_power_status(snapshot)

        current_signature = self._snapshot_signature(snapshot)

        if current_signature != previous_signature or current_route_name == "power":
            self.screen_coordinator.refresh_current_screen()

        if self.cloud_manager is not None:
            level = snapshot.battery.level_percent
            charging = snapshot.battery.charging
            if level is not None:
                self.cloud_manager.publish_battery(
                    level=round(level),
                    charging=bool(charging),
                    now=self.now_provider(),
                )

        if self.policy is None or self._event_bus is None:
            return

        for event in self.policy.evaluate(snapshot, now=self.now_provider()):
            self._event_bus.publish(event)

    def handle_availability_change(self, available: bool, reason: str) -> None:
        """Track power backend reachability for the runtime."""
        self.runtime.set_power_available(available)
        if available:
            logger.info(f"Power backend available ({reason or 'ready'})")
            return

        logger.warning(f"Power backend unavailable ({reason or 'unknown'})")
        if self.policy is not None:
            self.policy.shutdown_requested = False
            self.policy.next_warning_at = 0.0

    @staticmethod
    def _snapshot_signature(snapshot: PowerSnapshot | None) -> tuple[object, ...] | None:
        """Return the stable, user-visible subset of a power snapshot."""
        if snapshot is None:
            return None

        return (
            snapshot.available,
            snapshot.error,
            snapshot.device.model,
            snapshot.device.firmware_version,
            snapshot.battery.level_percent,
            snapshot.battery.voltage_volts,
            snapshot.battery.charging,
            snapshot.battery.power_plugged,
            snapshot.battery.allow_charging,
            snapshot.battery.output_enabled,
            snapshot.battery.temperature_celsius,
            snapshot.rtc.time,
            snapshot.rtc.alarm_enabled,
            snapshot.rtc.alarm_time,
            snapshot.rtc.alarm_repeat_mask,
            snapshot.rtc.adjust_ppm,
            snapshot.shutdown.safe_shutdown_level_percent,
            snapshot.shutdown.safe_shutdown_delay_seconds,
        )
