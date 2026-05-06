"""Power integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from yoyopod_cli.pi.support.power_integration.commands import SetRtcAlarmCommand
from yoyopod_cli.pi.support.power_integration.handlers import apply_snapshot
from yoyopod_cli.pi.support.power_integration.poller import PowerPoller

if TYPE_CHECKING:
    from yoyopod_cli.pi.support.power_integration.manager import PowerManager
    from yoyopod_cli.pi.support.power_integration.models import (
        BatteryState,
        PowerDeviceInfo,
        PowerSnapshot,
        RTCState,
        ShutdownState,
    )


_PUBLIC_EXPORTS = {
    "BatteryState": ("yoyopod_cli.pi.support.power_integration.models", "BatteryState"),
    "GracefulShutdownCancelled": (
        "yoyopod_cli.pi.support.power_integration.events",
        "GracefulShutdownCancelled",
    ),
    "GracefulShutdownRequested": (
        "yoyopod_cli.pi.support.power_integration.events",
        "GracefulShutdownRequested",
    ),
    "LowBatteryWarningRaised": (
        "yoyopod_cli.pi.support.power_integration.events",
        "LowBatteryWarningRaised",
    ),
    "PowerDeviceInfo": ("yoyopod_cli.pi.support.power_integration.models", "PowerDeviceInfo"),
    "PowerManager": ("yoyopod_cli.pi.support.power_integration.manager", "PowerManager"),
    "PendingShutdown": ("yoyopod_cli.pi.support.power_integration.models", "PendingShutdown"),
    "PowerAlert": ("yoyopod_cli.pi.support.power_integration.models", "PowerAlert"),
    "PowerSafetyPolicy": ("yoyopod_cli.pi.support.power_integration.policies", "PowerSafetyPolicy"),
    "PowerRuntimeService": (
        "yoyopod_cli.pi.support.power_integration.service",
        "PowerRuntimeService",
    ),
    "PowerSnapshot": ("yoyopod_cli.pi.support.power_integration.models", "PowerSnapshot"),
    "RTCState": ("yoyopod_cli.pi.support.power_integration.models", "RTCState"),
    "ShutdownState": ("yoyopod_cli.pi.support.power_integration.models", "ShutdownState"),
}


def __getattr__(name: str) -> Any:
    """Load canonical public power exports lazily to avoid backend import cycles."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


@dataclass(slots=True)
class PowerIntegration:
    """Runtime handles owned by the scaffold power integration."""

    backend: object
    poller: PowerPoller


__all__ = [
    "BatteryState",
    "GracefulShutdownCancelled",
    "GracefulShutdownRequested",
    "LowBatteryWarningRaised",
    "PendingShutdown",
    "PowerAlert",
    "PowerDeviceInfo",
    "PowerIntegration",
    "PowerManager",
    "PowerRuntimeService",
    "PowerSafetyPolicy",
    "PowerSnapshot",
    "RTCState",
    "SetRtcAlarmCommand",
    "ShutdownState",
    "setup",
    "teardown",
]


def setup(
    app: Any,
    *,
    config: object,
    backend: object | None = None,
    poll_interval_seconds: float = 30.0,
) -> PowerIntegration:
    """Register the scaffold power services and poller."""

    from yoyopod_cli.pi.support.power_backend import PiSugarBackend

    actual_backend = backend or PiSugarBackend(config)
    poller = PowerPoller(
        backend=actual_backend,
        scheduler=app.scheduler,
        on_snapshot=lambda snapshot: apply_snapshot(app, snapshot),
        poll_interval_seconds=poll_interval_seconds,
        background=getattr(app, "background", None),
    )
    integration = PowerIntegration(backend=actual_backend, poller=poller)

    app.integrations["power"] = integration

    app.services.register(
        "power",
        "refresh_snapshot",
        lambda data: apply_snapshot(app, actual_backend.get_snapshot()),
    )
    app.services.register(
        "power",
        "sync_time_to_rtc",
        lambda data: _sync_to_rtc(app, actual_backend),
    )
    app.services.register(
        "power",
        "sync_time_from_rtc",
        lambda data: _sync_from_rtc(app, actual_backend),
    )
    app.services.register(
        "power",
        "set_rtc_alarm",
        lambda data: _set_rtc_alarm(app, actual_backend, data),
    )
    app.services.register(
        "power",
        "disable_rtc_alarm",
        lambda data: _disable_rtc_alarm(app, actual_backend),
    )

    return integration


def teardown(app: Any) -> None:
    """Stop the scaffold poller and drop the integration handle."""

    integration = app.integrations.pop("power", None)
    if integration is not None:
        integration.poller.stop()


def _sync_to_rtc(app: Any, backend: object) -> object:
    backend.sync_time_to_rtc()
    return apply_snapshot(app, backend.get_snapshot())


def _sync_from_rtc(app: Any, backend: object) -> object:
    backend.sync_time_from_rtc()
    return apply_snapshot(app, backend.get_snapshot())


def _set_rtc_alarm(app: Any, backend: object, data: SetRtcAlarmCommand) -> object:
    if not isinstance(data, SetRtcAlarmCommand):
        raise TypeError("power.set_rtc_alarm expects SetRtcAlarmCommand")
    backend.set_rtc_alarm(data.when, data.repeat_mask)
    return apply_snapshot(app, backend.get_snapshot())


def _disable_rtc_alarm(app: Any, backend: object) -> object:
    backend.disable_rtc_alarm()
    return apply_snapshot(app, backend.get_snapshot())
