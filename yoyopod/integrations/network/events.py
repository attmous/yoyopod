"""Typed events owned by the canonical network integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkModemReadyEvent:
    """Published when the modem is initialized and registered."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkRegisteredEvent:
    """Published when the modem attaches to a cellular network."""

    carrier: str = ""
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class NetworkPppUpEvent:
    """Published when PPP data session is established."""

    connection_type: str = "4g"


@dataclass(frozen=True, slots=True)
class NetworkPppDownEvent:
    """Published when PPP data session drops."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class NetworkSignalUpdateEvent:
    """Published when signal strength changes."""

    bars: int = 0
    csq: int = 0


__all__ = [
    "NetworkModemReadyEvent",
    "NetworkPppDownEvent",
    "NetworkPppUpEvent",
    "NetworkRegisteredEvent",
    "NetworkSignalUpdateEvent",
]
