"""Focused tests for the LVGL-only Whisplay adapter hot paths."""

from __future__ import annotations

import pytest
from pathlib import Path
from struct import unpack
from types import SimpleNamespace

from yoyopod.ui.display.contracts import WhisplayProductionRenderContractError
from yoyopod.ui.display.adapters.whisplay import (
    WhisplayDisplayAdapter,
)
from yoyopod.ui.display.adapters.whisplay_gpiod_shim import _patch_vendor_gpiod_compat


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


def _read_png_dimensions(path: Path) -> tuple[int, int]:
    """Return `(width, height)` from a PNG file without third-party dependencies."""

    payload = path.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert payload[12:16] == b"IHDR"
    return unpack(">II", payload[16:24])


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


def test_production_whisplay_rejects_non_lvgl_renderer() -> None:
    """Real Whisplay runs must not silently keep the retired raster path."""

    with pytest.raises(WhisplayProductionRenderContractError, match="require the LVGL renderer"):
        WhisplayDisplayAdapter(simulate=False, renderer="pil")


def test_production_whisplay_refuses_missing_driver(monkeypatch) -> None:
    """Real Whisplay runs should fail loudly when the driver is unavailable."""

    import yoyopod.ui.display.adapters.whisplay as whisplay_module

    monkeypatch.setattr(whisplay_module, "HAS_HARDWARE", False)

    with pytest.raises(WhisplayProductionRenderContractError, match="driver is unavailable"):
        WhisplayDisplayAdapter(simulate=False, renderer="lvgl")


def test_rgb565_region_flush_updates_device_and_framebuffer() -> None:
    """RGB565 flushes should update both the hardware device and framebuffer."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.simulate = False
    adapter.ui_backend = type("Backend", (), {"available": True})()
    adapter.device = FakeDevice()

    payload = bytes.fromhex("f80007e0")
    adapter.draw_rgb565_region(0, 0, 2, 1, payload)

    assert adapter.device.draw_calls == [(0, 0, 2, 1, payload)]
    assert bytes(adapter._framebuffer.data[:4]) == payload


def test_simulated_whisplay_flush_pushes_browser_preview() -> None:
    """Simulation should surface flushes through the attached browser preview."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    preview_updates: list[str] = []
    adapter.web_server = type(
        "Server",
        (),
        {"send_display_update": lambda _self, image: preview_updates.append(image)},
    )()

    adapter.draw_rgb565_region(0, 0, 2, 1, bytes.fromhex("f80007e0"))

    assert len(preview_updates) == 1
    assert preview_updates[0]


def test_save_screenshot_writes_png_from_framebuffer(tmp_path) -> None:
    """Saving a screenshot should emit a PNG from the RGB565 framebuffer."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.draw_rgb565_region(0, 0, 2, 1, bytes.fromhex("f80007e0"))
    screenshot_path = tmp_path / "framebuffer.png"

    assert adapter.save_screenshot(str(screenshot_path)) is True
    assert _read_png_dimensions(screenshot_path) == (adapter.WIDTH, adapter.HEIGHT)


def test_readback_screenshot_decodes_rgb565_swapped_pixels(tmp_path) -> None:
    """Readback screenshots should write a valid PNG from shim RGB565 data."""

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
    assert _read_png_dimensions(screenshot_path) == (adapter.WIDTH, adapter.HEIGHT)


def test_simulated_whisplay_adapter_does_not_own_browser_preview() -> None:
    """The hardware adapter should stay independent from the simulation web preview."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.clear()
    adapter.update()

    assert adapter.web_server is None


def test_get_backend_kind_tracks_lvgl_initialization_state() -> None:
    """Backend kind should only report LVGL once the retained UI backend is live."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")

    assert adapter.get_backend_kind() == "unavailable"

    adapter.ui_backend = type("Backend", (), {"initialized": True})()

    assert adapter.get_backend_kind() == "lvgl"


def test_immediate_draw_methods_raise_after_lvgl_only_cut() -> None:
    """Legacy immediate draw helpers should fail loudly after the LVGL hard cut."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")

    with pytest.raises(RuntimeError, match="retired with the LVGL-only cut"):
        adapter.text("Hello", 1, 1)
    with pytest.raises(RuntimeError, match="retired with the LVGL-only cut"):
        adapter.rectangle(0, 0, 10, 10)
    with pytest.raises(RuntimeError, match="retired with the LVGL-only cut"):
        adapter.circle(5, 5, 3)
    with pytest.raises(RuntimeError, match="retired with the LVGL-only cut"):
        adapter.line(0, 0, 10, 10)


def test_timing_snapshot_tracks_full_frame_and_partial_flushes() -> None:
    """The adapter should expose recent timing metrics for both update paths."""

    adapter = WhisplayDisplayAdapter(simulate=True, renderer="lvgl")
    adapter.clear()
    adapter.draw_rgb565_region(0, 0, 2, 1, bytes.fromhex("f80007e0"))

    adapter.simulate = False
    adapter.device = FakeDevice()
    adapter.update()

    snapshot = adapter.timing_snapshot()

    assert snapshot["full_frame_updates"] == 1
    assert snapshot["partial_flushes"] == 1
    assert snapshot["last_full_frame_total_ms"] >= 0.0
    assert snapshot["last_partial_flush_total_ms"] >= 0.0
    assert snapshot["avg_partial_flush_ms"] >= 0.0
