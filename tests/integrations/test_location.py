"""Tests for the scaffold location integration."""

from __future__ import annotations

from dataclasses import dataclass

from tests.fixtures.app import build_test_app
from yoyopod.integrations.location import (
    DisableGpsCommand,
    EnableGpsCommand,
    RequestFixCommand,
    setup,
    teardown,
)


@dataclass(frozen=True, slots=True)
class FakeFix:
    """Simple immutable GPS fix for location tests."""

    lat: float
    lng: float
    altitude: float = 0.0
    speed: float = 0.0


@dataclass(slots=True)
class FakeGpsBackend:
    """Minimal backend double for scaffold location tests."""

    fix_lat: float = 48.1
    fix_lng: float = 11.5
    return_none: bool = False
    raise_on_get_fix: str = ""
    enabled: bool = False
    closed: bool = False

    def get_fix(self) -> FakeFix | None:
        if self.raise_on_get_fix:
            raise RuntimeError(self.raise_on_get_fix)
        if self.return_none:
            return None
        return FakeFix(self.fix_lat, self.fix_lng)

    def enable(self) -> bool:
        self.enabled = True
        return True

    def disable(self) -> None:
        self.enabled = False

    def close(self) -> None:
        self.closed = True


def test_location_setup_registers_services_and_seeds_state() -> None:
    app = build_test_app()
    backend = FakeGpsBackend()

    integration = setup(app, backend=backend)

    assert integration is app.integrations["location"]
    assert set(app.services.registered()) >= {
        ("location", "request_fix"),
        ("location", "enable_gps"),
        ("location", "disable_gps"),
    }
    assert app.states.get_value("location.fix") is None
    assert app.states.get("location.fix").attrs == {"no_fix_reason": "not_requested"}
    assert app.states.get_value("location.backend_available") is False
    assert app.states.get("location.backend_available").attrs == {"reason": "idle"}


def test_location_request_fix_applies_state_and_attrs() -> None:
    app = build_test_app()
    setup(app, backend=FakeGpsBackend())

    result = app.services.call("location", "request_fix", RequestFixCommand())

    assert result is not None
    fix = app.states.get_value("location.fix")
    assert fix is not None
    assert fix.lat == 48.1
    assert fix.lng == 11.5
    attrs = app.states.get("location.fix").attrs
    assert attrs["lat"] == 48.1
    assert attrs["lng"] == 11.5
    assert app.states.get_value("location.backend_available") is True


def test_location_request_fix_none_sets_reason() -> None:
    app = build_test_app()
    backend = FakeGpsBackend(return_none=True)
    setup(app, backend=backend)

    result = app.services.call("location", "request_fix", RequestFixCommand())

    assert result is None
    state = app.states.get("location.fix")
    assert state is not None
    assert state.value is None
    assert state.attrs == {"no_fix_reason": "no_fix"}
    assert app.states.get_value("location.backend_available") is True


def test_location_enable_and_disable_update_state() -> None:
    app = build_test_app()
    backend = FakeGpsBackend()
    setup(app, backend=backend)

    enabled = app.services.call("location", "enable_gps", EnableGpsCommand())
    disabled = app.services.call("location", "disable_gps", DisableGpsCommand())

    assert enabled is True
    assert disabled is True
    assert backend.enabled is False
    assert app.states.get_value("location.backend_available") is False
    assert app.states.get("location.backend_available").attrs == {"reason": "disabled"}


def test_location_request_fix_failure_updates_state() -> None:
    app = build_test_app()
    setup(app, backend=FakeGpsBackend(raise_on_get_fix="gps offline"))

    result = app.services.call("location", "request_fix", RequestFixCommand())

    assert result is None
    assert app.states.get_value("location.backend_available") is False
    assert app.states.get("location.backend_available").attrs == {"reason": "gps offline"}
    assert app.states.get("location.fix").attrs == {"no_fix_reason": "gps offline"}


def test_location_services_reject_wrong_payload_types_and_teardown_closes_backend() -> None:
    app = build_test_app()
    backend = FakeGpsBackend()
    setup(app, backend=backend)

    try:
        app.services.call("location", "request_fix", {"force": True})
    except TypeError as exc:
        assert str(exc) == "location.request_fix expects RequestFixCommand"
    else:
        raise AssertionError("location.request_fix accepted an untyped payload")

    try:
        app.services.call("location", "enable_gps", {"enabled": True})
    except TypeError as exc:
        assert str(exc) == "location.enable_gps expects EnableGpsCommand"
    else:
        raise AssertionError("location.enable_gps accepted an untyped payload")

    try:
        app.services.call("location", "disable_gps", {"enabled": False})
    except TypeError as exc:
        assert str(exc) == "location.disable_gps expects DisableGpsCommand"
    else:
        raise AssertionError("location.disable_gps accepted an untyped payload")

    teardown(app)
    assert "location" not in app.integrations
    assert backend.closed is True
