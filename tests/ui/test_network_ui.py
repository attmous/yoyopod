"""Unit tests for Network and GPS Setup pages."""

from __future__ import annotations

from dataclasses import replace

from yoyopod.core import AppContext
from yoyopod.integrations.network.snapshot import (
    RustNetworkGpsSnapshot,
    RustNetworkPppSnapshot,
    RustNetworkSignalSnapshot,
    RustNetworkSnapshot,
)
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
    gps: RustNetworkGpsSnapshot | None = None,
) -> RustNetworkSnapshot:
    return RustNetworkSnapshot(
        enabled=enabled,
        gps_enabled=gps_enabled,
        config_dir="config",
        state=state,
        sim_ready=enabled,
        registered=enabled,
        carrier="Telekom.de" if enabled else "",
        network_type="4G" if enabled else "",
        signal=RustNetworkSignalSnapshot(csq=20 if enabled else None, bars=3 if enabled else 0),
        ppp=RustNetworkPppSnapshot(
            up=connected,
            interface="ppp0" if enabled else "",
            pid=1234 if connected else None,
            default_route_owned=connected,
            last_failure="",
        ),
        gps=(
            gps
            if gps is not None
            else RustNetworkGpsSnapshot(has_fix=False, last_query_result="idle")
        ),
        recovering=False,
        retryable=True,
        reconnect_attempts=0,
        next_retry_at_ms=None,
        error_code="",
        error_message="",
        updated_at_ms=1,
    )


class FakeNetworkRuntime:
    """Minimal Rust-backed network runtime double."""

    def __init__(
        self,
        snapshot: RustNetworkSnapshot,
        *,
        refreshed_snapshot: RustNetworkSnapshot | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._refreshed_snapshot = refreshed_snapshot
        self.query_gps_calls = 0

    def snapshot(self) -> RustNetworkSnapshot:
        return self._snapshot

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
            gps=RustNetworkGpsSnapshot(
                has_fix=True,
                lat=48.8738,
                lng=2.3522,
                altitude=349.6,
                speed=0.0,
                timestamp="2026-04-30T10:00:00Z",
                last_query_result="fix",
            )
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
            gps=RustNetworkGpsSnapshot(
                has_fix=True,
                lat=48.8738,
                lng=2.3522,
                altitude=349.6,
                speed=0.0,
                timestamp="2026-04-30T10:00:00Z",
                last_query_result="fix",
            ),
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
    refreshed_snapshot = replace(
        initial_snapshot,
        gps=RustNetworkGpsSnapshot(
            has_fix=True,
            lat=48.8738,
            lng=2.3522,
            altitude=349.6,
            speed=0.0,
            timestamp="2026-04-30T10:00:00Z",
            last_query_result="fix",
        ),
    )
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
