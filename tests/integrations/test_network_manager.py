"""Unit tests for the NetworkManager facade."""

from __future__ import annotations

import threading
import yaml

from yoyopod.config import ConfigManager
from yoyopod.config.models import NetworkConfig, build_config_model
from yoyopod.core import Bus
from yoyopod.integrations.location.events import NetworkGpsFixEvent, NetworkGpsNoFixEvent
from yoyopod.integrations.network import NetworkManager
from yoyopod.integrations.network.events import (
    NetworkPppDownEvent,
    NetworkPppUpEvent,
    NetworkRegisteredEvent,
)
from yoyopod.integrations.network.models import (
    GpsCoordinate,
    ModemPhase,
    ModemState,
    SignalInfo,
)


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
        self.ppp_wait_calls = 0
        self.gps_query_calls = 0
        self.gps_coord: GpsCoordinate | None = None
        self.health_online = True

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

    def start_ppp(self, *, wait_for_link: bool = True) -> bool:
        self.ppp_started = True
        if not wait_for_link:
            self.state.phase = ModemPhase.PPP_STARTING
            return True
        return self.wait_for_ppp_link()

    def wait_for_ppp_link(self, timeout: float = 30.0) -> bool:
        self.ppp_wait_calls += 1
        self.health_online = True
        self.state.phase = ModemPhase.ONLINE
        return True

    def stop_ppp(self) -> None:
        self.ppp_stopped = True
        self.health_online = False
        self.state.phase = ModemPhase.REGISTERED

    def query_gps(self):
        self.gps_query_calls += 1
        self.state.gps = self.gps_coord
        return self.gps_coord

    def is_online(self) -> bool:
        return self.health_online and self.state.phase == ModemPhase.ONLINE


class RecordingLock:
    """Track lifecycle lock usage without changing manager behavior."""

    def __init__(self) -> None:
        self.enter_calls = 0
        self.exit_calls = 0

    def __enter__(self) -> "RecordingLock":
        self.enter_calls += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exit_calls += 1
        return None


class BlockingPppBackend(FakeBackend):
    """Backend double that pauses PPP link-up so stop() can race recover()."""

    def __init__(self) -> None:
        super().__init__()
        self.wait_entered = threading.Event()
        self.release_wait = threading.Event()
        self.close_called = threading.Event()

    def wait_for_ppp_link(self, timeout: float = 30.0) -> bool:
        self.ppp_wait_calls += 1
        self.wait_entered.set()
        self.release_wait.wait(timeout=timeout)
        self.health_online = True
        self.state.phase = ModemPhase.ONLINE
        return True

    def close(self) -> None:
        self.close_called.set()
        super().close()


def test_manager_start_full_sequence():
    """start() should open, init, and start PPP."""
    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = Bus()
    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)

    manager.start()

    assert backend.opened is True
    assert backend.inited is True
    assert backend.ppp_started is True


def test_manager_start_background_runs_full_sequence() -> None:
    """start_background() should run the same bring-up flow off the caller thread."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    published: list[object] = []
    manager = NetworkManager(
        config=config,
        backend=backend,
        event_publisher=published.append,
    )

    worker = manager.start_background()
    worker.join(timeout=1.0)

    assert worker.is_alive() is False
    assert backend.opened is True
    assert backend.inited is True
    assert backend.ppp_started is True
    assert any(isinstance(event, NetworkPppUpEvent) for event in published)


def test_manager_stop():
    """stop() should close the backend."""
    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = Bus()
    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)

    manager.start()
    manager.stop()

    assert backend.closed is True


def test_manager_publishes_ppp_up():
    """start() should publish NetworkPppUpEvent on the bus."""
    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = Bus()
    events_seen: list[object] = []
    bus.subscribe(NetworkPppUpEvent, events_seen.append)

    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)
    manager.start()
    assert bus.drain() == 5

    assert len(events_seen) == 1
    assert isinstance(events_seen[0], NetworkPppUpEvent)


def test_manager_is_online():
    """is_online should reflect backend PPP state."""
    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    bus = Bus()
    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)

    manager.start()
    assert manager.is_online is True

    backend.state.phase = ModemPhase.REGISTERED
    assert manager.is_online is False


def test_manager_recover_retries_full_bringup_after_failed_boot() -> None:
    """recover() should reset the backend and rerun modem init plus PPP bring-up."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    backend.state.phase = ModemPhase.REGISTERING
    backend.health_online = False
    bus = Bus()
    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)

    recovered = manager.recover()

    assert recovered is True
    assert backend.closed is True
    assert backend.opened is True
    assert backend.inited is True
    assert backend.ppp_started is True
    assert backend.ppp_wait_calls == 1


def test_manager_warms_gps_fix_on_start_when_enabled():
    """start() should query GPS once so Setup can show cached coordinates promptly."""

    config = build_config_model(
        NetworkConfig,
        {"enabled": True, "apn": "internet", "gps_enabled": True},
    )
    backend = FakeBackend()
    backend.gps_coord = GpsCoordinate(lat=48.7083, lng=9.6610, altitude=328.2, speed=0.0)
    bus = Bus()
    gps_events: list[object] = []
    bus.subscribe(NetworkGpsFixEvent, gps_events.append)

    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)
    manager.start()
    assert bus.drain() == 5

    assert backend.gps_query_calls == 1
    assert backend.state.gps == backend.gps_coord
    assert len(gps_events) == 1
    assert isinstance(gps_events[0], NetworkGpsFixEvent)


def test_manager_publishes_no_fix_and_clears_cached_gps_state() -> None:
    """query_gps() should clear stale coordinates and publish a no-fix event."""

    config = build_config_model(
        NetworkConfig,
        {"enabled": True, "apn": "internet", "gps_enabled": True},
    )
    backend = FakeBackend()
    backend.state.gps = GpsCoordinate(lat=48.7083, lng=9.6610, altitude=328.2, speed=0.0)
    bus = Bus()
    no_fix_events: list[object] = []
    bus.subscribe(NetworkGpsNoFixEvent, no_fix_events.append)

    manager = NetworkManager(config=config, backend=backend, event_publisher=bus.publish)

    coord = manager.query_gps()
    assert bus.drain() == 1

    assert coord is None
    assert backend.state.gps is None
    assert len(no_fix_events) == 1
    assert isinstance(no_fix_events[0], NetworkGpsNoFixEvent)


def test_manager_query_gps_uses_lifecycle_lock() -> None:
    """query_gps() should serialize GPS reads with modem recovery work."""

    config = build_config_model(
        NetworkConfig,
        {"enabled": True, "apn": "internet", "gps_enabled": True},
    )
    backend = FakeBackend()
    backend.gps_coord = GpsCoordinate(lat=48.7083, lng=9.6610, altitude=328.2, speed=0.0)
    manager = NetworkManager(config=config, backend=backend)
    lock = RecordingLock()
    manager._lifecycle_lock = lock

    coord = manager.query_gps()

    assert coord == backend.gps_coord
    assert backend.gps_query_calls == 1
    assert lock.enter_calls == 1
    assert lock.exit_calls == 1


def test_manager_stop_does_not_block_on_recovering_ppp_wait() -> None:
    """stop() should still acquire the lifecycle lock while PPP wait runs in recover()."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = BlockingPppBackend()
    backend.state.phase = ModemPhase.REGISTERING
    backend.health_online = False
    manager = NetworkManager(config=config, backend=backend)

    recovery_thread = threading.Thread(target=manager.recover, daemon=True)
    recovery_thread.start()

    assert backend.wait_entered.wait(timeout=1.0) is True

    stop_thread = threading.Thread(target=manager.stop, daemon=True)
    stop_thread.start()

    assert backend.close_called.wait(timeout=0.5) is True
    backend.release_wait.set()
    recovery_thread.join(timeout=1.0)
    stop_thread.join(timeout=1.0)

    assert recovery_thread.is_alive() is False
    assert stop_thread.is_alive() is False


def test_manager_stop_cancels_recovery_restart_after_reset() -> None:
    """stop() should invalidate a recovery attempt before it reopens the modem."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    backend.state.phase = ModemPhase.REGISTERING
    backend.health_online = False
    manager = NetworkManager(config=config, backend=backend)
    start_attempted = threading.Event()
    release_start = threading.Event()
    original_start_flow = manager._start_flow
    recover_result: list[bool] = []

    def gated_start_flow(*, expected_generation: int | None = None) -> bool:
        start_attempted.set()
        assert release_start.wait(timeout=1.0) is True
        return original_start_flow(expected_generation=expected_generation)

    manager._start_flow = gated_start_flow

    recovery_thread = threading.Thread(
        target=lambda: recover_result.append(manager.recover()),
        daemon=True,
    )
    recovery_thread.start()

    assert start_attempted.wait(timeout=1.0) is True

    manager.stop()
    release_start.set()
    recovery_thread.join(timeout=1.0)

    assert recovery_thread.is_alive() is False
    assert recover_result == [False]
    assert backend.opened is False


def test_manager_stop_cancels_ppp_start_after_post_init_events() -> None:
    """stop() should prevent PPP startup if shutdown lands after modem init succeeds."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    backend.state.phase = ModemPhase.REGISTERING
    backend.health_online = False
    manager = NetworkManager(config=config, backend=backend)
    published: list[object] = []
    stop_requested = False

    def intercept_publish(event: object) -> None:
        nonlocal stop_requested
        published.append(event)
        if not stop_requested and isinstance(event, NetworkRegisteredEvent):
            stop_requested = True
            manager.stop()

    manager._publish = intercept_publish

    recovered = manager.recover()

    assert recovered is False
    assert backend.closed is True
    assert backend.ppp_started is False
    assert any(isinstance(event, NetworkRegisteredEvent) for event in published)
    assert any(isinstance(event, NetworkPppDownEvent) for event in published)
    assert not any(isinstance(event, NetworkPppUpEvent) for event in published)


def test_manager_stop_suppresses_ppp_up_event_after_ppp_link_ready() -> None:
    """stop() should suppress stale PPP-up publish if teardown lands after link-up."""

    config = build_config_model(NetworkConfig, {"enabled": True, "apn": "internet"})
    backend = FakeBackend()
    backend.state.phase = ModemPhase.REGISTERING
    backend.health_online = False
    manager = NetworkManager(config=config, backend=backend)
    published: list[object] = []
    original_start_ppp = manager._start_ppp
    stop_requested = False

    def intercept_publish(event: object) -> None:
        published.append(event)

    def stop_after_ppp(*, expected_generation: int | None = None) -> bool:
        nonlocal stop_requested
        result = original_start_ppp(expected_generation=expected_generation)
        if result and not stop_requested:
            stop_requested = True
            manager.stop()
        return result

    manager._publish = intercept_publish
    manager._start_ppp = stop_after_ppp

    recovered = manager.recover()

    assert recovered is False
    assert backend.closed is True
    assert backend.ppp_started is True
    assert any(isinstance(event, NetworkPppDownEvent) for event in published)
    assert not any(isinstance(event, NetworkPppUpEvent) for event in published)


def test_manager_from_config_manager_uses_domain_owned_network_settings(tmp_path) -> None:
    """from_config_manager() should read the canonical network domain file."""

    config_dir = tmp_path / "config"
    network_file = config_dir / "network" / "cellular.yaml"
    network_file.parent.mkdir(parents=True, exist_ok=True)
    network_file.write_text(
        yaml.safe_dump(
            {
                "network": {
                    "enabled": True,
                    "apn": "iot.example",
                    "ppp_timeout": 45,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config_manager = ConfigManager(config_dir=str(config_dir))

    manager = NetworkManager.from_config_manager(config_manager)

    assert manager.config.enabled is True
    assert manager.config.apn == "iot.example"
    assert manager.config.ppp_timeout == 45
