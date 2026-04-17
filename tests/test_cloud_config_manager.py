from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yoyopod.cloud.manager as cloud_manager_module
from yoyopod.cloud.client import CloudClientError
from yoyopod.cloud.manager import CloudManager
from yoyopod.cloud.models import CloudAccessToken
from yoyopod.config.manager import ConfigManager


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_config_manager_loads_cloud_backend_and_secrets(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "cloud" / "backend.yaml",
        "\n".join(
            [
                "backend:",
                '  api_base_url: "https://backend.example.test"',
                '  auth_path: "/auth/device"',
                '  refresh_path: "/auth/refresh"',
                '  config_path_template: "/devices/{device_id}/config"',
                "  timeout_seconds: 5.0",
                "  mqtt_broker_port: 2883",
            ]
        ),
    )
    _write_yaml(
        tmp_path / "cloud" / "device.secrets.yaml",
        "\n".join(
            [
                "secrets:",
                '  device_id: "device-123"',
                '  device_secret: "secret-456"',
            ]
        ),
    )

    manager = ConfigManager(config_dir=str(tmp_path))

    cloud = manager.get_cloud_settings()
    assert cloud.backend.api_base_url == "https://backend.example.test"
    assert cloud.backend.auth_path == "/auth/device"
    assert cloud.backend.mqtt_broker_port == 2883
    assert cloud.secrets.device_id == "device-123"
    assert cloud.secrets.device_secret == "secret-456"
    assert manager.get_cloud_device_id() == "device-123"
    assert manager.get_cloud_device_secret() == "secret-456"


def test_apply_cloud_overrides_updates_runtime_values(tmp_path: Path) -> None:
    manager = ConfigManager(config_dir=str(tmp_path))

    unapplied = manager.apply_cloud_overrides(
        {
            "audio": {
                "max_volume": 65,
                "default_volume": 42,
            },
            "messaging": {
                "voice_note_max_duration_seconds": 55,
            },
            "unknown_section": {
                "ignored": True,
            },
        }
    )

    assert manager.get_max_output_volume() == 65
    assert manager.get_default_output_volume() == 42
    assert manager.get_voice_note_max_duration_seconds() == 55
    assert "unknown_section" in unapplied


class _FakeMqttClient:
    def __init__(self, **_kwargs) -> None:
        self.is_connected = False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _FakeApp:
    def __init__(self) -> None:
        self.context = None

    def _queue_main_thread_callback(self, callback) -> None:
        callback()


def test_cloud_manager_backs_off_refresh_after_network_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_yaml(
        tmp_path / "cloud" / "backend.yaml",
        "\n".join(
            [
                "backend:",
                '  api_base_url: "https://backend.example.test"',
                "  claim_retry_seconds: 60",
                "  config_poll_interval_seconds: 300",
            ]
        ),
    )
    _write_yaml(
        tmp_path / "cloud" / "device.secrets.yaml",
        "\n".join(
            [
                "secrets:",
                '  device_id: "device-123"',
                '  device_secret: "secret-456"',
            ]
        ),
    )

    monkeypatch.setattr(cloud_manager_module, "DeviceMqttClient", _FakeMqttClient)

    config_manager = ConfigManager(config_dir=str(tmp_path))
    manager = CloudManager(
        app=_FakeApp(),
        config_manager=config_manager,
        client=SimpleNamespace(),
    )
    manager.prepare_boot()
    manager._access_token = CloudAccessToken(
        access_token="token-123",
        issued_at_epoch=0.0,
        expires_at_epoch=3600.0,
        lifetime_seconds=3600.0,
    )
    manager._next_refresh_at = 0.0
    manager._next_config_poll_at = 0.0

    manager._complete_refresh_token(
        access_token="token-123",
        generation=manager._provisioning_generation,
        completed_at=100.0,
        error=CloudClientError("network down"),
    )

    assert manager.status.cloud_state == "offline"
    assert manager.status.backend_reachable is False
    assert manager._next_refresh_at == 130.0
    assert manager._next_config_poll_at == 130.0
