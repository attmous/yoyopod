"""Tests for Rust-backed network status projection into shared UI state."""

from __future__ import annotations

from yoyopod.app import YoyoPodApp
from yoyopod.core import AppContext
from yoyopod.core.events import WorkerDomainStateChangedEvent, WorkerMessageReceivedEvent
from yoyopod.integrations.network.rust_host import RustNetworkFacade
from yoyopod.ui.screens.lvgl_status import network_status_kwargs


def _snapshot(
    *,
    enabled: bool = True,
    gps_enabled: bool = True,
    state: str = "registered",
    connected: bool = False,
    gps_has_fix: bool = False,
    signal_bars: int = 3,
) -> dict[str, object]:
    network_status = "registered"
    if not enabled:
        network_status = "disabled"
    elif connected:
        network_status = "online"
    elif state in {"probing", "ready", "registering", "recovering"}:
        network_status = "connecting"
    elif state == "degraded":
        network_status = "degraded"
    gps_status = "disabled"
    if enabled and gps_enabled:
        gps_status = "fix" if gps_has_fix else "searching"
    probe_error = "" if enabled else "network module disabled in config/network/cellular.yaml"
    return {
        "enabled": enabled,
        "gps_enabled": gps_enabled,
        "config_dir": "config",
        "state": state,
        "sim_ready": enabled,
        "registered": state in {"registered", "ppp_starting", "online", "recovering", "degraded"},
        "carrier": "Telekom.de" if enabled else "",
        "network_type": "4G" if enabled else "",
        "signal": {"csq": 20 if enabled else None, "bars": signal_bars},
        "ppp": {
            "up": connected,
            "interface": "ppp0" if enabled else "",
            "pid": 1234 if connected else None,
            "default_route_owned": connected,
            "last_failure": "",
        },
        "gps": {
            "has_fix": gps_has_fix,
            "lat": 48.7083 if gps_has_fix else None,
            "lng": 9.6610 if gps_has_fix else None,
            "altitude": 328.2 if gps_has_fix else None,
            "speed": 0.0 if gps_has_fix else None,
            "timestamp": "2026-04-30T10:00:00Z" if gps_has_fix else None,
            "last_query_result": "fix" if gps_has_fix else "no_fix",
        },
        "connected": connected,
        "gps_has_fix": gps_has_fix,
        "connection_type": "4g" if enabled else "none",
        "network_status": network_status,
        "gps_status": gps_status,
        "recovering": state == "recovering",
        "retryable": True,
        "reconnect_attempts": 0,
        "next_retry_at_ms": None,
        "error_code": "",
        "error_message": "",
        "updated_at_ms": 1,
        "app_state": {
            "network_enabled": enabled,
            "signal_bars": signal_bars,
            "connection_type": "4g" if enabled else "none",
            "connected": connected,
            "gps_has_fix": gps_has_fix,
        },
        "views": {
            "setup": {
                "network_enabled": enabled,
                "gps_refresh_allowed": enabled and gps_enabled,
                "network_rows": (
                    [["Status", "Disabled"]]
                    if not enabled
                    else [
                        ["Status", "Online" if connected else "Registered"],
                        ["Carrier", "Telekom.de"],
                        ["Type", "4G"],
                        ["Signal", f"{signal_bars}/4"],
                        ["PPP", "Up" if connected else "Down"],
                    ]
                ),
                "gps_rows": (
                    [
                        ["Fix", "Disabled"],
                        ["Lat", "--"],
                        ["Lng", "--"],
                        ["Alt", "--"],
                        ["Speed", "--"],
                    ]
                    if not enabled or not gps_enabled
                    else (
                        [
                            ["Fix", "Yes"],
                            ["Lat", "48.708300"],
                            ["Lng", "9.661000"],
                            ["Alt", "328.2m"],
                            ["Speed", "0.0km/h"],
                        ]
                        if gps_has_fix
                        else [
                            ["Fix", "Searching"],
                            ["Lat", "--"],
                            ["Lng", "--"],
                            ["Alt", "--"],
                            ["Speed", "--"],
                        ]
                    )
                ),
            },
            "cli": {
                "probe_ok": enabled,
                "probe_error": probe_error,
                "status_lines": [
                    f"phase={state}",
                    f"sim_ready={enabled}",
                    f"carrier={'Telekom.de' if enabled else 'unknown'}",
                    f"network_type={'4G' if enabled else 'unknown'}",
                    f"signal_csq={20 if enabled else 'unknown'}",
                    f"signal_bars={signal_bars}",
                    f"ppp_up={connected}",
                    f"error={probe_error or 'none'}",
                ],
            },
        },
    }


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
            payload=_snapshot(connected=True, gps_has_fix=True, state="online"),
        )
    )

    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 3
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is True
    assert app.context.network.gps_has_fix is True


def test_rust_network_facade_clears_context_when_worker_degrades() -> None:
    """Worker degradation should clear mirrored app state instead of deriving stale network facts."""

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
            payload=_snapshot(connected=True, gps_has_fix=True, state="online"),
        )
    )

    facade.handle_worker_state_change(
        WorkerDomainStateChangedEvent(
            domain="network",
            state="degraded",
            reason="process_exited",
        )
    )

    assert app.context.network.enabled is False
    assert app.context.network.signal_strength == 0
    assert app.context.network.connection_type == "none"
    assert app.context.network.connected is False
    assert app.context.network.gps_has_fix is False
    assert facade.snapshot() is not None
    assert facade.snapshot()["state"] == "online"
    assert cloud_events == [False]
