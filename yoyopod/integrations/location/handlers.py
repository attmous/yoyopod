"""State helpers for the scaffold location integration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LocationFix:
    """Immutable scaffold location fix shape stored in `location.fix`."""

    lat: float
    lng: float
    altitude: float
    speed_mps: float
    last_fix_at: float


def apply_fix_to_state(app: Any, fix: object | None, *, reason: str = "") -> None:
    """Mirror one GPS fix into scaffold state."""

    if fix is None:
        app.states.set("location.fix", None, {"no_fix_reason": reason or "no_fix"})
        return

    applied_at = time.time()
    location_fix = LocationFix(
        lat=float(getattr(fix, "lat")),
        lng=float(getattr(fix, "lng")),
        altitude=float(getattr(fix, "altitude", 0.0)),
        speed_mps=float(getattr(fix, "speed_mps", getattr(fix, "speed", 0.0))),
        last_fix_at=applied_at,
    )
    app.states.set(
        "location.fix",
        location_fix,
        {
            "lat": location_fix.lat,
            "lng": location_fix.lng,
            "altitude": location_fix.altitude,
            "speed_mps": location_fix.speed_mps,
            "last_fix_at": location_fix.last_fix_at,
        },
    )


def apply_availability_to_state(app: Any, available: bool, *, reason: str = "") -> None:
    """Mirror backend availability into scaffold state."""

    app.states.set(
        "location.backend_available",
        bool(available),
        {"reason": reason} if reason else {},
    )
