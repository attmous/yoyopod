"""HTTP client for claimed-device cloud auth and config fetches."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from yoyopod.cloud.models import CloudAccessToken


@dataclass(slots=True)
class CloudClientError(RuntimeError):
    """Structured cloud/backend failure surfaced to the coordinator."""

    message: str
    status_code: int | None = None
    error_code: str | None = None
    payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        code = f" [{self.error_code}]" if self.error_code else ""
        status = f" ({self.status_code})" if self.status_code is not None else ""
        return f"{self.message}{code}{status}"


class CloudDeviceClient:
    """Small HTTP client for device auth, refresh, and config fetch."""

    def __init__(
        self,
        *,
        base_url: str,
        auth_path: str,
        refresh_path: str,
        config_path_template: str,
        contacts_bootstrap_path_template: str,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_path = auth_path
        self.refresh_path = refresh_path
        self.config_path_template = config_path_template
        self.contacts_bootstrap_path_template = contacts_bootstrap_path_template
        self.timeout_seconds = max(0.1, float(timeout_seconds))

    def authenticate(self, *, device_id: str, device_secret: str) -> CloudAccessToken:
        payload = self._request_json(
            "POST",
            self._url(self.auth_path),
            json={
                "device_id": device_id,
                "device_secret": device_secret,
            },
        )
        return CloudAccessToken.from_payload(payload)

    def refresh(self, *, access_token: str) -> CloudAccessToken:
        payload = self._request_json(
            "POST",
            self._url(self.refresh_path),
            headers=self._auth_headers(access_token),
        )
        return CloudAccessToken.from_payload(payload)

    def fetch_config(self, *, access_token: str, device_id: str) -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            self._url(self.config_path_template.format(device_id=device_id)),
            headers=self._auth_headers(access_token),
        )
        if not isinstance(payload, dict):
            raise CloudClientError("Malformed cloud config payload", payload={"payload": payload})
        return payload

    def bootstrap_contacts(
        self,
        *,
        access_token: str,
        device_id: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._request_json(
            "POST",
            self._url(self.contacts_bootstrap_path_template.format(device_id=device_id)),
            headers=self._auth_headers(access_token),
            json={"entries": entries},
        )
        if not isinstance(payload, dict):
            raise CloudClientError(
                "Malformed cloud contact bootstrap payload",
                payload={"payload": payload},
            )
        return payload

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise CloudClientError(str(exc)) from exc

        payload: dict[str, Any] | None
        try:
            decoded = response.json()
            payload = decoded if isinstance(decoded, dict) else {"payload": decoded}
        except ValueError:
            payload = None

        if response.status_code >= 400:
            error_code = None
            message = response.reason or "Cloud request failed"
            if payload is not None:
                error_code = str(payload.get("error_code") or payload.get("code") or "").strip() or None
                message = str(payload.get("message") or payload.get("detail") or message)
            raise CloudClientError(
                message=message,
                status_code=response.status_code,
                error_code=error_code,
                payload=payload,
            )

        if payload is None:
            raise CloudClientError(
                message="Cloud response was not valid JSON",
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _auth_headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"
