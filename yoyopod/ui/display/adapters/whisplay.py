"""PiSugar Whisplay HAT adapter with an LVGL-only render path."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import time

from loguru import logger

from yoyopod.ui.display.adapters.whisplay_gpiod_shim import _patch_vendor_gpiod_compat
from yoyopod.ui.display.adapters.whisplay_paths import ensure_whisplay_driver_on_path
from yoyopod.ui.display.contracts import (
    WhisplayProductionRenderContractError,
    build_whisplay_production_contract_message,
)
from yoyopod.ui.display.hal import DisplayHAL
from yoyopod.ui.display.rgb565 import Rgb565FrameBuffer, rgb565_bytes_to_png

DRIVER_PATH = ensure_whisplay_driver_on_path()

try:
    _whisplay_driver = import_module("WhisPlay")
    _patch_vendor_gpiod_compat(_whisplay_driver)
    WhisPlayBoard = _whisplay_driver.WhisPlayBoard
    HAS_HARDWARE = True
except ImportError:
    HAS_HARDWARE = False
    if DRIVER_PATH:
        logger.warning(
            "WhisPlay library not importable from {} - adapter will require simulation mode",
            DRIVER_PATH.parent,
        )
    else:
        logger.warning("WhisPlay library not available - adapter will require simulation mode")


class WhisplayDisplayAdapter(DisplayHAL):
    """Hardware adapter for the PiSugar Whisplay LVGL runtime."""

    DISPLAY_TYPE = "whisplay"
    WIDTH = 240
    HEIGHT = 280
    ORIENTATION = "portrait"
    STATUS_BAR_HEIGHT = 25
    _SLOW_FULL_FRAME_UPDATE_THRESHOLD_SECONDS = 0.03
    _SLOW_REGION_FLUSH_THRESHOLD_SECONDS = 0.008
    _PARTIAL_FLUSH_TIMING_LOG_INTERVAL = 60

    def __init__(
        self,
        simulate: bool = False,
        renderer: str = "lvgl",
        lvgl_buffer_lines: int = 40,
        *,
        enforce_production_contract: bool | None = None,
    ) -> None:
        requested_simulation = bool(simulate)
        self._production_contract_enforced = (
            not requested_simulation
            if enforce_production_contract is None
            else bool(enforce_production_contract)
        )
        self.requested_renderer = renderer.lower().strip() or "lvgl"
        if self.requested_renderer != "lvgl":
            self._raise_production_contract_error("The Whisplay adapter now requires LVGL")

        if self._production_contract_enforced and not HAS_HARDWARE:
            self._raise_production_contract_error("Whisplay driver is unavailable on this host")

        self.renderer = "lvgl"
        self.simulate = requested_simulation or not HAS_HARDWARE
        self.SIMULATED_HARDWARE = "whisplay" if self.simulate else None
        self.device = None
        self.web_server = None
        self.lvgl_buffer_lines = max(1, int(lvgl_buffer_lines))
        self.ui_backend = None
        self._force_shadow_buffer_sync = False
        self._framebuffer = Rgb565FrameBuffer(self.WIDTH, self.HEIGHT)
        self._timing_metrics: dict[str, float | int] = {
            "full_frame_updates": 0,
            "last_full_frame_device_ms": 0.0,
            "last_full_frame_total_ms": 0.0,
            "max_full_frame_total_ms": 0.0,
            "partial_flushes": 0,
            "framebuffer_updates": 0,
            "last_partial_flush_device_ms": 0.0,
            "last_partial_flush_framebuffer_ms": 0.0,
            "last_partial_flush_total_ms": 0.0,
            "max_partial_flush_total_ms": 0.0,
            "partial_flush_total_ms": 0.0,
        }

        if not self.simulate:
            try:
                self.device = WhisPlayBoard()
                self.device.set_backlight(100)
                self.device.set_rgb(0, 100, 200)
                logger.info("Whisplay HAT initialized (240x280 portrait)")
            except Exception as exc:  # pragma: no cover - hardware-only path
                if self._production_contract_enforced:
                    self._raise_production_contract_error(
                        f"Whisplay hardware initialization failed: {exc}",
                    )
                logger.error("Failed to initialize Whisplay hardware: {}", exc)
                self.simulate = True
                self.device = None
        else:
            logger.info("Whisplay display adapter running in LVGL simulation mode")

        from yoyopod.ui.lvgl_binding import LvglDisplayBackend

        self.ui_backend = LvglDisplayBackend(
            self,
            buffer_lines=self.lvgl_buffer_lines,
        )
        if self._production_contract_enforced and not self.ui_backend.available:
            self._raise_production_contract_error("Whisplay LVGL shim is unavailable during startup")

    @staticmethod
    def _raise_production_contract_error(reason: str) -> None:
        message = build_whisplay_production_contract_message(reason)
        logger.error(message)
        raise WhisplayProductionRenderContractError(message)

    def _raise_immediate_draw_error(self, operation: str) -> None:
        raise RuntimeError(
            f"WhisplayDisplayAdapter.{operation}() was retired with the LVGL-only cut; "
            "render via LVGL scenes instead"
        )

    def _sync_simulation_preview(self) -> None:
        if self.web_server is None:
            return
        try:
            self.web_server.send_display_update(self._framebuffer.to_png_base64())
        except Exception as exc:
            logger.warning("Failed to send simulation preview update: {}", exc)

    def _record_partial_flush_timing(
        self,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        device_seconds: float,
        framebuffer_seconds: float,
        total_seconds: float,
    ) -> None:
        metrics = self._timing_metrics
        metrics["partial_flushes"] = int(metrics["partial_flushes"]) + 1
        metrics["framebuffer_updates"] = int(metrics["framebuffer_updates"]) + 1
        metrics["last_partial_flush_device_ms"] = device_seconds * 1000.0
        metrics["last_partial_flush_framebuffer_ms"] = framebuffer_seconds * 1000.0
        metrics["last_partial_flush_total_ms"] = total_seconds * 1000.0
        metrics["partial_flush_total_ms"] = float(metrics["partial_flush_total_ms"]) + (
            total_seconds * 1000.0
        )
        metrics["max_partial_flush_total_ms"] = max(
            float(metrics["max_partial_flush_total_ms"]),
            total_seconds * 1000.0,
        )

        if total_seconds >= self._SLOW_REGION_FLUSH_THRESHOLD_SECONDS:
            logger.warning(
                "Slow Whisplay RGB565 flush: area={}x{} at {},{} total_ms={:.1f} device_ms={:.1f} framebuffer_ms={:.1f}",
                width,
                height,
                x,
                y,
                total_seconds * 1000.0,
                device_seconds * 1000.0,
                framebuffer_seconds * 1000.0,
            )
            return

        flush_count = int(metrics["partial_flushes"])
        if flush_count % self._PARTIAL_FLUSH_TIMING_LOG_INTERVAL == 0:
            average_ms = float(metrics["partial_flush_total_ms"]) / max(1, flush_count)
            logger.debug(
                "Whisplay RGB565 flush timing: flushes={} avg_ms={:.1f} max_ms={:.1f}",
                flush_count,
                average_ms,
                float(metrics["max_partial_flush_total_ms"]),
            )

    def _record_full_frame_timing(
        self,
        *,
        device_seconds: float,
        total_seconds: float,
    ) -> None:
        metrics = self._timing_metrics
        metrics["full_frame_updates"] = int(metrics["full_frame_updates"]) + 1
        metrics["last_full_frame_device_ms"] = device_seconds * 1000.0
        metrics["last_full_frame_total_ms"] = total_seconds * 1000.0
        metrics["max_full_frame_total_ms"] = max(
            float(metrics["max_full_frame_total_ms"]),
            total_seconds * 1000.0,
        )

        if total_seconds >= self._SLOW_FULL_FRAME_UPDATE_THRESHOLD_SECONDS:
            logger.warning(
                "Slow Whisplay full-frame update: device_ms={:.1f} total_ms={:.1f}",
                device_seconds * 1000.0,
                total_seconds * 1000.0,
            )

    def timing_snapshot(self) -> dict[str, float | int]:
        metrics = dict(self._timing_metrics)
        flush_count = int(metrics["partial_flushes"])
        metrics["avg_partial_flush_ms"] = (
            float(metrics["partial_flush_total_ms"]) / max(1, flush_count) if flush_count else 0.0
        )
        return metrics

    def draw_rgb565_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        started_at = time.monotonic()

        device_started_at = started_at
        if not self.simulate and self.device is not None:
            self.device.draw_image(x, y, width, height, pixel_data)
        device_seconds = max(0.0, time.monotonic() - device_started_at)

        framebuffer_started_at = time.monotonic()
        self._framebuffer.paste_region(x, y, width, height, pixel_data)
        if self.simulate:
            self._sync_simulation_preview()
        framebuffer_seconds = max(0.0, time.monotonic() - framebuffer_started_at)

        total_seconds = max(0.0, time.monotonic() - started_at)
        self._record_partial_flush_timing(
            x=x,
            y=y,
            width=width,
            height=height,
            device_seconds=device_seconds,
            framebuffer_seconds=framebuffer_seconds,
            total_seconds=total_seconds,
        )

    def clear(self, color: tuple[int, int, int] | None = None) -> None:
        self._framebuffer.clear(self.COLOR_BLACK if color is None else color)

    def text(
        self,
        text: str,
        x: int,
        y: int,
        color: tuple[int, int, int] | None = None,
        font_size: int = 16,
        font_path: Path | None = None,
    ) -> None:
        self._raise_immediate_draw_error("text")

    def rectangle(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        fill: tuple[int, int, int] | None = None,
        outline: tuple[int, int, int] | None = None,
        width: int = 1,
    ) -> None:
        self._raise_immediate_draw_error("rectangle")

    def circle(
        self,
        x: int,
        y: int,
        radius: int,
        fill: tuple[int, int, int] | None = None,
        outline: tuple[int, int, int] | None = None,
        width: int = 1,
    ) -> None:
        self._raise_immediate_draw_error("circle")

    def line(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: tuple[int, int, int] | None = None,
        width: int = 1,
    ) -> None:
        self._raise_immediate_draw_error("line")

    def image(
        self,
        image_path: Path,
        x: int,
        y: int,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        self._raise_immediate_draw_error("image")

    def status_bar(
        self,
        time_str: str = "--:--",
        battery_percent: int = 100,
        signal_strength: int = 4,
        charging: bool = False,
        external_power: bool = False,
        power_available: bool = True,
    ) -> None:
        self._raise_immediate_draw_error("status_bar")

    def update(self) -> None:
        started_at = time.monotonic()
        device_started_at = started_at
        if not self.simulate and self.device is not None:
            self.device.draw_image(0, 0, self.WIDTH, self.HEIGHT, bytes(self._framebuffer.data))
        device_seconds = max(0.0, time.monotonic() - device_started_at)
        if self.simulate:
            self._sync_simulation_preview()
        total_seconds = max(0.0, time.monotonic() - started_at)
        self._record_full_frame_timing(device_seconds=device_seconds, total_seconds=total_seconds)

    def save_screenshot(self, path: str) -> bool:
        try:
            Path(path).write_bytes(self._framebuffer.to_png_bytes())
            logger.info("Framebuffer screenshot saved to {}", path)
            return True
        except Exception as exc:
            logger.error("Failed to save framebuffer screenshot to {}: {}", path, exc)
            return False

    def save_screenshot_readback(self, path: str) -> bool:
        if self.ui_backend is None or not getattr(self.ui_backend, "initialized", False):
            logger.warning("LVGL backend not available for readback screenshot")
            return False

        binding = getattr(self.ui_backend, "binding", None)
        if binding is None:
            logger.warning("LVGL binding not available for readback screenshot")
            return False

        try:
            pixel_data = binding.snapshot(self.WIDTH, self.HEIGHT)
            if pixel_data is None:
                logger.error("LVGL snapshot returned no data")
                return False

            Path(path).write_bytes(rgb565_bytes_to_png(self.WIDTH, self.HEIGHT, pixel_data))
            logger.info("LVGL readback screenshot saved to {}", path)
            return True
        except Exception as exc:
            logger.error("Failed to save LVGL readback screenshot: {}", exc)
            return False

    def get_backend_kind(self) -> str:
        if self.ui_backend is not None and getattr(self.ui_backend, "initialized", False):
            return "lvgl"
        return "unavailable"

    def get_ui_backend(self):
        return self.ui_backend

    def reset_ui_backend(self) -> None:
        if self.ui_backend is not None:
            self.ui_backend.reset()

    def set_backlight(self, brightness: float) -> None:
        if not self.simulate and self.device is not None:
            try:
                self.device.set_backlight(int(max(0.0, min(1.0, brightness)) * 100))
            except Exception as exc:  # pragma: no cover - hardware-only path
                logger.error("Failed to set Whisplay backlight: {}", exc)

    def get_text_size(self, text: str, font_size: int = 16) -> tuple[int, int]:
        return (int(len(text) * max(6, font_size * 0.6)), font_size)

    def cleanup(self) -> None:
        if self.ui_backend is not None:
            try:
                self.ui_backend.cleanup()
            except Exception as exc:
                logger.error("Error during LVGL backend cleanup: {}", exc)
        if self.device is not None:
            try:
                self.device.set_backlight(0)
                self.device.set_rgb(0, 0, 0)
                self.device.cleanup()
            except Exception as exc:  # pragma: no cover - hardware-only path
                logger.error("Error during Whisplay cleanup: {}", exc)
