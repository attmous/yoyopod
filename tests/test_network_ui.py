"""Unit tests for Network and GPS Setup pages."""

from __future__ import annotations

from yoyopod.app_context import AppContext
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo
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


class FakeNetworkManager:
    """Minimal network manager double."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        gps_enabled: bool = True,
        phase: ModemPhase = ModemPhase.ONLINE,
    ) -> None:
        self.config = type("Config", (), {"enabled": enabled, "gps_enabled": gps_enabled})()
        self._state = ModemState(
            phase=phase,
            signal=SignalInfo(csq=20),
            carrier="Telekom.de",
            network_type="4G",
            sim_ready=True,
        )
        self.query_gps_calls = 0

    @property
    def modem_state(self) -> ModemState:
        return self._state

    def query_gps(self):
        self.query_gps_calls += 1
        return self._state.gps


def test_network_page_online():
    """Network page should show Online status with carrier info."""
    nm = FakeNetworkManager(phase=ModemPhase.ONLINE)
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
    )
    rows = screen._build_network_rows()
    assert ("Status", "Online") in rows
    assert ("Carrier", "Telekom.de") in rows
    assert ("Type", "4G") in rows
    assert ("PPP", "Up") in rows


def test_network_page_disabled():
    """Network page should show Disabled when network is off."""
    nm = FakeNetworkManager(enabled=False)
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
    )
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_network_page_no_manager():
    """Network page should show Disabled when no network manager."""
    screen = PowerScreen(FakeDisplay())
    rows = screen._build_network_rows()
    assert rows == [("Status", "Disabled")]


def test_gps_page_with_fix():
    """GPS page should show coordinates when fix is available."""
    nm = FakeNetworkManager()
    nm._state.gps = GpsCoordinate(lat=48.8738, lng=2.3522, altitude=349.6, speed=0.0)
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
    )
    rows = screen._build_gps_rows()
    assert ("Fix", "Yes") in rows
    assert any("48.8738" in v for _, v in rows)
    assert any("2.3522" in v for _, v in rows)


def test_gps_page_no_fix():
    """GPS page should show a searching state when GPS has no fix yet."""
    nm = FakeNetworkManager()
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
    )
    rows = screen._build_gps_rows()
    assert ("Fix", "Searching") in rows
    assert ("Lat", "--") in rows


def test_gps_page_render_does_not_query_coordinates():
    """GPS render helpers should consume cached state instead of querying coordinates."""

    nm = FakeNetworkManager()
    nm._state.gps = GpsCoordinate(lat=48.8738, lng=2.3522, altitude=349.6, speed=0.0)
    screen = PowerScreen(
        FakeDisplay(),
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        state_provider=build_power_screen_state_provider(network_manager=nm),
        actions=build_power_screen_actions(network_manager=nm),
    )
    screen.enter()
    screen.page_index = 2

    payload = screen.lvgl_payload()

    assert nm.query_gps_calls == 0
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

    nm = FakeNetworkManager()
    nm._state.gps = GpsCoordinate(lat=48.8738, lng=2.3522, altitude=349.6, speed=0.0)
    screen = PowerScreen(
        FakeDisplay(),
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        state_provider=build_power_screen_state_provider(network_manager=nm),
        actions=build_power_screen_actions(network_manager=nm),
    )
    screen.enter()
    screen.page_index = 2

    screen.refresh_prepared_state(force=True, allow_gps_refresh=True, reason="test")
    payload = screen.lvgl_payload()

    assert nm.query_gps_calls == 1
    assert payload.title_text == "GPS"
    assert "Lat: 48.873800" in payload.items


def test_build_pages_includes_network_when_enabled():
    """build_pages should include Network and GPS pages when network is enabled."""
    nm = FakeNetworkManager()
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
    )
    pages = screen.build_pages()
    titles = [p.title for p in pages]
    assert "Network" in titles
    assert "GPS" in titles
    assert titles.index("Network") == 1  # after Power
    assert titles.index("GPS") == 2  # after Network


def test_build_pages_excludes_network_when_disabled():
    """build_pages should omit Network and GPS pages when network is disabled."""
    screen = PowerScreen(FakeDisplay())
    pages = screen.build_pages()
    titles = [p.title for p in pages]
    assert "Network" not in titles
    assert "GPS" not in titles
