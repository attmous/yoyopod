"""Safety policies for low-battery warning and graceful shutdown."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod_cli.config.models import PowerConfig
from yoyopod_cli.pi.support.power_integration.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)
from yoyopod_cli.pi.support.power_integration.models import PowerSnapshot


@dataclass(slots=True)
class PowerSafetyPolicy:
    """Track warning/shutdown state derived from power snapshots."""

    config: PowerConfig
    next_warning_at: float = 0.0
    shutdown_requested: bool = False

    def evaluate(self, snapshot: PowerSnapshot, now: float) -> list[object]:
        """Return policy events triggered by the latest power snapshot."""
        if not self.config.enabled or not snapshot.available:
            return []

        battery_percent = snapshot.battery.level_percent
        if battery_percent is None:
            return []

        has_external_power = bool(snapshot.battery.power_plugged) or bool(snapshot.battery.charging)
        if has_external_power:
            self.next_warning_at = 0.0
            if self.shutdown_requested:
                self.shutdown_requested = False
                return [GracefulShutdownCancelled(reason="external_power_restored")]
            return []

        if (
            self.config.auto_shutdown_enabled
            and battery_percent <= self.config.critical_shutdown_percent
        ):
            if not self.shutdown_requested:
                self.shutdown_requested = True
                return [
                    GracefulShutdownRequested(
                        reason="critical_battery",
                        delay_seconds=self.config.shutdown_delay_seconds,
                        snapshot=snapshot,
                    )
                ]
            return []

        if battery_percent > self.config.low_battery_warning_percent:
            self.next_warning_at = 0.0
            return []

        if now < self.next_warning_at:
            return []

        self.next_warning_at = now + self.config.low_battery_warning_cooldown_seconds
        return [
            LowBatteryWarningRaised(
                threshold_percent=self.config.low_battery_warning_percent,
                battery_percent=battery_percent,
                snapshot=snapshot,
            )
        ]


__all__ = ["PowerSafetyPolicy"]
