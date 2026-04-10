"""Focused tests for the Whisplay adapter hot paths."""

from __future__ import annotations

from PIL import Image

from yoyopy.ui.display.adapters.whisplay import WhisplayDisplayAdapter


class FakeDevice:
    """Small device double that records RGB565 writes."""

    def __init__(self) -> None:
        self.draw_calls: list[tuple[int, int, int, int, bytes]] = []

    def draw_image(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        self.draw_calls.append((x, y, width, height, pixel_data))


def test_hardware_lvgl_flush_skips_shadow_buffer_sync(monkeypatch) -> None:
    """Hardware LVGL flushes should not mirror every region into PIL."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.simulate = False
    adapter.ui_backend = type("Backend", (), {"available": True})()
    adapter.device = FakeDevice()

    mirrored: list[tuple[int, int, int, int, bytes]] = []
    monkeypatch.setattr(
        adapter,
        "_paste_rgb565_region",
        lambda x, y, width, height, pixel_data: mirrored.append((x, y, width, height, pixel_data)),
    )

    payload = b"\x12\x34" * 8
    adapter.draw_rgb565_region(1, 2, 4, 2, payload)

    assert adapter.device.draw_calls == [(1, 2, 4, 2, payload)]
    assert mirrored == []


def test_simulated_lvgl_flush_keeps_shadow_buffer_for_debug(monkeypatch) -> None:
    """Simulation still needs the PIL shadow buffer for local inspection."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")

    mirrored: list[tuple[int, int, int, int, bytes]] = []
    monkeypatch.setattr(
        adapter,
        "_paste_rgb565_region",
        lambda x, y, width, height, pixel_data: mirrored.append((x, y, width, height, pixel_data)),
    )

    payload = b"\xaa\x55" * 8
    adapter.draw_rgb565_region(0, 0, 4, 2, payload)

    assert mirrored == [(0, 0, 4, 2, payload)]


def test_shadow_screenshot_forces_one_redraw_into_buffer_when_shadow_sync_is_disabled(
    monkeypatch,
) -> None:
    """Hardware LVGL screenshots should force one redraw into the PIL buffer."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.simulate = False
    mirrored: list[tuple[int, int, int, int, bytes]] = []
    saved_paths: list[tuple[str, str]] = []
    adapter.buffer = type(
        "Buffer",
        (),
        {"save": lambda _self, path, fmt: saved_paths.append((path, fmt))},
    )()
    monkeypatch.setattr(
        adapter,
        "_paste_rgb565_region",
        lambda x, y, width, height, pixel_data: mirrored.append((x, y, width, height, pixel_data)),
    )

    class Backend:
        available = True
        initialized = True

        def force_refresh(self) -> None:
            adapter.draw_rgb565_region(1, 2, 2, 1, b"\x12\x34" * 2)

    adapter.ui_backend = Backend()

    assert adapter.save_screenshot("/tmp/test.png") is True
    assert mirrored == [(1, 2, 2, 1, b"\x12\x34" * 2)]
    assert saved_paths == [("/tmp/test.png", "PNG")]


def test_shadow_screenshot_falls_back_to_lvgl_readback_when_force_refresh_is_unavailable(
    monkeypatch,
) -> None:
    """Hardware LVGL screenshots should still fall back to readback when needed."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.simulate = False
    adapter.ui_backend = type("Backend", (), {"available": True, "initialized": False})()

    readback_calls: list[str] = []
    monkeypatch.setattr(
        adapter,
        "save_screenshot_readback",
        lambda path: readback_calls.append(path) or True,
    )

    assert adapter.save_screenshot("/tmp/test.png") is True
    assert readback_calls == ["/tmp/test.png"]


def test_shadow_sync_mode_tracks_runtime_fallback_state_changes() -> None:
    """The sync mode should follow later renderer/simulation fallback changes."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")

    assert adapter.shadow_buffer_sync_enabled is True

    adapter.simulate = False
    adapter.renderer = "lvgl"
    adapter.ui_backend = type("Backend", (), {"available": True})()
    assert adapter.shadow_buffer_sync_enabled is False

    adapter.renderer = "pil"
    assert adapter.shadow_buffer_sync_enabled is True

    adapter.renderer = "lvgl"
    adapter.ui_backend = type("Backend", (), {"available": False})()
    assert adapter.shadow_buffer_sync_enabled is True


def test_readback_screenshot_decodes_rgb565_swapped_pixels(tmp_path) -> None:
    """Readback screenshots should decode the shim's RGB565_SWAPPED contract."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    pixel_data = b"\xf8\x00" * (adapter.WIDTH * adapter.HEIGHT)

    class Binding:
        def snapshot(self, width: int, height: int) -> bytes:
            assert width == adapter.WIDTH
            assert height == adapter.HEIGHT
            return pixel_data

    adapter.ui_backend = type(
        "Backend",
        (),
        {
            "initialized": True,
            "binding": Binding(),
        },
    )()

    screenshot_path = tmp_path / "readback.png"

    assert adapter.save_screenshot_readback(str(screenshot_path)) is True

    with Image.open(screenshot_path) as screenshot:
        assert screenshot.size == (adapter.WIDTH, adapter.HEIGHT)
        assert screenshot.getpixel((0, 0)) == (255, 0, 0)


def test_simulated_whisplay_adapter_does_not_own_browser_preview() -> None:
    """The hardware adapter should stay independent from the simulation web preview."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter.clear()
    adapter.update()

    assert not hasattr(adapter, "web_server")
