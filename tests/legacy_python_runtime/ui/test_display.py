#!/usr/bin/env python3
"""Smoke tests for the LVGL-only display/runtime contract."""

from types import SimpleNamespace

from yoyopod.backends.music import MockMusicBackend, Track
from yoyopod.core import AppContext
from yoyopod.ui.display import Display, get_hardware_info
from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
from yoyopod.ui.screens.voip.in_call import InCallScreen


class FakeServer:
    """Minimal browser-preview double."""

    def __init__(self) -> None:
        self.started = False
        self.images: list[str] = []

    def start(self) -> None:
        self.started = True

    def send_display_update(self, image: str) -> None:
        self.images.append(image)


def _patch_fake_server(monkeypatch) -> FakeServer:
    fake_server = FakeServer()
    import yoyopod.ui.display.adapters.simulation_web.server as web_server

    monkeypatch.setattr(web_server, "get_server", lambda *args, **kwargs: fake_server)
    return fake_server


def test_simulate_mode_uses_simulation_lvgl_adapter(monkeypatch) -> None:
    """Simulation should use its own adapter surface on the shared LVGL path."""

    fake_server = _patch_fake_server(monkeypatch)
    display = Display(simulate=True)

    try:
        adapter = display.get_adapter()
        info = get_hardware_info(adapter)

        assert adapter.DISPLAY_TYPE == "simulation"
        assert adapter.SIMULATED_HARDWARE == "whisplay"
        assert display.WIDTH == 240
        assert display.HEIGHT == 280
        assert display.ORIENTATION == "portrait"
        assert info["display_type"] == "simulation"
        assert info["simulated_hardware"] == "whisplay"
        assert info["simulated"] is True
        assert info["renderer"] == "unavailable"
        assert fake_server.started is True
    finally:
        display.cleanup()


def test_simulate_flag_overrides_explicit_hardware_to_simulation_adapter(monkeypatch) -> None:
    """The simulate flag should still resolve to the simulation adapter surface."""

    _patch_fake_server(monkeypatch)
    display = Display(hardware="whisplay", simulate=True)

    try:
        adapter = display.get_adapter()
        assert adapter.DISPLAY_TYPE == "simulation"
        assert adapter.SIMULATED_HARDWARE == "whisplay"
        assert adapter.simulate is True
    finally:
        display.cleanup()


def test_simulation_display_update_pushes_browser_preview(monkeypatch) -> None:
    """Simulation mode should keep the browser-preview transport alive."""

    fake_server = _patch_fake_server(monkeypatch)
    display = Display(simulate=True)

    try:
        display.clear()
        display.update()

        assert fake_server.started is True
        assert len(fake_server.images) == 1
        assert fake_server.images[0]
    finally:
        display.cleanup()


def test_now_playing_screen_only_requests_visible_ticks_while_playing() -> None:
    """Now-playing should only opt into periodic visible ticks during active playback."""

    context = AppContext()
    backend = MockMusicBackend()
    backend.start()
    backend.current_track = Track(
        uri="demo.mp3",
        name="Demo",
        artists=["Artist"],
        album="Album",
        length=180,
    )
    app = SimpleNamespace(context=context, music_backend=backend)
    screen = NowPlayingScreen(object(), context, app=app)

    assert screen.wants_visible_tick_refresh() is False

    backend.play()

    assert screen.wants_visible_tick_refresh() is True


def test_in_call_screen_always_requests_visible_tick_refresh() -> None:
    """In-call should keep opting into visible ticks for live duration updates."""

    screen = InCallScreen(object(), AppContext())

    assert screen.wants_visible_tick_refresh() is True
