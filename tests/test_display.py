#!/usr/bin/env python3
"""Smoke tests for current display and screen rendering paths."""

import pytest

from yoyopod.app_context import AppContext
from yoyopod.ui.display import Display, get_hardware_info
from yoyopod.ui.display.adapters.pimoroni import PimoroniDisplayAdapter
from yoyopod.ui.screens import HomeScreen, MenuScreen, NowPlayingScreen


@pytest.fixture
def display():
    """Create a simulation display and clean it up after the test."""
    test_display = Display(simulate=True)
    try:
        yield test_display
    finally:
        test_display.cleanup()


@pytest.fixture
def context() -> AppContext:
    """Create an app context with a demo playlist loaded."""
    app_context = AppContext()
    playlist = app_context.create_demo_playlist()
    app_context.set_playlist(playlist)
    app_context.update_system_status(battery=85, signal=3, connected=True)
    app_context.play()
    app_context.media.playback.position = 45.0
    return app_context


def test_core_screens_render_without_hardware(display: Display, context: AppContext) -> None:
    """Core screens should render cleanly in simulation mode."""
    screens = [
        HomeScreen(display, context),
        MenuScreen(display, context, items=["Music", "Podcasts", "Stories", "Settings"]),
        NowPlayingScreen(display, context),
    ]

    for screen in screens:
        screen.enter()
        screen.render()
        screen.exit()


def test_rendering_still_works_after_state_changes(display: Display, context: AppContext) -> None:
    """Menu and now playing screens should still render after local state changes."""
    menu_screen = MenuScreen(display, context, items=["Music", "Podcasts", "Stories", "Settings"])
    now_playing_screen = NowPlayingScreen(display, context)

    menu_screen.select_next()
    menu_screen.select_next()
    menu_screen.render()

    context.next_track()
    context.pause()
    now_playing_screen.render()


def test_simulate_mode_uses_whisplay_sized_simulation_adapter() -> None:
    """Simulation mode should use the dedicated Whisplay-like simulation adapter."""

    class FakeServer:
        def start(self) -> None:
            pass

    import yoyopod.ui.web_server as web_server

    original_get_server = web_server.get_server
    web_server.get_server = lambda *args, **kwargs: FakeServer()
    try:
        display = Display(simulate=True)
    finally:
        web_server.get_server = original_get_server

    try:
        adapter = display.get_adapter()
        assert adapter.DISPLAY_TYPE == "simulation"
        assert adapter.SIMULATED_HARDWARE == "whisplay"
        assert display.WIDTH == 240
        assert display.HEIGHT == 280
        assert display.ORIENTATION == "portrait"
    finally:
        display.cleanup()


def test_simulate_flag_overrides_explicit_hardware_to_simulation_adapter() -> None:
    """The simulate flag should override the configured hardware selection."""

    class FakeServer:
        def start(self) -> None:
            pass

    import yoyopod.ui.web_server as web_server

    original_get_server = web_server.get_server
    web_server.get_server = lambda *args, **kwargs: FakeServer()
    try:
        display = Display(hardware="whisplay", simulate=True)
    finally:
        web_server.get_server = original_get_server

    try:
        adapter = display.get_adapter()
        assert adapter.DISPLAY_TYPE == "simulation"
        assert adapter.SIMULATED_HARDWARE == "whisplay"
        assert display.WIDTH == 240
        assert display.HEIGHT == 280
        assert display.ORIENTATION == "portrait"
    finally:
        display.cleanup()


def test_simulation_display_update_pushes_browser_preview() -> None:
    """The simulation adapter should remain the only browser-preview owner."""

    class FakeServer:
        def __init__(self) -> None:
            self.started = False
            self.images: list[str] = []

        def start(self) -> None:
            self.started = True

        def send_display_update(self, image: str) -> None:
            self.images.append(image)

    fake_server = FakeServer()

    import yoyopod.ui.web_server as web_server

    original_get_server = web_server.get_server
    web_server.get_server = lambda *args, **kwargs: fake_server
    try:
        display = Display(simulate=True)
    finally:
        web_server.get_server = original_get_server

    try:
        display.clear()
        display.update()

        assert fake_server.started is True
        assert len(fake_server.images) == 1
        assert fake_server.images[0]
    finally:
        display.cleanup()


def test_pimoroni_hardware_info_reports_explicit_display_type() -> None:
    """Display info should expose Pimoroni's typed adapter identity."""

    adapter = PimoroniDisplayAdapter(simulate=True)
    try:
        info = get_hardware_info(adapter)
        assert info["display_type"] == "pimoroni"
        assert info["simulated_hardware"] is None
    finally:
        adapter.cleanup()
