"""Typed models for cloud auth and backend status."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CloudAccessToken:
    """Normalized bearer token metadata returned by the backend."""

    access_token: str
    issued_at_epoch: float
    expires_at_epoch: float
    lifetime_seconds: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CloudAccessToken":
        access_token = str(payload.get("access_token") or payload.get("token") or "").strip()
        if not access_token:
            raise ValueError("Cloud auth payload did not include an access token")

        issued_at_epoch = float(payload.get("issued_at_epoch") or time.time())

        expires_at_epoch_raw = payload.get("expires_at_epoch")
        expires_in_raw = payload.get("expires_in_seconds", payload.get("expires_in"))
        if expires_at_epoch_raw is not None:
            expires_at_epoch = float(expires_at_epoch_raw)
        elif expires_in_raw is not None:
            expires_at_epoch = issued_at_epoch + max(1.0, float(expires_in_raw))
        else:
            expires_at_epoch = issued_at_epoch + 3600.0

        lifetime_seconds = max(1.0, expires_at_epoch - issued_at_epoch)
        return cls(
            access_token=access_token,
            issued_at_epoch=issued_at_epoch,
            expires_at_epoch=expires_at_epoch,
            lifetime_seconds=lifetime_seconds,
        )


@dataclass(slots=True)
class CloudStatusSnapshot:
    """Redacted backend/provisioning state mirrored into files and context."""

    device_id: str = ""
    provisioning_state: str = "unprovisioned"
    cloud_state: str = "offline"
    config_source: str = "none"
    config_version: int = 0
    backend_reachable: bool | None = None
    last_successful_sync: str | None = None
    last_error_summary: str = ""
    unapplied_keys: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "provisioning_state": self.provisioning_state,
            "cloud_state": self.cloud_state,
            "config_source": self.config_source,
            "config_version": self.config_version,
            "backend_reachable": self.backend_reachable,
            "last_successful_sync": self.last_successful_sync,
            "last_error_summary": self.last_error_summary,
            "unapplied_keys": list(self.unapplied_keys),
            "updated_at": self.updated_at,
        }
