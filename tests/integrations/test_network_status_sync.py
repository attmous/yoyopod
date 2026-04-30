"""Tests for Rust-backed network status projection into shared UI state."""

from __future__ import annotations

from dataclasses import asdict

from yoyopod.app import YoyoPodApp
from yoyopod.core import AppContext
from yoyopod.core.events import WorkerDomainStateChangedEvent, WorkerMessageReceivedEvent
from yoyopod.integrations.network.rust_host import RustNetworkFacade
from yoyopod.integrations.network.snapshot import (
    RustNetworkGpsSnapshot,
    RustNetworkPppSnapshot,
    RustNetworkSignalSnapshot,
    RustNetworkSnapshot,
)
from yoyopod.ui.screens.lvgl_status import network_status_kwargs


def _snapshot(
    *,
    enabled: bool = True,
    gps_enabled: bool = True,
    state: str = "registered",
    connected: bool = False,
    gps_has_fix: bool = False,
    signal_bars: int = 3,
) -> RustNetworkSnapshot:
    gps = RustNetworkGpsSnapshot(
        has_fix=gps_has_fix,
        lat=48.7083 if gps_has_fix else None,
        lng=9.6610 if gps_has_fix else None,
        altitude=328.2 if gps_has_fix else None,
        speed=0.0 if gps_has_fix else None,
        timestamp="2026-04-30T10:00:00Z" if gps_has_fix else None,
        last_query_result="fix" if gps_has_fix else "no_fix",
    )
    return RustNetworkSnapshot(
        enabled=enabled,
        gps_enabled=gps_enabled,
        config_dir="config",
        state=state,
        sim_ready=enabled,
        registered=state in {"registered", "ppp_starting", "online", "recovering", "degraded"},
        carrier="Telekom.de" if enabled else "",
        network_type="4G" if enabled else "",
        signal=RustNetworkSignalSnapshot(csq=20 if enabled else None, bars=signal_bars),
        ppp=RustNetworkPppSnapshot(
            up=connected,
            interface="ppp0" if enabled else "",
            pid=1234 if connected else None,
            default_route_owned=connected,
            last_failure="",
        ),
        gps=gps,
        recovering=state == "recovering",
        retryable=True,
        reconnect_attempts=0,
        next_retry_at_ms=None,
        error_code="",
        error_message="",
        updated_at_ms=1,
    )


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


def test_rust_network_facade_projects_snapshot_into_context() -> None:
    """Rust worker snapshots should become the app-facing network source of truth."""

    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.cloud_manager = None
    facade = RustNetworkFacade(app)

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="network",
            kind="event",
            type="network.snapshot",
            request_id=None,
            payload=asdict(_snapshot(connected=True, gps_has_fix=True, state="online")),
        )
    )

    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 3
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is True
    assert app.context.network.gps_has_fix is True


def test_rust_network_facade_keeps_cellular_visibility_when_worker_degrades() -> None:
    """Worker degradation should drop PPP while preserving the cellular status block."""

    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    cloud_events: list[bool] = []
    app.cloud_manager = type(
        "CloudManager",
        (),
        {"note_network_change": lambda self, *, connected: cloud_events.append(connected)},
    )()
    facade = RustNetworkFacade(app)

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="network",
            kind="event",
            type="network.snapshot",
            request_id=None,
            payload=asdict(_snapshot(connected=True, gps_has_fix=True, state="online")),
        )
    )

    facade.handle_worker_state_change(
        WorkerDomainStateChangedEvent(
            domain="network",
            state="degraded",
            reason="process_exited",
        )
    )

    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 3
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is False
    assert app.context.network.gps_has_fix is False
    assert facade.snapshot() is not None
    assert facade.snapshot().state == "online"
    assert cloud_events == [False]
