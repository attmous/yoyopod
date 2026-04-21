"""Tests for the scaffold network integration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from yoyopod.core import build_test_app, drain_all
from yoyopod.integrations.network import (
    DisablePppCommand,
    EnablePppCommand,
    RefreshSignalCommand,
    SetApnCommand,
    setup,
    teardown,
)


@dataclass(frozen=True, slots=True)
class FakeStatus:
    registered: bool
    carrier: str
    network_type: str
    available: bool = True


@dataclass(frozen=True, slots=True)
class FakeSignal:
    csq: int | None
    bars: int | None


@dataclass(slots=True)
class FakeNetworkBackend:
    registered: bool = True
    carrier: str = "TestCarrier"
    network_type: str = "4G"
    csq: int | None = 20
    bars: int | None = 3
    ppp_commands: list[str] = field(default_factory=list)
    apn_calls: list[tuple[str, str, str]] = field(default_factory=list)
    closed: bool = False

    def get_status(self) -> FakeStatus:
        return FakeStatus(self.registered, self.carrier, self.network_type)

    def get_signal(self) -> FakeSignal:
        return FakeSignal(self.csq, self.bars)

    def enable_ppp(self) -> bool:
        self.ppp_commands.append("up")
        return True

    def disable_ppp(self) -> None:
        self.ppp_commands.append("down")

    def set_apn(self, *, apn: str, username: str = "", password: str = "") -> None:
        self.apn_calls.append((apn, username, password))

    def close(self) -> None:
        self.closed = True


def test_network_setup_registers_services_and_seeds_state() -> None:
    app = build_test_app()
    backend = FakeNetworkBackend()

    integration = setup(app, backend=backend, poll_interval_seconds=1.0)

    assert integration is app.integrations["network"]
    assert set(app.services.registered()) >= {
        ("network", "disable_ppp"),
        ("network", "enable_ppp"),
        ("network", "refresh_signal"),
        ("network", "set_apn"),
    }
    assert app.states.get_value("network.cellular_registered") is False
    assert app.states.get("network.cellular_registered").attrs == {
        "carrier": "",
        "network_type": "",
    }
    assert app.states.get_value("network.signal_bars") is None
    assert app.states.get("network.signal_bars").attrs == {"csq": None}
    assert app.states.get_value("network.ppp_up") is False
    teardown(app)


def test_network_poller_mirrors_modem_status_and_signal() -> None:
    app = build_test_app()
    backend = FakeNetworkBackend()
    setup(app, backend=backend, poll_interval_seconds=0.05)

    time.sleep(0.15)
    drain_all(app)

    assert app.states.get_value("network.cellular_registered") is True
    assert app.states.get("network.cellular_registered").attrs == {
        "carrier": "TestCarrier",
        "network_type": "4G",
    }
    assert app.states.get_value("network.signal_bars") == 3
    assert app.states.get("network.signal_bars").attrs == {"csq": 20}

    teardown(app)


def test_network_enable_disable_ppp_and_set_apn() -> None:
    app = build_test_app()
    backend = FakeNetworkBackend()
    setup(app, backend=backend, poll_interval_seconds=1.0)

    enabled = app.services.call("network", "enable_ppp", EnablePppCommand())
    disabled = app.services.call("network", "disable_ppp", DisablePppCommand())
    app.services.call(
        "network",
        "set_apn",
        SetApnCommand(apn="internet", username="u", password="p"),
    )

    assert enabled is True
    assert disabled is True
    assert backend.ppp_commands == ["up", "down"]
    assert app.states.get_value("network.ppp_up") is False
    assert app.states.get("network.ppp_up").attrs == {"reason": "disabled"}
    assert backend.apn_calls == [("internet", "u", "p")]

    teardown(app)


def test_network_refresh_signal_updates_state() -> None:
    app = build_test_app()
    backend = FakeNetworkBackend(csq=25, bars=4)
    setup(app, backend=backend, poll_interval_seconds=1.0)

    signal = app.services.call("network", "refresh_signal", RefreshSignalCommand())

    assert signal is not None
    assert app.states.get_value("network.signal_bars") == 4
    assert app.states.get("network.signal_bars").attrs == {"csq": 25}

    teardown(app)


def test_network_services_reject_wrong_payload_types_and_teardown_closes_backend() -> None:
    app = build_test_app()
    backend = FakeNetworkBackend()
    setup(app, backend=backend, poll_interval_seconds=1.0)

    try:
        app.services.call("network", "enable_ppp", {"up": True})
    except TypeError as exc:
        assert str(exc) == "network.enable_ppp expects EnablePppCommand"
    else:
        raise AssertionError("network.enable_ppp accepted an untyped payload")

    try:
        app.services.call("network", "disable_ppp", {"down": True})
    except TypeError as exc:
        assert str(exc) == "network.disable_ppp expects DisablePppCommand"
    else:
        raise AssertionError("network.disable_ppp accepted an untyped payload")

    try:
        app.services.call("network", "refresh_signal", {"now": True})
    except TypeError as exc:
        assert str(exc) == "network.refresh_signal expects RefreshSignalCommand"
    else:
        raise AssertionError("network.refresh_signal accepted an untyped payload")

    try:
        app.services.call("network", "set_apn", {"apn": "internet"})
    except TypeError as exc:
        assert str(exc) == "network.set_apn expects SetApnCommand"
    else:
        raise AssertionError("network.set_apn accepted an untyped payload")

    teardown(app)
    assert "network" not in app.integrations
    assert backend.closed is True
