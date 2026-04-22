"""PiSugar power backend adapters."""

from __future__ import annotations

from yoyopod.backends.power.pisugar import (
    PiSugarAutoTransport,
    PiSugarBackend,
    PiSugarTCPTransport,
    PiSugarTransport,
    PiSugarUnixTransport,
    PowerBackend,
    PowerTransportError,
    build_pisugar_transport,
)
from yoyopod.backends.power.watchdog import PiSugarWatchdog, WatchdogCommandError
from yoyopod.integrations.power.models import PowerSnapshot

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
