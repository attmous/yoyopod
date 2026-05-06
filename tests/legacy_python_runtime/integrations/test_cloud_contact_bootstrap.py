"""Focused tests for one-time local-contact bootstrap into backend authority."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.integrations.cloud.manager import CloudManager
from yoyopod.integrations.cloud.models import CloudAccessToken
from yoyopod.integrations.contacts.models import Contact


class _FakePeopleDirectory:
    def __init__(self) -> None:
        self.contacts = [
            Contact(
                name="Hagar",
                sip_address="sip:hagarmo@sip.linphone.org",
                favorite=True,
                notes="Mama",
            )
        ]
        self.speed_dial = {1: "sip:hagarmo@sip.linphone.org"}

    def get_local_contacts(self) -> list[Contact]:
        return list(self.contacts)


class _FakeConfigManager:
    def __init__(self) -> None:
        self.cloud_secrets_error = ""
        self._backend = SimpleNamespace(
            api_base_url="https://yoyopod.moraouf.net",
            auth_path="/v1/auth/device",
            refresh_path="/v1/auth/device/refresh",
            config_path_template="/v1/devices/{device_id}/config",
            contacts_bootstrap_path_template="/v1/devices/{device_id}/contacts/bootstrap",
            timeout_seconds=3.0,
            config_poll_interval_seconds=300,
            claim_retry_seconds=60,
            battery_report_interval_seconds=60,
        )

    def get_cloud_settings(self):
        return SimpleNamespace(backend=self._backend)

    def get_media_settings(self):
        return SimpleNamespace(
            music=SimpleNamespace(
                remote_cache_dir="data/media/remote_cache",
                remote_cache_max_bytes=64 * 1024 * 1024,
            )
        )

    def get_cloud_device_id(self) -> str:
        return "YYP-DEV-0001"

    def get_cloud_device_secret(self) -> str:
        return "secret"

    def load_cloud_config(self) -> None:
        return None

    def resolve_runtime_path(self, value: str) -> str:
        return value


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def bootstrap_contacts(self, *, access_token: str, device_id: str, entries: list[dict[str, object]]):
        self.calls.append(
            {
                "access_token": access_token,
                "device_id": device_id,
                "entries": entries,
            }
        )
        return {"success": True, "importedCount": 1, "skippedCount": 0}


class _FakeApp:
    def __init__(self) -> None:
        self.people_directory = _FakePeopleDirectory()

    def _queue_main_thread_callback(self, callback):
        callback()


def test_local_contacts_bootstrap_payload_uses_seeded_contact_fields() -> None:
    app = _FakeApp()
    manager = CloudManager(
        app=app,
        config_manager=_FakeConfigManager(),
        client=_FakeClient(),
    )
    manager._access_token = CloudAccessToken(
        access_token="token-123",
        issued_at_epoch=1.0,
        expires_at_epoch=3601.0,
        lifetime_seconds=3600.0,
    )

    entries = manager._local_contacts_bootstrap_entries()

    assert entries == [
        {
            "name": "Hagar",
            "phoneNumber": None,
            "sipAddress": "sip:hagarmo@sip.linphone.org",
            "relationship": "Mama",
            "isPrimary": True,
            "canCall": True,
            "canReceive": True,
            "quickDial": 1,
        }
    ]


def test_bootstrap_runs_once_when_backend_contacts_are_empty() -> None:
    app = _FakeApp()
    client = _FakeClient()
    manager = CloudManager(
        app=app,
        config_manager=_FakeConfigManager(),
        client=client,
    )
    manager._access_token = CloudAccessToken(
        access_token="token-123",
        issued_at_epoch=1.0,
        expires_at_epoch=3601.0,
        lifetime_seconds=3600.0,
    )
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._maybe_bootstrap_local_contacts(payload={"contacts": {"entries": []}}, completed_at=10.0)
    manager._maybe_bootstrap_local_contacts(payload={"contacts": {"entries": []}}, completed_at=11.0)

    assert len(client.calls) == 1
    assert client.calls[0]["device_id"] == "YYP-DEV-0001"
