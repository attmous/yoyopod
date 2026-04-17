"""Unit tests for Network and GPS Setup pages."""

from __future__ import annotations

from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState, SignalInfo
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


def test_active_gps_page_refreshes_coordinates_before_render():
    """The GPS Setup page should trigger a GPS query when it becomes active."""

    nm = FakeNetworkManager()
    nm._state.gps = GpsCoordinate(lat=48.8738, lng=2.3522, altitude=349.6, speed=0.0)
    screen = PowerScreen(
        FakeDisplay(),
        state_provider=build_power_screen_state_provider(network_manager=nm),
        actions=build_power_screen_actions(network_manager=nm),
    )
    screen.page_index = 2

    pages = screen._build_pages_for_display()

    assert nm.query_gps_calls == 1
    gps_page = pages[2]
    assert gps_page.title == "GPS"
    assert ("Fix", "Yes") in gps_page.rows
    assert any("48.8738" in value for _, value in gps_page.rows)


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
