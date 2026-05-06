"""Unit tests for shared network-facing config and context state."""

from __future__ import annotations

from yoyopod.core import AppContext
from yoyopod.config.models import NetworkConfig, build_config_model


def test_app_context_update_network_status():
    """update_network_status should set signal and connection fields."""
    ctx = AppContext()
    assert ctx.network.connection_type == "none"
    assert ctx.network.signal_strength == 4  # default

    ctx.update_network_status(signal_bars=3, connection_type="4g", connected=True)
    assert ctx.network.signal_strength == 3
    assert ctx.network.connection_type == "4g"
    assert ctx.network.connected is True


def test_network_config_defaults():
    """NetworkConfig should be disabled by default with sane defaults."""
    config = build_config_model(NetworkConfig, {})
    assert config.enabled is False
    assert config.serial_port == "/dev/ttyUSB2"
    assert config.ppp_port == "/dev/ttyUSB3"
    assert config.baud_rate == 115200
    assert config.apn == ""
    assert config.gps_enabled is True
    assert config.ppp_timeout == 30


def test_network_config_from_yaml_data():
    """NetworkConfig should load from YAML data."""
    data = {"enabled": True, "apn": "internet", "serial_port": "/dev/ttyAMA0"}
    config = build_config_model(NetworkConfig, data)
    assert config.enabled is True
    assert config.apn == "internet"
    assert config.serial_port == "/dev/ttyAMA0"


def test_app_context_update_network_status_with_gps():
    """update_network_status should set gps_has_fix."""
    ctx = AppContext()
    assert ctx.network.gps_has_fix is False

    ctx.update_network_status(gps_has_fix=True)
    assert ctx.network.gps_has_fix is True

    ctx.update_network_status(gps_has_fix=False)
    assert ctx.network.gps_has_fix is False
