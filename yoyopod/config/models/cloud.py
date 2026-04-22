"""Cloud backend and runtime secret configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class CloudBackendConfig:
    """Tracked cloud/backend endpoints, polling, cache, and MQTT transport."""

    api_base_url: str = config_value(
        default="https://yoyopod.moraouf.net",
        env="YOYOPOD_CLOUD_API_BASE_URL",
    )
    auth_path: str = "/v1/auth/device"
    refresh_path: str = "/v1/auth/device/refresh"
    config_path_template: str = "/v1/devices/{device_id}/config"
    contacts_bootstrap_path_template: str = "/v1/devices/{device_id}/contacts/bootstrap"
    timeout_seconds: float = config_value(default=3.0, env="YOYOPOD_CLOUD_TIMEOUT_SECONDS")
    config_poll_interval_seconds: int = config_value(
        default=300,
        env="YOYOPOD_CLOUD_CONFIG_POLL_INTERVAL_SECONDS",
    )
    claim_retry_seconds: int = config_value(
        default=60,
        env="YOYOPOD_CLOUD_CLAIM_RETRY_SECONDS",
    )
    cache_file: str = config_value(
        default="data/cloud/config_cache.json",
        env="YOYOPOD_CLOUD_CACHE_FILE",
    )
    status_file: str = config_value(
        default="data/cloud/status.json",
        env="YOYOPOD_CLOUD_STATUS_FILE",
    )
    mqtt_broker_host: str = config_value(
        default="yoyopod.moraouf.net",
        env="YOYOPOD_CLOUD_MQTT_BROKER_HOST",
    )
    mqtt_broker_port: int = config_value(
        default=1883,
        env="YOYOPOD_CLOUD_MQTT_BROKER_PORT",
    )
    mqtt_use_tls: bool = config_value(
        default=False,
        env="YOYOPOD_CLOUD_MQTT_USE_TLS",
    )
    mqtt_username: str = config_value(
        default="",
        env="YOYOPOD_CLOUD_MQTT_USERNAME",
    )
    mqtt_password: str = config_value(
        default="",
        env="YOYOPOD_CLOUD_MQTT_PASSWORD",
    )
    mqtt_transport: str = config_value(
        default="tcp",
        env="YOYOPOD_CLOUD_MQTT_TRANSPORT",
    )
    battery_report_interval_seconds: int = config_value(
        default=60,
        env="YOYOPOD_CLOUD_BATTERY_REPORT_INTERVAL_SECONDS",
    )


@dataclass(slots=True)
class CloudSecretsConfig:
    """Runtime-only device claim credentials."""

    device_id: str = config_value(default="", env="YOYOPOD_CLOUD_DEVICE_ID")
    device_secret: str = config_value(default="", env="YOYOPOD_CLOUD_DEVICE_SECRET")


@dataclass(slots=True)
class CloudConfig:
    """Composed cloud config built from tracked backend settings plus runtime secrets."""

    backend: CloudBackendConfig = config_value(default_factory=CloudBackendConfig)
    secrets: CloudSecretsConfig = config_value(default_factory=CloudSecretsConfig)


BackendTelemetryConfig = CloudBackendConfig
