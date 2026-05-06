"""LVGL-backed Pimoroni/ST7789 display adapter."""

from __future__ import annotations

from pathlib import Path
import time

from loguru import logger

from yoyopod_cli.config.models.power import PimoroniGpioConfig
from yoyopod_cli.pi.support.display.adapters.st7789_spi import ST7789SpiDriver
from yoyopod_cli.pi.support.display.hal import DisplayHAL
from yoyopod_cli.pi.support.display.rgb565 import Rgb565FrameBuffer, rgb565_bytes_to_png


class PimoroniDisplayAdapter(DisplayHAL):
    """Landscape ST7789 adapter that keeps the adapter surface on the LVGL path."""

    DISPLAY_TYPE = "pimoroni"
    WIDTH = 320
    HEIGHT = 240
    ORIENTATION = "landscape"
    STATUS_BAR_HEIGHT = 20
    _SLOW_FULL_FRAME_UPDATE_THRESHOLD_SECONDS = 0.03
    _SLOW_REGION_FLUSH_THRESHOLD_SECONDS = 0.008

    def __init__(
        self,
        simulate: bool = False,
        *,
        lvgl_buffer_lines: int = 40,
        gpio_config: PimoroniGpioConfig | None = None,
    ) -> None:
        self.simulate = bool(simulate)
        self.SIMULATED_HARDWARE = "pimoroni" if self.simulate else None
        self.device: ST7789SpiDriver | None = None
        self.web_server = None
        self.lvgl_buffer_lines = max(1, int(lvgl_buffer_lines))
        self.ui_backend = None
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
            if gpio_config is None or gpio_config.dc is None or gpio_config.backlight is None:
                logger.warning(
                    "Pimoroni LVGL adapter requested without pimoroni_gpio wiring config; "
                    "falling back to simulation mode",
                )
                self.simulate = True
                self.SIMULATED_HARDWARE = "pimoroni"
            else:
                try:
                    self.device = ST7789SpiDriver(
                        spi_bus=gpio_config.spi_bus,
                        spi_device=gpio_config.spi_device,
                        spi_speed_hz=gpio_config.spi_speed_hz,
                        dc_chip=gpio_config.dc.chip,
                        dc_line=gpio_config.dc.line,
                        cs_chip=(
                            gpio_config.cs.chip
                            if gpio_config.cs is not None
                            else gpio_config.dc.chip
                        ),
                        cs_line=(
                            gpio_config.cs.line
                            if gpio_config.cs is not None
                            else gpio_config.dc.line
                        ),
                        backlight_chip=gpio_config.backlight.chip,
                        backlight_line=gpio_config.backlight.line,
                    )
                    self.device.init()
                    self.device.set_backlight(True)
                    logger.info("Pimoroni LVGL adapter initialized (320x240 landscape)")
                except Exception as exc:
                    logger.error("Failed to initialize Pimoroni LVGL hardware path: {}", exc)
                    self.simulate = True
                    self.SIMULATED_HARDWARE = "pimoroni"
                    if self.device is not None:
                        try:
                            self.device.cleanup()
                        except Exception:
                            pass
                    self.device = None
        else:
            logger.info("Pimoroni display adapter running in LVGL simulation mode")

        from yoyopod_cli.pi.support.lvgl_binding import LvglDisplayBackend

        self.ui_backend = LvglDisplayBackend(self, buffer_lines=self.lvgl_buffer_lines)

    def _raise_immediate_draw_error(self, operation: str) -> None:
        raise RuntimeError(
            f"PimoroniDisplayAdapter.{operation}() was retired with the LVGL-only cut; "
            "render via LVGL scenes instead"
        )

    def _sync_simulation_preview(self) -> None:
        if self.web_server is None:
            return
        try:
            self.web_server.send_display_update(self._framebuffer.to_png_base64())
        except Exception as exc:
            logger.warning("Failed to send Pimoroni simulation preview update: {}", exc)

    def _record_partial_flush_timing(
        self,
        *,
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
            logger.info("Pimoroni framebuffer screenshot saved to {}", path)
            return True
        except Exception as exc:
            logger.error("Failed to save Pimoroni framebuffer screenshot to {}: {}", path, exc)
            return False

    def save_screenshot_readback(self, path: str) -> bool:
        if self.ui_backend is None or not getattr(self.ui_backend, "initialized", False):
            logger.warning("LVGL backend not available for Pimoroni readback screenshot")
            return False

        binding = getattr(self.ui_backend, "binding", None)
        if binding is None:
            logger.warning("LVGL binding not available for Pimoroni readback screenshot")
            return False

        try:
            pixel_data = binding.snapshot(self.WIDTH, self.HEIGHT)
            if pixel_data is None:
                logger.error("LVGL snapshot returned no data")
                return False
            Path(path).write_bytes(rgb565_bytes_to_png(self.WIDTH, self.HEIGHT, pixel_data))
            logger.info("Pimoroni LVGL readback screenshot saved to {}", path)
            return True
        except Exception as exc:
            logger.error("Failed to save Pimoroni LVGL readback screenshot: {}", exc)
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
                self.device.set_backlight(brightness > 0.0)
            except Exception as exc:
                logger.error("Failed to set Pimoroni backlight: {}", exc)

    def get_text_size(self, text: str, font_size: int = 16) -> tuple[int, int]:
        return (int(len(text) * max(6, font_size * 0.6)), font_size)

    def cleanup(self) -> None:
        if self.ui_backend is not None:
            try:
                self.ui_backend.cleanup()
            except Exception as exc:
                logger.error("Error during Pimoroni LVGL backend cleanup: {}", exc)
        if self.device is not None:
            try:
                self.device.set_backlight(False)
                self.device.cleanup()
            except Exception as exc:
                logger.error("Error during Pimoroni cleanup: {}", exc)
