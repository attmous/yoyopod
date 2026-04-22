"""Network modem configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class NetworkConfig:
    """4G cellular modem settings owned by the network domain."""

    enabled: bool = config_value(default=False, env="YOYOPOD_NETWORK_ENABLED")
    serial_port: str = config_value(default="/dev/ttyUSB2", env="YOYOPOD_MODEM_PORT")
    ppp_port: str = config_value(default="/dev/ttyUSB3", env="YOYOPOD_MODEM_PPP_PORT")
    baud_rate: int = config_value(default=115200, env="YOYOPOD_MODEM_BAUD")
    apn: str = config_value(default="", env="YOYOPOD_MODEM_APN")
    pin: str | None = config_value(default=None)
    gps_enabled: bool = config_value(default=True, env="YOYOPOD_MODEM_GPS_ENABLED")
    ppp_timeout: int = config_value(default=30, env="YOYOPOD_MODEM_PPP_TIMEOUT")
