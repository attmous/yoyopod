"""Unit tests for the NetworkManager facade."""

from __future__ import annotations

from yoyopy.config.models import AppNetworkConfig, build_config_model
from yoyopy.event_bus import EventBus
from yoyopy.events import NetworkGpsFixEvent, NetworkPppUpEvent
from yoyopy.network.manager import NetworkManager
from yoyopy.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo


class FakeBackend:
    """Minimal backend double for manager tests."""

    def __init__(self) -> None:
        self.state = ModemState(
            phase=ModemPhase.ONLINE,
            signal=SignalInfo(csq=20),
            carrier="T-Mobile",
            network_type="4G",
            sim_ready=True,
        )
        self.opened = False
        self.closed = False
        self.inited = False
        self.ppp_started = False
        self.ppp_stopped = False
        self.gps_query_calls = 0
        self.gps_coord: GpsCoordinate | None = None

    def probe(self) -> bool:
        return True

    def get_state(self) -> ModemState:
        return self.state

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def init_modem(self) -> None:
        self.inited = True
        self.state.phase = ModemPhase.REGISTERED

    def start_ppp(self) -> bool:
        self.ppp_started = True
        self.state.phase = ModemPhase.ONLINE
        return True

    def stop_ppp(self) -> None:
        self.ppp_stopped = True
        self.state.phase = ModemPhase.REGISTERED

    def query_gps(self):
        self.gps_query_calls += 1
        if self.gps_coord is not None:
            self.state.gps = self.gps_coord
        return self.gps_coord


def test_manager_start_full_sequence():
    """start() should open, init, and start PPP."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()

    assert backend.opened is True
    assert backend.inited is True
    assert backend.ppp_started is True


def test_manager_stop():
    """stop() should close the backend."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()
    manager.stop()

    assert backend.closed is True


def test_manager_publishes_ppp_up():
    """start() should publish NetworkPppUpEvent on the bus."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    events_seen: list[object] = []
    bus.subscribe(NetworkPppUpEvent, events_seen.append)

    manager = NetworkManager(config=config, backend=backend, event_bus=bus)
    manager.start()

    assert len(events_seen) == 1
    assert isinstance(events_seen[0], NetworkPppUpEvent)


def test_manager_is_online():
    """is_online should reflect backend PPP state."""
    config = build_config_model(AppNetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = EventBus()
    manager = NetworkManager(config=config, backend=backend, event_bus=bus)

    manager.start()
    assert manager.is_online is True

    backend.state.phase = ModemPhase.REGISTERED
    assert manager.is_online is False


def test_manager_warms_gps_fix_on_start_when_enabled():
    """start() should query GPS once so Setup can show cached coordinates promptly."""

    config = build_config_model(
        AppNetworkConfig,
        {"enabled": True, "apn": "internet", "gps_enabled": True},
    )
    backend = FakeBackend()
    backend.gps_coord = GpsCoordinate(lat=48.7083, lng=9.6610, altitude=328.2, speed=0.0)
    bus = EventBus()
    gps_events: list[object] = []
    bus.subscribe(NetworkGpsFixEvent, gps_events.append)

    manager = NetworkManager(config=config, backend=backend, event_bus=bus)
    manager.start()

    assert backend.gps_query_calls == 1
    assert backend.state.gps == backend.gps_coord
    assert len(gps_events) == 1
    assert isinstance(gps_events[0], NetworkGpsFixEvent)
