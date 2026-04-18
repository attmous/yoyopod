"""Focused tests for the Whisplay adapter hot paths."""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from yoyopod.ui.display.adapters.whisplay import (
    WhisplayDisplayAdapter,
    _patch_vendor_gpiod_compat,
)


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


def test_vendor_gpiod_compat_aliases_pypi_module_shapes() -> None:
    """PyPI gpiod layouts should be normalized for the vendor driver."""

    chip_calls: list[object] = []
    request_calls: list[tuple[object, object]] = []

    class FakeLineRequest:
        DIRECTION_OUTPUT = 3
        DIRECTION_INPUT = 2
        FLAG_BIAS_DISABLE = 8

        def __init__(self) -> None:
            self.consumer = None
            self.request_type = None
            self.flags = None

    class FakeLine:
        def request(self, config: object, default_val: object = None) -> dict[str, object]:
            request_calls.append((config, default_val))
            return {"config": config, "default_val": default_val}

    class FakeChip:
        def get_line(self, offset: int) -> FakeLine:
            assert offset == 7
            return FakeLine()

    fake_gpiod = SimpleNamespace(
        chip=lambda path: chip_calls.append(path) or FakeChip(),
        line_request=FakeLineRequest,
    )
    fake_module = SimpleNamespace(gpiod=fake_gpiod)

    _patch_vendor_gpiod_compat(fake_module)

    assert fake_gpiod.LINE_REQ_DIR_OUT == FakeLineRequest.DIRECTION_OUTPUT
    assert fake_gpiod.LINE_REQ_DIR_IN == FakeLineRequest.DIRECTION_INPUT
    assert fake_gpiod.LINE_REQ_FLAG_BIAS_DISABLE == FakeLineRequest.FLAG_BIAS_DISABLE
    chip = fake_gpiod.Chip("gpiochip0")
    result = chip.get_line(7).request(
        consumer="whisplay",
        type=fake_gpiod.LINE_REQ_DIR_OUT,
        flags=fake_gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
        default_val=1,
    )

    assert result["default_val"] == 1
    assert request_calls[0][0].consumer == "whisplay"
    assert request_calls[0][0].request_type == FakeLineRequest.DIRECTION_OUTPUT
    assert request_calls[0][0].flags == FakeLineRequest.FLAG_BIAS_DISABLE
    assert chip_calls == ["/dev/gpiochip0"]


def test_vendor_gpiod_compat_retries_existing_chip_with_dev_prefix() -> None:
    """Legacy ``gpiod.Chip`` call sites should retry with ``/dev`` when needed."""

    chip_calls: list[object] = []

    def fake_chip(path: object) -> dict[str, object]:
        chip_calls.append(path)
        if path == "gpiochip1":
            raise FileNotFoundError(path)
        return {"path": path}

    fake_gpiod = SimpleNamespace(Chip=fake_chip)
    fake_module = SimpleNamespace(gpiod=fake_gpiod)

    _patch_vendor_gpiod_compat(fake_module)

    assert fake_gpiod.Chip("gpiochip1") == {"path": "/dev/gpiochip1"}
    assert chip_calls == ["gpiochip1", "/dev/gpiochip1"]


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


def test_whisplay_font_cache_reuses_loaded_fonts(monkeypatch) -> None:
    """Repeated text draws should not reload the same font on every call."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter._font_cache.clear()

    original_truetype = ImageFont.truetype
    load_calls: list[tuple[str, int]] = []

    def counting_truetype(path: str, size: int, *args, **kwargs):
        load_calls.append((path, size))
        return original_truetype(path, size, *args, **kwargs)

    monkeypatch.setattr(
        "yoyopod.ui.display.adapters.whisplay.ImageFont.truetype", counting_truetype
    )

    adapter.text("Hello", 4, 4, font_size=16)
    adapter.text("Again", 4, 24, font_size=16)
    adapter.get_text_size("Measured", 16)

    assert len(load_calls) == 1


def test_rgb565_conversion_matches_expected_byte_order() -> None:
    """The optimized conversion should preserve the adapter's big-endian RGB565 contract."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter.WIDTH = 2
    adapter.HEIGHT = 1
    adapter.buffer = Image.new("RGB", (2, 1))
    adapter.draw = ImageDraw.Draw(adapter.buffer)
    adapter.buffer.putdata([(255, 0, 0), (0, 255, 0)])

    assert adapter._convert_to_rgb565() == bytes.fromhex("f80007e0")


def test_rgb565_conversion_matches_reference_for_mixed_pixels() -> None:
    """The bulk conversion should match the historical RGB565 packing rules."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter.WIDTH = 4
    adapter.HEIGHT = 1
    adapter.buffer = Image.new("RGB", (4, 1))
    adapter.draw = ImageDraw.Draw(adapter.buffer)
    pixels = [
        (255, 255, 255),
        (0, 0, 255),
        (17, 34, 51),
        (123, 231, 45),
    ]
    adapter.buffer.putdata(pixels)

    expected = bytearray()
    for red, green, blue in pixels:
        rgb565 = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        expected.extend(((rgb565 >> 8) & 0xFF, rgb565 & 0xFF))

    assert adapter._convert_to_rgb565() == bytes(expected)


def test_paste_rgb565_region_decodes_into_shadow_buffer() -> None:
    """Shadow-buffer region pastes should decode RGB565 bytes back into RGB pixels."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter.WIDTH = 2
    adapter.HEIGHT = 1
    adapter.buffer = Image.new("RGB", (2, 1))
    adapter.draw = ImageDraw.Draw(adapter.buffer)

    adapter._paste_rgb565_region(0, 0, 2, 1, bytes.fromhex("f80007e0"))

    assert adapter.buffer.getpixel((0, 0)) == (255, 0, 0)
    assert adapter.buffer.getpixel((1, 0)) == (0, 255, 0)


def test_timing_snapshot_tracks_full_frame_and_partial_flushes() -> None:
    """The adapter should expose recent timing metrics for both update paths."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="pil")
    adapter.WIDTH = 2
    adapter.HEIGHT = 1
    adapter.buffer = Image.new("RGB", (2, 1))
    adapter.draw = ImageDraw.Draw(adapter.buffer)
    adapter.buffer.putdata([(255, 0, 0), (0, 255, 0)])

    adapter.simulate = False
    adapter.device = FakeDevice()
    adapter.update()

    adapter.simulate = True
    adapter.draw_rgb565_region(0, 0, 2, 1, bytes.fromhex("f80007e0"))

    snapshot = adapter.timing_snapshot()

    assert snapshot["full_frame_updates"] == 1
    assert snapshot["partial_flushes"] == 1
    assert snapshot["last_full_frame_total_ms"] >= 0.0
    assert snapshot["last_partial_flush_total_ms"] >= 0.0
    assert snapshot["avg_partial_flush_ms"] >= 0.0
