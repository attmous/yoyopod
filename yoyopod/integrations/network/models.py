"""Typed models for the canonical network integration seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ModemPhase(str, Enum):
    """Modem lifecycle phases."""

    OFF = "off"
    PROBING = "probing"
    READY = "ready"
    REGISTERING = "registering"
    REGISTERED = "registered"
    PPP_STARTING = "ppp_starting"
    ONLINE = "online"
    PPP_STOPPING = "ppp_stopping"


@dataclass(frozen=True, slots=True)
class SignalInfo:
    """Parsed AT+CSQ response."""

    csq: int = 0

    @property
    def bars(self) -> int:
        """Map raw CSQ value (0-31, 99) to 0-4 signal bars."""

        if self.csq == 99 or self.csq < 1:
            return 0
        if self.csq < 10:
            return 1
        if self.csq < 15:
            return 2
        if self.csq < 25:
            return 3
        return 4


@dataclass(frozen=True, slots=True)
class GpsCoordinate:
    """Parsed AT+CGPSINFO response."""

    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass(slots=True)
class ModemState:
    """Mutable current modem state snapshot."""

    phase: ModemPhase = ModemPhase.OFF
    signal: Optional[SignalInfo] = None
    carrier: str = ""
    network_type: str = ""
    sim_ready: bool = False
    gps: Optional[GpsCoordinate] = None
    error: str = ""


__all__ = ["GpsCoordinate", "ModemPhase", "ModemState", "SignalInfo"]
