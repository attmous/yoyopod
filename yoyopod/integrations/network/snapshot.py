"""Rust-owned network snapshot helpers for the worker-backed runtime seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CELLULAR_VISIBLE_STATES = {
    "probing",
    "ready",
    "registering",
    "registered",
    "ppp_starting",
    "online",
    "ppp_stopping",
    "recovering",
    "degraded",
}


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_text_or_none(value: object) -> str | None:
    text = _coerce_text(value)
    return text or None


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


@dataclass(frozen=True, slots=True)
class RustNetworkSignalSnapshot:
    """Signal facts emitted by the Rust network host."""

    csq: int | None = None
    bars: int = 0

    @classmethod
    def from_payload(cls, payload: object) -> "RustNetworkSignalSnapshot":
        data = _coerce_mapping(payload)
        csq_value = data.get("csq")
        csq = None if csq_value is None else max(0, _coerce_int(csq_value))
        return cls(
            csq=csq,
            bars=max(0, min(4, _coerce_int(data.get("bars"), 0))),
        )


@dataclass(frozen=True, slots=True)
class RustNetworkPppSnapshot:
    """PPP facts emitted by the Rust network host."""

    up: bool = False
    interface: str = ""
    pid: int | None = None
    default_route_owned: bool = False
    last_failure: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> "RustNetworkPppSnapshot":
        data = _coerce_mapping(payload)
        pid_value = data.get("pid")
        pid = None if pid_value is None else max(0, _coerce_int(pid_value))
        return cls(
            up=_coerce_bool(data.get("up")),
            interface=_coerce_text(data.get("interface")),
            pid=pid,
            default_route_owned=_coerce_bool(data.get("default_route_owned")),
            last_failure=_coerce_text(data.get("last_failure")),
        )


@dataclass(frozen=True, slots=True)
class RustNetworkGpsSnapshot:
    """GPS facts emitted by the Rust network host."""

    has_fix: bool = False
    lat: float | None = None
    lng: float | None = None
    altitude: float | None = None
    speed: float | None = None
    timestamp: str | None = None
    last_query_result: str = "idle"

    @classmethod
    def from_payload(cls, payload: object) -> "RustNetworkGpsSnapshot":
        data = _coerce_mapping(payload)
        return cls(
            has_fix=_coerce_bool(data.get("has_fix")),
            lat=_coerce_float(data.get("lat")),
            lng=_coerce_float(data.get("lng")),
            altitude=_coerce_float(data.get("altitude")),
            speed=_coerce_float(data.get("speed")),
            timestamp=_coerce_text_or_none(data.get("timestamp")),
            last_query_result=_coerce_text(data.get("last_query_result")) or "idle",
        )


@dataclass(frozen=True, slots=True)
class RustNetworkSnapshot:
    """Canonical Rust-defined network snapshot cached by Python."""

    enabled: bool = False
    gps_enabled: bool = False
    config_dir: str = ""
    state: str = "off"
    sim_ready: bool = False
    registered: bool = False
    carrier: str = ""
    network_type: str = ""
    signal: RustNetworkSignalSnapshot = RustNetworkSignalSnapshot()
    ppp: RustNetworkPppSnapshot = RustNetworkPppSnapshot()
    gps: RustNetworkGpsSnapshot = RustNetworkGpsSnapshot()
    recovering: bool = False
    retryable: bool = False
    reconnect_attempts: int = 0
    next_retry_at_ms: int | None = None
    error_code: str = ""
    error_message: str = ""
    updated_at_ms: int = 0

    @classmethod
    def from_payload(cls, payload: object) -> "RustNetworkSnapshot":
        data = _coerce_mapping(payload)
        next_retry_at_ms_value = data.get("next_retry_at_ms")
        next_retry_at_ms = (
            None
            if next_retry_at_ms_value is None
            else max(0, _coerce_int(next_retry_at_ms_value))
        )
        return cls(
            enabled=_coerce_bool(data.get("enabled")),
            gps_enabled=_coerce_bool(data.get("gps_enabled")),
            config_dir=_coerce_text(data.get("config_dir")),
            state=_coerce_text(data.get("state")) or "off",
            sim_ready=_coerce_bool(data.get("sim_ready")),
            registered=_coerce_bool(data.get("registered")),
            carrier=_coerce_text(data.get("carrier")),
            network_type=_coerce_text(data.get("network_type")),
            signal=RustNetworkSignalSnapshot.from_payload(data.get("signal")),
            ppp=RustNetworkPppSnapshot.from_payload(data.get("ppp")),
            gps=RustNetworkGpsSnapshot.from_payload(data.get("gps")),
            recovering=_coerce_bool(data.get("recovering")),
            retryable=_coerce_bool(data.get("retryable")),
            reconnect_attempts=max(0, _coerce_int(data.get("reconnect_attempts"), 0)),
            next_retry_at_ms=next_retry_at_ms,
            error_code=_coerce_text(data.get("error_code")),
            error_message=_coerce_text(data.get("error_message")),
            updated_at_ms=max(0, _coerce_int(data.get("updated_at_ms"), 0)),
        )

    @property
    def connected(self) -> bool:
        """Return True when Rust reports PPP as up."""

        return self.enabled and self.ppp.up

    @property
    def signal_bars(self) -> int:
        """Return UI-safe cellular bars."""

        return max(0, min(4, self.signal.bars))

    @property
    def gps_has_fix(self) -> bool:
        """Return True when GPS is enabled and a fix is present."""

        return self.enabled and self.gps_enabled and self.gps.has_fix

    @property
    def connection_type(self) -> str:
        """Map the Rust snapshot to the current app-facing connection type."""

        if not self.enabled:
            return "none"
        if self.connected or self._has_cellular_visibility():
            return "4g"
        return "none"

    def _has_cellular_visibility(self) -> bool:
        return (
            self.registered
            or self.sim_ready
            or bool(self.carrier)
            or bool(self.network_type)
            or self.signal_bars > 0
            or self.state in _CELLULAR_VISIBLE_STATES
        )

__all__ = [
    "RustNetworkGpsSnapshot",
    "RustNetworkPppSnapshot",
    "RustNetworkSignalSnapshot",
    "RustNetworkSnapshot",
]
