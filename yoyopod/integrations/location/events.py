"""Typed events owned by the canonical location integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkGpsFixEvent:
    """Published when a GPS coordinate is obtained."""

    lat: float = 0.0
    lng: float = 0.0
    altitude: float = 0.0
    speed: float = 0.0


@dataclass(frozen=True, slots=True)
class NetworkGpsNoFixEvent:
    """Published when a GPS query completes without an active fix."""

    reason: str = ""


__all__ = [
    "NetworkGpsFixEvent",
    "NetworkGpsNoFixEvent",
]
