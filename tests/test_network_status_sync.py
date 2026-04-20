"""Tests for network status propagation into shared UI state."""

from __future__ import annotations

from yoyopod.app import YoyoPodApp
from yoyopod.app_context import AppContext
from yoyopod.events import (
    NetworkGpsFixEvent,
    NetworkGpsNoFixEvent,
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkSignalUpdateEvent,
)
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo
from yoyopod.ui.screens.lvgl_status import network_status_kwargs


def test_network_status_kwargs_normalize_context_state() -> None:
    """LVGL status-bar helpers should clamp and normalize AppContext values."""

    context = AppContext()
    context.update_network_status(
        network_enabled=True,
        signal_bars=9,
        connection_type="4g",
        connected=True,
        gps_has_fix=True,
    )

    assert network_status_kwargs(context) == {
        "network_enabled": 1,
        "network_connected": 1,
        "wifi_connected": 0,
        "signal_strength": 4,
        "gps_has_fix": 1,
    }


def test_network_status_kwargs_marks_wifi_state_separately() -> None:
    """Wi-Fi connectivity should not light the 4G bars as connected."""

    context = AppContext()
    context.update_network_status(
        network_enabled=True,
        signal_bars=3,
        connection_type="wifi",
        connected=True,
    )

    assert network_status_kwargs(context) == {
        "network_enabled": 1,
        "network_connected": 0,
        "wifi_connected": 1,
        "signal_strength": 3,
        "gps_has_fix": 0,
    }


def test_network_status_kwargs_keep_cellular_indicators_visible_when_disconnected() -> None:
    """Degraded cellular state should keep the indicator block visible even before PPP is up."""

    context = AppContext()
    context.update_network_status(
        network_enabled=True,
        signal_bars=2,
        connection_type="4g",
        connected=False,
        gps_has_fix=False,
    )

    assert network_status_kwargs(context) == {
        "network_enabled": 1,
        "network_connected": 0,
        "wifi_connected": 0,
        "signal_strength": 2,
        "gps_has_fix": 0,
    }


def test_network_event_handlers_keep_context_status_in_sync() -> None:
    """App-level network handlers should keep shared UI state current."""

    app = YoyoPodApp(simulate=True)
    app.context = AppContext()

    app.event_wiring.network_events.handle_network_ppp_up(
        NetworkPppUpEvent(connection_type="4g")
    )
    assert app.context.network.enabled is True
    assert app.context.network.connected is True
    assert app.context.network.connection_type == "4g"
    assert app.context.network.enabled is True
    assert app.context.network.connected is True

    app.event_wiring.network_events.handle_network_signal_update(
        NetworkSignalUpdateEvent(bars=2, csq=12)
    )
    assert app.context.network.signal_strength == 2
    assert app.context.network.signal_strength == 2

    app.event_wiring.network_events.handle_network_gps_fix(NetworkGpsFixEvent(lat=0.0, lng=0.0))
    assert app.context.network.gps_has_fix is True
    assert app.context.network.gps_has_fix is True

    app.event_wiring.network_events.handle_network_gps_no_fix(
        NetworkGpsNoFixEvent(reason="no_fix")
    )
    assert app.context.network.gps_has_fix is False
    assert app.context.network.gps_has_fix is False

    app.event_wiring.network_events.handle_network_ppp_down(
        NetworkPppDownEvent(reason="link lost")
    )
    assert app.context.network.enabled is True
    assert app.context.network.connected is False
    assert app.context.network.connection_type == "4g"
    assert app.context.network.gps_has_fix is False


def test_network_event_handlers_prefer_live_manager_state_over_latched_flags() -> None:
    """Manager-backed handlers should derive degraded 4G and GPS state from the modem snapshot."""

    class _FakeNetworkManager:
        def __init__(self) -> None:
            self.config = type("Config", (), {"enabled": True})()
            self._state = ModemState(
                phase=ModemPhase.REGISTERED,
                signal=SignalInfo(csq=20),
                carrier="Telekom.de",
                network_type="4G",
                sim_ready=True,
                gps=GpsCoordinate(lat=48.7083, lng=9.6610, altitude=328.2, speed=0.0),
            )

        @property
        def modem_state(self) -> ModemState:
            return self._state

        @property
        def is_online(self) -> bool:
            return self._state.phase == ModemPhase.ONLINE

    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.network_manager = _FakeNetworkManager()

    app.event_wiring.network_events.handle_network_gps_fix(
        NetworkGpsFixEvent(lat=48.7083, lng=9.6610)
    )
    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 3
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is False
    assert app.context.network.gps_has_fix is True
    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 3

    app.network_manager.modem_state.gps = None
    app.event_wiring.network_events.handle_network_gps_no_fix(
        NetworkGpsNoFixEvent(reason="no_fix")
    )
    assert app.context.network.gps_has_fix is False
    assert app.context.network.gps_has_fix is False

    app.event_wiring.network_events.handle_network_ppp_down(
        NetworkPppDownEvent(reason="link lost")
    )
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is False
