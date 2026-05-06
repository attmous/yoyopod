"""PiSugar power backend adapters."""

from __future__ import annotations

from yoyopod_cli.pi.support.power_backend.pisugar import (
    PiSugarAutoTransport,
    PiSugarBackend,
    PiSugarTCPTransport,
    PiSugarTransport,
    PiSugarUnixTransport,
    PowerBackend,
    PowerTransportError,
    build_pisugar_transport,
)
from yoyopod_cli.pi.support.power_backend.watchdog import PiSugarWatchdog, WatchdogCommandError
from yoyopod_cli.pi.support.power_integration.models import PowerSnapshot

__all__ = [
    "PiSugarAutoTransport",
    "PiSugarBackend",
    "PiSugarTCPTransport",
    "PiSugarTransport",
    "PiSugarUnixTransport",
    "PiSugarWatchdog",
    "PowerBackend",
    "PowerSnapshot",
    "PowerTransportError",
    "WatchdogCommandError",
    "build_pisugar_transport",
]
