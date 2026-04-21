"""Tests for scaffold network state helpers."""

from __future__ import annotations

from dataclasses import dataclass

from tests.fixtures.app import build_test_app
from yoyopod.integrations.network.handlers import (
    apply_modem_status_to_state,
    apply_ppp_status_to_state,
    apply_signal_to_state,
)


@dataclass(frozen=True, slots=True)
class FakeModemStatus:
    registered: bool
    carrier: str
    network_type: str
    available: bool = True


def test_apply_modem_status_sets_state() -> None:
    app = build_test_app()

    apply_modem_status_to_state(
        app,
        FakeModemStatus(registered=True, carrier="T-Mobile", network_type="4G"),
    )

    assert app.states.get_value("network.cellular_registered") is True
    assert app.states.get("network.cellular_registered").attrs == {
        "carrier": "T-Mobile",
        "network_type": "4G",
    }


def test_apply_modem_status_unregistered() -> None:
    app = build_test_app()

    apply_modem_status_to_state(
        app,
        FakeModemStatus(registered=False, carrier="", network_type=""),
    )

    assert app.states.get_value("network.cellular_registered") is False


def test_apply_ppp_status() -> None:
    app = build_test_app()

    apply_ppp_status_to_state(app, up=True, reason="session_established")
    assert app.states.get_value("network.ppp_up") is True
    assert app.states.get("network.ppp_up").attrs == {"reason": "session_established"}

    apply_ppp_status_to_state(app, up=False, reason="link_down")
    assert app.states.get_value("network.ppp_up") is False
    assert app.states.get("network.ppp_up").attrs == {"reason": "link_down"}


def test_apply_signal_maps_csq_to_bars() -> None:
    app = build_test_app()

    apply_signal_to_state(app, csq=25, bars=4)

    assert app.states.get_value("network.signal_bars") == 4
    assert app.states.get("network.signal_bars").attrs == {"csq": 25}


def test_apply_signal_none_when_no_service() -> None:
    app = build_test_app()

    apply_signal_to_state(app, csq=None, bars=None)

    assert app.states.get_value("network.signal_bars") is None
    assert app.states.get("network.signal_bars").attrs == {"csq": None}
