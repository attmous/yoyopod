"""Unit tests for network data models and config."""

from __future__ import annotations

from yoyopod.network.models import (
    GpsCoordinate,
    ModemState,
    ModemPhase,
    SignalInfo,
)


def test_modem_state_defaults():
    """ModemState should have sensible defaults for an uninitialized modem."""
    state = ModemState()
    assert state.phase == ModemPhase.OFF
    assert state.signal is None
    assert state.carrier == ""
    assert state.network_type == ""
    assert state.gps is None


def test_signal_info_bars_mapping():
    """SignalInfo.bars should map raw CSQ 0-31 to 0-4 bars."""
    assert SignalInfo(csq=0).bars == 0
    assert SignalInfo(csq=5).bars == 1
    assert SignalInfo(csq=12).bars == 2
    assert SignalInfo(csq=20).bars == 3
    assert SignalInfo(csq=28).bars == 4
    assert SignalInfo(csq=99).bars == 0  # 99 = not detectable


def test_gps_coordinate_fields():
    """GpsCoordinate should store lat/lng/altitude/speed."""
    coord = GpsCoordinate(lat=48.8566, lng=2.3522, altitude=35.0, speed=0.0)
    assert coord.lat == 48.8566
    assert coord.lng == 2.3522


from yoyopod.events import (
    NetworkModemReadyEvent,
    NetworkRegisteredEvent,
    NetworkPppUpEvent,
    NetworkPppDownEvent,
    NetworkSignalUpdateEvent,
    NetworkGpsFixEvent,
)
from yoyopod.app_context import AppContext
from yoyopod.network import NetworkConfig


def test_network_events_are_frozen():
    """Network events should be immutable frozen dataclasses."""
    evt = NetworkPppUpEvent()
    try:
        evt.connection_type = "wifi"  # type: ignore
        assert False, "Expected FrozenInstanceError"
    except AttributeError:
        pass


def test_app_context_update_network_status():
    """update_network_status should set signal and connection fields."""
    ctx = AppContext()
    assert ctx.network.connection_type == "none"
    assert ctx.network.signal_strength == 4  # default

    ctx.update_network_status(signal_bars=3, connection_type="4g", connected=True)
    assert ctx.network.signal_strength == 3
    assert ctx.network.connection_type == "4g"
    assert ctx.network.connected is True


from yoyopod.config.models import build_config_model


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
