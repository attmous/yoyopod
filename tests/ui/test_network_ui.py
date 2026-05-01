"""Unit tests for Network and GPS Setup pages."""

from __future__ import annotations

from yoyopod.core import AppContext
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens.system.power import (
    PowerScreen,
    build_power_screen_actions,
    build_power_screen_state_provider,
)


class FakeDisplay:
    """Minimal display double."""

    WIDTH = 240
    HEIGHT = 280
    STATUS_BAR_HEIGHT = 28
    COLOR_BLACK = (0, 0, 0)

    def is_portrait(self) -> bool:
        return True

    def rectangle(self, *args, **kwargs) -> None:
        pass

    def circle(self, *args, **kwargs) -> None:
        pass

    def text(self, *args, **kwargs) -> None:
        pass

    def get_text_size(self, text: str, size: int) -> tuple[int, int]:
        return (len(text) * 6, size)


def _runtime_snapshot(
    *,
    enabled: bool = True,
    gps_enabled: bool = True,
    state: str = "online",
    connected: bool = True,
    gps: dict[str, object] | None = None,
) -> dict[str, object]:
    network_status = "disabled"
    if enabled:
        if connected:
            network_status = "online"
        elif state in {"registered", "ppp_starting", "ppp_stopping"}:
            network_status = "registered"
        elif state in {"probing", "ready", "registering", "recovering"}:
            network_status = "connecting"
        elif state == "degraded":
            network_status = "degraded"
        else:
            network_status = "offline"
    gps_payload = gps or {
        "has_fix": False,
        "lat": None,
        "lng": None,
        "altitude": None,
        "speed": None,
        "timestamp": None,
        "last_query_result": "idle",
    }
    if not enabled:
        network_rows = [["Status", "Disabled"]]
        gps_rows = [
            ["Fix", "Disabled"],
            ["Lat", "--"],
            ["Lng", "--"],
            ["Alt", "--"],
            ["Speed", "--"],
        ]
    else:
        network_rows = [
            [
                "Status",
                {
                    "online": "Online",
                    "registered": "Registered",
                    "connecting": "Connecting",
                    "degraded": "Degraded",
                    "offline": "Offline",
                    "disabled": "Disabled",
                }.get(network_status, "Offline"),
            ],
            ["Carrier", "Telekom.de"],
            ["Type", "4G"],
            ["Signal", "3/4"],
            ["PPP", "Up" if connected else "Down"],
        ]
        if not gps_enabled:
            gps_rows = [
                ["Fix", "Disabled"],
                ["Lat", "--"],
                ["Lng", "--"],
                ["Alt", "--"],
                ["Speed", "--"],
            ]
        elif gps_payload.get("has_fix", False):
            gps_rows = [
                ["Fix", "Yes"],
                ["Lat", f"{float(gps_payload.get('lat', 0.0) or 0.0):.6f}"],
                ["Lng", f"{float(gps_payload.get('lng', 0.0) or 0.0):.6f}"],
                ["Alt", f"{float(gps_payload.get('altitude', 0.0) or 0.0):.1f}m"],
                ["Speed", f"{float(gps_payload.get('speed', 0.0) or 0.0):.1f}km/h"],
            ]
        else:
            gps_rows = [
                [
                    "Fix",
                    {
                        "disabled": "Disabled",
                        "starting": "Starting",
                        "searching": "Searching",
                        "unavailable": "Unavailable",
                    }.get(
                        "disabled"
                        if not enabled or not gps_enabled
                        else ("fix" if gps_payload.get("has_fix", False) else "searching"),
                        "Searching",
                    ),
                ],
                ["Lat", "--"],
                ["Lng", "--"],
                ["Alt", "--"],
                ["Speed", "--"],
            ]
    return {
        "enabled": enabled,
        "gps_enabled": gps_enabled,
        "config_dir": "config",
        "state": state,
        "sim_ready": enabled,
        "registered": enabled,
        "carrier": "Telekom.de" if enabled else "",
        "network_type": "4G" if enabled else "",
        "signal": {"csq": 20 if enabled else None, "bars": 3 if enabled else 0},
        "ppp": {
            "up": connected,
            "interface": "ppp0" if enabled else "",
            "pid": 1234 if connected else None,
            "default_route_owned": connected,
            "last_failure": "",
        },
        "gps": gps_payload,
        "connected": connected,
        "gps_has_fix": bool(gps_payload.get("has_fix", False)),
        "connection_type": "4g" if enabled else "none",
        "network_status": network_status,
        "gps_status": (
            "disabled"
            if not enabled or not gps_enabled
            else ("fix" if gps_payload.get("has_fix", False) else "searching")
        ),
        "recovering": False,
        "retryable": True,
        "reconnect_attempts": 0,
        "next_retry_at_ms": None,
        "error_code": "",
        "error_message": "",
        "updated_at_ms": 1,
        "app_state": {
            "network_enabled": enabled,
            "signal_bars": 3 if enabled else 0,
            "connection_type": "4g" if enabled else "none",
            "connected": connected,
            "gps_has_fix": bool(gps_payload.get("has_fix", False)),
        },
        "views": {
            "setup": {
                "network_enabled": enabled,
                "gps_refresh_allowed": enabled and gps_enabled,
                "network_rows": network_rows,
                "gps_rows": gps_rows,
            },
            "cli": {
                "probe_ok": enabled,
                "probe_error": "" if enabled else "network module disabled in config/network/cellular.yaml",
                "status_lines": [
                    f"phase={state}",
                    f"sim_ready={enabled}",
                    f"carrier={'Telekom.de' if enabled else 'unknown'}",
                    f"network_type={'4G' if enabled else 'unknown'}",
                    f"signal_csq={20 if enabled else 'unknown'}",
                    f"signal_bars={3 if enabled else 0}",
                    f"ppp_up={connected}",
                    f"error={'none' if enabled else 'network module disabled in config/network/cellular.yaml'}",
                ],
            },
        },
    }


class FakeNetworkRuntime:
    """Minimal Rust-backed network runtime double."""

    def __init__(
        self,
        snapshot: dict[str, object],
        *,
        refreshed_snapshot: dict[str, object] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._refreshed_snapshot = refreshed_snapshot
        self.query_gps_calls = 0
        self.available = True

    def snapshot(self) -> dict[str, object]:
        return self._snapshot

    def is_available(self) -> bool:
        return self.available

    def query_gps(self) -> bool:
        self.query_gps_calls += 1
        if self._refreshed_snapshot is not None:
            self._snapshot = self._refreshed_snapshot
        return True


def test_network_page_online():
    """Network page should show Online status with carrier info."""
    runtime = FakeNetworkRuntime(_runtime_snapshot(state="online", connected=True))
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()
    rows = screen._build_network_rows()
    assert ("Status", "Online") in rows
    assert ("Carrier", "Telekom.de") in rows
    assert ("Type", "4G") in rows
    assert ("PPP", "Up") in rows


def test_network_page_disabled():
    """Network page should show Disabled when network is off."""
    runtime = FakeNetworkRuntime(_runtime_snapshot(enabled=False, connected=False, gps_enabled=False))
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_network_page_no_runtime():
    """Network page should show Disabled when no network runtime exists."""
    screen = PowerScreen(FakeDisplay())
    screen.enter()
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_gps_page_with_fix():
    """GPS page should show coordinates when fix is available."""
    runtime = FakeNetworkRuntime(
        _runtime_snapshot(
            gps={
                "has_fix": True,
                "lat": 48.8738,
                "lng": 2.3522,
                "altitude": 349.6,
                "speed": 0.0,
                "timestamp": "2026-04-30T10:00:00Z",
                "last_query_result": "fix",
            }
        )
    )
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()
    rows = screen._build_gps_rows()
    assert ("Fix", "Yes") in rows
    assert any("48.8738" in value for _, value in rows)
    assert any("2.3522" in value for _, value in rows)


def test_gps_page_no_fix():
    """GPS page should show a searching state when GPS has no fix yet."""
    runtime = FakeNetworkRuntime(_runtime_snapshot(state="registered", connected=False))
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()
    rows = screen._build_gps_rows()
    assert ("Fix", "Searching") in rows
    assert ("Lat", "--") in rows


def test_gps_page_render_does_not_query_coordinates():
    """GPS render helpers should consume cached state instead of querying coordinates."""

    runtime = FakeNetworkRuntime(
        _runtime_snapshot(
            connected=False,
            state="registered",
            gps={
                "has_fix": True,
                "lat": 48.8738,
                "lng": 2.3522,
                "altitude": 349.6,
                "speed": 0.0,
                "timestamp": "2026-04-30T10:00:00Z",
                "last_query_result": "fix",
            },
        )
    )
    screen = PowerScreen(
        FakeDisplay(),
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
        actions=build_power_screen_actions(network_runtime=runtime),
    )
    screen.enter()
    screen.page_index = 2

    payload = screen.lvgl_payload()

    assert runtime.query_gps_calls == 0
    assert payload.title_text == "GPS"
    assert payload.items == (
        "Fix: Yes",
        "Lat: 48.873800",
        "Lng: 2.352200",
        "Alt: 349.6m",
        "Speed: 0.0km/h",
    )


def test_active_gps_page_refreshes_coordinates_via_explicit_state_hook():
    """The GPS Setup page should only query coordinates through an explicit refresh hook."""

    initial_snapshot = _runtime_snapshot(state="registered", connected=False)
    refreshed_snapshot = {
        **initial_snapshot,
        "gps": {
            "has_fix": True,
            "lat": 48.8738,
            "lng": 2.3522,
            "altitude": 349.6,
            "speed": 0.0,
            "timestamp": "2026-04-30T10:00:00Z",
            "last_query_result": "fix",
        },
        "gps_has_fix": True,
        "gps_status": "fix",
        "app_state": {
            **dict(initial_snapshot["app_state"]),
            "gps_has_fix": True,
        },
        "views": {
            **dict(initial_snapshot["views"]),
            "setup": {
                **dict(initial_snapshot["views"]["setup"]),
                "gps_rows": [
                    ["Fix", "Yes"],
                    ["Lat", "48.873800"],
                    ["Lng", "2.352200"],
                    ["Alt", "349.6m"],
                    ["Speed", "0.0km/h"],
                ],
            },
        },
    }
    runtime = FakeNetworkRuntime(initial_snapshot, refreshed_snapshot=refreshed_snapshot)
    screen = PowerScreen(
        FakeDisplay(),
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
        actions=build_power_screen_actions(network_runtime=runtime),
    )
    screen.enter()
    screen.page_index = 2

    screen.refresh_prepared_state(allow_gps_refresh=True)
    payload = screen.lvgl_payload()

    assert runtime.query_gps_calls == 1
    assert payload.title_text == "GPS"
    assert "Lat: 48.873800" in payload.items


def test_power_screen_hides_cached_snapshot_when_runtime_is_unavailable() -> None:
    """Prepared state should not surface stale network rows once the worker is unavailable."""

    runtime = FakeNetworkRuntime(_runtime_snapshot())
    runtime.available = False
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()

    assert screen._build_network_rows() == [("Status", "Disabled")]


def test_build_pages_includes_network_when_enabled():
    """build_pages should include Network and GPS pages when network is enabled."""
    runtime = FakeNetworkRuntime(_runtime_snapshot())
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()
    pages = screen.build_pages()
    titles = [page.title for page in pages]
    assert "Network" in titles
    assert "GPS" in titles
    assert titles.index("Network") == 1
    assert titles.index("GPS") == 2


def test_build_pages_excludes_network_when_disabled():
    """build_pages should omit Network and GPS pages when network is disabled."""
    screen = PowerScreen(FakeDisplay())
    screen.enter()
    pages = screen.build_pages()
    titles = [page.title for page in pages]
    assert "Network" not in titles
    assert "GPS" not in titles


def test_network_page_uses_rust_setup_projection_rows() -> None:
    runtime = FakeNetworkRuntime(
        {
            **_runtime_snapshot(enabled=False, connected=False, gps_enabled=False),
            "views": {
                "setup": {
                    "network_enabled": True,
                    "gps_refresh_allowed": True,
                    "network_rows": [
                        ["Status", "Online"],
                        ["Carrier", "Telekom.de"],
                        ["Type", "4G"],
                        ["Signal", "3/4"],
                        ["PPP", "Up"],
                    ],
                    "gps_rows": [
                        ["Fix", "Searching"],
                        ["Lat", "--"],
                        ["Lng", "--"],
                        ["Alt", "--"],
                        ["Speed", "--"],
                    ],
                }
            },
        }
    )
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_runtime=runtime),
    )
    screen.enter()

    assert screen._build_network_rows() == [
        ("Status", "Online"),
        ("Carrier", "Telekom.de"),
        ("Type", "4G"),
        ("Signal", "3/4"),
        ("PPP", "Up"),
    ]


def test_gps_refresh_uses_rust_setup_projection_allow_flag() -> None:
    runtime = FakeNetworkRuntime(
        {
            **_runtime_snapshot(enabled=False, connected=False, gps_enabled=False),
            "views": {
                "setup": {
                    "network_enabled": True,
                    "gps_refresh_allowed": True,
                    "network_rows": [["Status", "Online"]],
                    "gps_rows": [
                        ["Fix", "Searching"],
                        ["Lat", "--"],
                        ["Lng", "--"],
                        ["Alt", "--"],
                        ["Speed", "--"],
                    ],
                }
            },
        }
    )
    actions = build_power_screen_actions(network_runtime=runtime)

    assert actions.refresh_gps is not None
    assert actions.refresh_gps() is True
    assert runtime.query_gps_calls == 1
