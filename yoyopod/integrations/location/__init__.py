"""Location integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from yoyopod.backends.location import GpsBackend
from yoyopod.integrations.location.commands import (
    DisableGpsCommand,
    EnableGpsCommand,
    RequestFixCommand,
)
from yoyopod.integrations.location.events import NetworkGpsFixEvent, NetworkGpsNoFixEvent
from yoyopod.integrations.location.handlers import (
    apply_availability_to_state,
    apply_fix_to_state,
)


@dataclass(slots=True)
class LocationIntegration:
    """Runtime handles owned by the scaffold location integration."""

    backend: object


def setup(app: Any, *, backend: object | None = None) -> LocationIntegration:
    """Register scaffold location services and seed initial state."""

    integration = LocationIntegration(backend=backend or GpsBackend(_resolve_network_config(app.config)))
    app.integrations["location"] = integration
    apply_fix_to_state(app, None, reason="not_requested")
    apply_availability_to_state(app, False, reason="idle")
    app.services.register(
        "location",
        "request_fix",
        lambda data: _handle_request_fix(app, integration.backend, data),
    )
    app.services.register(
        "location",
        "enable_gps",
        lambda data: _handle_enable_gps(app, integration.backend, data),
    )
    app.services.register(
        "location",
        "disable_gps",
        lambda data: _handle_disable_gps(app, integration.backend, data),
    )
    return integration


def teardown(app: Any) -> None:
    """Drop the scaffold location integration and close the backend when supported."""

    integration = app.integrations.pop("location", None)
    if integration is None:
        return
    close = getattr(integration.backend, "close", None)
    if callable(close):
        close()


def _handle_request_fix(app: Any, backend: object, command: RequestFixCommand) -> object | None:
    if not isinstance(command, RequestFixCommand):
        raise TypeError("location.request_fix expects RequestFixCommand")
    try:
        fix = backend.get_fix()
    except Exception as exc:
        logger.error("GPS.get_fix failed: {}", exc)
        apply_availability_to_state(app, False, reason=str(exc))
        apply_fix_to_state(app, None, reason=str(exc))
        return None

    apply_availability_to_state(app, True)
    apply_fix_to_state(app, fix, reason="" if fix is not None else "no_fix")
    return fix


def _handle_enable_gps(app: Any, backend: object, command: EnableGpsCommand) -> bool:
    if not isinstance(command, EnableGpsCommand):
        raise TypeError("location.enable_gps expects EnableGpsCommand")
    try:
        enabled = bool(backend.enable())
    except Exception as exc:
        logger.error("GPS.enable failed: {}", exc)
        apply_availability_to_state(app, False, reason=str(exc))
        return False
    apply_availability_to_state(app, enabled)
    return enabled


def _handle_disable_gps(app: Any, backend: object, command: DisableGpsCommand) -> bool:
    if not isinstance(command, DisableGpsCommand):
        raise TypeError("location.disable_gps expects DisableGpsCommand")
    try:
        backend.disable()
    except Exception as exc:
        logger.error("GPS.disable failed: {}", exc)
        apply_availability_to_state(app, False, reason=str(exc))
        return False
    apply_availability_to_state(app, False, reason="disabled")
    return True


def _resolve_network_config(config: object | None) -> object:
    if config is None:
        raise ValueError("location setup requires app.config or an explicit backend")

    get_network_settings = getattr(config, "get_network_settings", None)
    if callable(get_network_settings):
        return get_network_settings()

    network = getattr(config, "network", None)
    if network is None:
        raise ValueError("location setup requires config.network")
    return network


__all__ = [
    "DisableGpsCommand",
    "EnableGpsCommand",
    "LocationIntegration",
    "NetworkGpsFixEvent",
    "NetworkGpsNoFixEvent",
    "RequestFixCommand",
    "setup",
    "teardown",
]
