"""
PiSugar Whisplay HAT adapter for YoyoPod.

This adapter implements the DisplayHAL interface for the PiSugar Whisplay HAT,
featuring a 240×280 pixel portrait display with ST7789P3 driver.

Hardware Specs:
- Display: 240×280 pixels (portrait orientation)
- Driver: ST7789P3 (SPI interface)
- Button: 1 mouse click button (GPIO 11, BOARD mode)
- LED: RGB LED
- Audio: WM8960 codec with dual MEMS microphones
- Library: WhisPlay (custom driver)

Author: YoyoPod Team
Date: 2025-11-30
"""

from importlib import import_module
from pathlib import Path
import time
from types import ModuleType
from typing import Optional, Tuple

from loguru import logger
from PIL import Image, ImageChops, ImageDraw, ImageFont

from yoyopod.ui.display.adapters.whisplay_paths import ensure_whisplay_driver_on_path
from yoyopod.ui.display.hal import DisplayHAL

DRIVER_PATH = ensure_whisplay_driver_on_path()
DEFAULT_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_RGB565_HIGH_RED_LUT = tuple(value & 0xF8 for value in range(256))
_RGB565_HIGH_GREEN_LUT = tuple(value >> 5 for value in range(256))
_RGB565_LOW_GREEN_LUT = tuple((value & 0x1C) << 3 for value in range(256))
_RGB565_LOW_BLUE_LUT = tuple(value >> 3 for value in range(256))


def _normalize_gpiochip_path(candidate: object) -> object:
    """Normalize bare ``gpiochipN`` names to ``/dev/gpiochipN`` when needed."""

    if isinstance(candidate, str) and candidate.startswith("gpiochip"):
        return f"/dev/{candidate}"
    return candidate


def _patch_vendor_gpiod_compat(whisplay_module: ModuleType) -> None:
    """Normalize the WhisPlay driver's expected gpiod API for Python 3.12 envs."""

    gpiod = getattr(whisplay_module, "gpiod", None)
    if gpiod is None or getattr(gpiod, "_yoyopod_whisplay_compat", False):
        return

    line_request = getattr(gpiod, "line_request", None)
    if line_request is not None:
        aliases = {
            "LINE_REQ_DIR_OUT": "DIRECTION_OUTPUT",
            "LINE_REQ_DIR_IN": "DIRECTION_INPUT",
            "LINE_REQ_FLAG_BIAS_DISABLE": "FLAG_BIAS_DISABLE",
        }
        for alias, source_name in aliases.items():
            if not hasattr(gpiod, alias) and hasattr(line_request, source_name):
                setattr(gpiod, alias, getattr(line_request, source_name))

    if hasattr(gpiod, "chip") and not hasattr(gpiod, "Chip"):

        class _CompatLine:
            def __init__(self, line: object) -> None:
                self._line = line

            def request(self, *args, **kwargs):
                if kwargs:
                    request_config = line_request()
                    request_config.consumer = kwargs.pop("consumer", "")
                    request_config.request_type = kwargs.pop("type")
                    request_config.flags = kwargs.pop("flags", 0)
                    default_val = kwargs.pop("default_val", 0)
                    if kwargs:
                        unexpected = ", ".join(sorted(kwargs))
                        raise TypeError(f"Unexpected line.request kwargs: {unexpected}")
                    return self._line.request(request_config, default_val)
                return self._line.request(*args)

            def __getattr__(self, name: str) -> object:
                return getattr(self._line, name)

        class _CompatChip:
            def __init__(self, chip: object) -> None:
                self._chip = chip

            def get_line(self, offset: int) -> _CompatLine:
                return _CompatLine(self._chip.get_line(offset))

            def __getattr__(self, name: str) -> object:
                return getattr(self._chip, name)

        def _compat_chip(name: object):
            return _CompatChip(gpiod.chip(_normalize_gpiochip_path(name)))

        gpiod.Chip = _compat_chip
    elif hasattr(gpiod, "Chip"):
        original_chip = gpiod.Chip

        def _compat_chip(name: object):
            try:
                return original_chip(name)
            except FileNotFoundError:
                normalized = _normalize_gpiochip_path(name)
                if normalized == name:
                    raise
                return original_chip(normalized)

        gpiod.Chip = _compat_chip

    gpiod._yoyopod_whisplay_compat = True


try:
    _whisplay_driver = import_module("WhisPlay")
    _patch_vendor_gpiod_compat(_whisplay_driver)
    WhisPlayBoard = _whisplay_driver.WhisPlayBoard

    HAS_HARDWARE = True
except ImportError:
    HAS_HARDWARE = False
    if DRIVER_PATH:
        logger.warning(
            f"WhisPlay library not importable from {DRIVER_PATH.parent} - adapter will run in simulation mode"
        )
    else:
        logger.warning("WhisPlay library not available - adapter will run in simulation mode")


class WhisplayDisplayAdapter(DisplayHAL):
    """
    Hardware adapter for PiSugar Whisplay HAT.

    This adapter wraps the WhisPlay driver and implements the standard
    DisplayHAL interface, enabling hardware-independent code in the rest
    of the application.

    The Whisplay HAT features a 240×280 pixel portrait display, making it
    ideal for vertical layouts and content stacking.

    Technical Notes:
    - Uses RGB565 color format (converted from RGB888)
    - Display updates require full-screen buffer transfer
    - Backlight control: 0-100 scale (converted from 0.0-1.0)
    """

    # Display configuration
    DISPLAY_TYPE = "whisplay"
    WIDTH = 240
    HEIGHT = 280
    ORIENTATION = "portrait"
    STATUS_BAR_HEIGHT = 25  # Slightly taller for portrait mode
    _SLOW_FULL_FRAME_UPDATE_THRESHOLD_SECONDS = 0.03
    _SLOW_REGION_FLUSH_THRESHOLD_SECONDS = 0.008
    _PARTIAL_FLUSH_TIMING_LOG_INTERVAL = 60

    def __init__(
        self,
        simulate: bool = False,
        renderer: str = "pil",
        lvgl_buffer_lines: int = 40,
    ) -> None:
        """
        Initialize the Whisplay HAT display.

        Args:
            simulate: If True, run in simulation mode without hardware
        """
        self.simulate = simulate or not HAS_HARDWARE
        self.buffer: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self.device = None
        self.renderer = renderer.lower().strip() or "pil"
        self.lvgl_buffer_lines = max(1, int(lvgl_buffer_lines))
        self.ui_backend = None
        self._force_shadow_buffer_sync = False
        self._font_cache: dict[tuple[str, int], object] = {}
        self._timing_metrics: dict[str, float | int] = {
            "full_frame_updates": 0,
            "last_full_frame_convert_ms": 0.0,
            "last_full_frame_device_ms": 0.0,
            "last_full_frame_total_ms": 0.0,
            "max_full_frame_total_ms": 0.0,
            "partial_flushes": 0,
            "partial_flush_shadow_syncs": 0,
            "last_partial_flush_device_ms": 0.0,
            "last_partial_flush_shadow_ms": 0.0,
            "last_partial_flush_total_ms": 0.0,
            "max_partial_flush_total_ms": 0.0,
            "partial_flush_total_ms": 0.0,
        }

        # Create PIL drawing buffer
        self._create_buffer()

        if not self.simulate:
            try:
                # Initialize WhisPlay board
                # Note: Button event detection is disabled in driver
                self.device = WhisPlayBoard()
                self.device.set_backlight(100)  # Full brightness (0-100 scale)
                self.device.set_rgb(0, 100, 200)  # Blue LED indicator
                logger.info("Whisplay HAT initialized (240×280 portrait)")
            except Exception as e:
                logger.error(f"Failed to initialize Whisplay display hardware: {e}")
                logger.info("Falling back to simulation mode")
                self.simulate = True
                self.device = None
        else:
            logger.info("Whisplay display adapter running in local render-only simulation mode")

        if self.renderer == "lvgl":
            try:
                from yoyopod.ui.lvgl_binding import LvglDisplayBackend

                self.ui_backend = LvglDisplayBackend(
                    self,
                    buffer_lines=self.lvgl_buffer_lines,
                )
                if not self.ui_backend.available:
                    logger.warning(
                        "Whisplay LVGL renderer requested but native shim is unavailable"
                    )
            except Exception as e:
                logger.warning(f"Failed to prepare LVGL backend: {e}")
                self.ui_backend = None
                self.renderer = "pil"

    @property
    def shadow_buffer_sync_enabled(self) -> bool:
        """Return True when screenshots should rely on the PIL shadow buffer.

        This must follow the adapter's effective runtime mode instead of the
        initial constructor arguments, because hardware/LVGL setup can fall
        back to simulation or PIL later in __init__.
        """

        if self.simulate or self.renderer != "lvgl":
            return True
        if self.ui_backend is None:
            return True
        if self._force_shadow_buffer_sync:
            return True
        return not bool(getattr(self.ui_backend, "available", False))

    def _create_buffer(self) -> None:
        """Create a new PIL drawing buffer."""
        self.buffer = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.COLOR_BLACK)
        self.draw = ImageDraw.Draw(self.buffer)

    def _load_font(
        self,
        font_size: int,
        font_path: Optional[Path] = None,
    ) -> object:
        """Load and cache the requested font once per path/size pair."""

        resolved_path: Path | None = None
        if font_path is not None and font_path.exists():
            resolved_path = font_path
        elif DEFAULT_FONT_PATH.exists():
            resolved_path = DEFAULT_FONT_PATH

        cache_key = (
            str(resolved_path.resolve()) if resolved_path is not None else "__pil_default__",
            font_size,
        )
        cached_font = self._font_cache.get(cache_key)
        if cached_font is not None:
            return cached_font

        try:
            if resolved_path is not None:
                font = ImageFont.truetype(str(resolved_path), font_size)
            else:
                font = ImageFont.load_default()
        except Exception as e:
            logger.warning("Failed to load font {} at {} px: {}", resolved_path, font_size, e)
            cache_key = ("__pil_default__", font_size)
            cached_font = self._font_cache.get(cache_key)
            if cached_font is not None:
                return cached_font
            font = ImageFont.load_default()

        self._font_cache[cache_key] = font
        return font

    @staticmethod
    def _rgb565_to_image(width: int, height: int, pixel_data: bytes) -> Image.Image:
        """Decode big-endian RGB565 bytes into a PIL image."""

        swapped = bytearray(len(pixel_data))
        swapped[0::2] = pixel_data[1::2]
        swapped[1::2] = pixel_data[0::2]
        return Image.frombytes("RGB", (width, height), bytes(swapped), "raw", "BGR;16")

    def _record_partial_flush_timing(
        self,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        device_seconds: float,
        shadow_seconds: float,
        total_seconds: float,
        shadow_synced: bool,
    ) -> None:
        """Record lightweight timing visibility for LVGL partial flushes."""

        metrics = self._timing_metrics
        metrics["partial_flushes"] = int(metrics["partial_flushes"]) + 1
        if shadow_synced:
            metrics["partial_flush_shadow_syncs"] = int(metrics["partial_flush_shadow_syncs"]) + 1
        metrics["last_partial_flush_device_ms"] = device_seconds * 1000.0
        metrics["last_partial_flush_shadow_ms"] = shadow_seconds * 1000.0
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
                "Slow Whisplay RGB565 flush: area={}x{} at {},{} total_ms={:.1f} device_ms={:.1f} shadow_ms={:.1f} shadow_sync={}",
                width,
                height,
                x,
                y,
                total_seconds * 1000.0,
                device_seconds * 1000.0,
                shadow_seconds * 1000.0,
                shadow_synced,
            )
            return

        flush_count = int(metrics["partial_flushes"])
        if flush_count % self._PARTIAL_FLUSH_TIMING_LOG_INTERVAL == 0:
            average_ms = float(metrics["partial_flush_total_ms"]) / max(1, flush_count)
            logger.debug(
                "Whisplay RGB565 flush timing: flushes={} avg_ms={:.1f} max_ms={:.1f} shadow_syncs={}",
                flush_count,
                average_ms,
                float(metrics["max_partial_flush_total_ms"]),
                int(metrics["partial_flush_shadow_syncs"]),
            )

    def _record_full_frame_timing(
        self,
        *,
        convert_seconds: float,
        device_seconds: float,
        total_seconds: float,
    ) -> None:
        """Record timing visibility for the PIL full-frame update path."""

        metrics = self._timing_metrics
        metrics["full_frame_updates"] = int(metrics["full_frame_updates"]) + 1
        metrics["last_full_frame_convert_ms"] = convert_seconds * 1000.0
        metrics["last_full_frame_device_ms"] = device_seconds * 1000.0
        metrics["last_full_frame_total_ms"] = total_seconds * 1000.0
        metrics["max_full_frame_total_ms"] = max(
            float(metrics["max_full_frame_total_ms"]),
            total_seconds * 1000.0,
        )

        if total_seconds >= self._SLOW_FULL_FRAME_UPDATE_THRESHOLD_SECONDS:
            logger.warning(
                "Slow Whisplay full-frame update: convert_ms={:.1f} device_ms={:.1f} total_ms={:.1f}",
                convert_seconds * 1000.0,
                device_seconds * 1000.0,
                total_seconds * 1000.0,
            )
            return

        logger.debug(
            "Whisplay full-frame update timing: convert_ms={:.1f} device_ms={:.1f} total_ms={:.1f}",
            convert_seconds * 1000.0,
            device_seconds * 1000.0,
            total_seconds * 1000.0,
        )

    def timing_snapshot(self) -> dict[str, float | int]:
        """Return the most recent Whisplay render/update timing metrics."""

        metrics = dict(self._timing_metrics)
        flush_count = int(metrics["partial_flushes"])
        metrics["avg_partial_flush_ms"] = (
            float(metrics["partial_flush_total_ms"]) / max(1, flush_count) if flush_count else 0.0
        )
        return metrics

    def _convert_to_rgb565(self) -> bytes:
        """
        Convert PIL RGB888 buffer to RGB565 byte array for Whisplay display.

        RGB565 format:
        - 5 bits for red
        - 6 bits for green
        - 5 bits for blue
        - Total: 16 bits (2 bytes) per pixel

        Returns:
            Byte array in RGB565 format (big-endian)
        """
        if self.buffer is None:
            return b""

        red, green, blue = self.buffer.split()
        high = ImageChops.add(
            red.point(_RGB565_HIGH_RED_LUT),
            green.point(_RGB565_HIGH_GREEN_LUT),
        )
        low = ImageChops.add(
            green.point(_RGB565_LOW_GREEN_LUT),
            blue.point(_RGB565_LOW_BLUE_LUT),
        )

        # ``LA`` stores two 8-bit channels interleaved, which matches the
        # adapter's big-endian RGB565 byte contract without a Python pixel loop.
        return Image.merge("LA", (high, low)).tobytes()

    def _paste_rgb565_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        """Paste an RGB565 region into the PIL buffer for simulation/debugging."""

        if self.buffer is None:
            return

        region = self._rgb565_to_image(width, height, pixel_data)
        self.buffer.paste(region, (x, y))

    def draw_rgb565_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        """Write an RGB565 region to hardware and optionally the PIL shadow buffer."""

        started_at = time.monotonic()
        device_started_at = started_at
        if not self.simulate and self.device:
            self.device.draw_image(x, y, width, height, pixel_data)
        device_seconds = max(0.0, time.monotonic() - device_started_at)

        # Keep the PIL buffer in sync only when it is the active renderer or simulation target.
        # Doing this for every LVGL partial flush on hardware is too expensive on the Pi.
        shadow_started_at = time.monotonic()
        shadow_synced = self.shadow_buffer_sync_enabled
        if shadow_synced:
            self._paste_rgb565_region(x, y, width, height, pixel_data)
        shadow_seconds = max(0.0, time.monotonic() - shadow_started_at) if shadow_synced else 0.0
        total_seconds = max(0.0, time.monotonic() - started_at)
        self._record_partial_flush_timing(
            x=x,
            y=y,
            width=width,
            height=height,
            device_seconds=device_seconds,
            shadow_seconds=shadow_seconds,
            total_seconds=total_seconds,
            shadow_synced=shadow_synced,
        )

    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        """Clear the display with specified color."""
        if color is None:
            color = self.COLOR_BLACK

        self.draw.rectangle([(0, 0), (self.WIDTH, self.HEIGHT)], fill=color)
        logger.debug(f"Whisplay display cleared with color {color}")

    def text(
        self,
        text: str,
        x: int,
        y: int,
        color: Optional[Tuple[int, int, int]] = None,
        font_size: int = 16,
        font_path: Optional[Path] = None,
    ) -> None:
        """Draw text at specified position."""
        if color is None:
            color = self.COLOR_WHITE

        font = self._load_font(font_size, font_path)
        self.draw.text((x, y), text, fill=color, font=font)

    def rectangle(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        fill: Optional[Tuple[int, int, int]] = None,
        outline: Optional[Tuple[int, int, int]] = None,
        width: int = 1,
    ) -> None:
        """Draw a rectangle."""
        self.draw.rectangle([(x1, y1), (x2, y2)], fill=fill, outline=outline, width=width)

    def circle(
        self,
        x: int,
        y: int,
        radius: int,
        fill: Optional[Tuple[int, int, int]] = None,
        outline: Optional[Tuple[int, int, int]] = None,
        width: int = 1,
    ) -> None:
        """Draw a circle."""
        bbox = [x - radius, y - radius, x + radius, y + radius]
        self.draw.ellipse(bbox, fill=fill, outline=outline, width=width)

    def line(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: Optional[Tuple[int, int, int]] = None,
        width: int = 1,
    ) -> None:
        """Draw a line."""
        if color is None:
            color = self.COLOR_WHITE

        self.draw.line([(x1, y1), (x2, y2)], fill=color, width=width)

    def image(
        self,
        image_path: Path,
        x: int,
        y: int,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Draw an image from file."""
        try:
            img = Image.open(image_path)

            if width and height:
                img = img.resize((width, height), Image.Resampling.LANCZOS)

            self.buffer.paste(img, (x, y))
        except Exception as e:
            logger.error(f"Failed to load image {image_path}: {e}")

    def status_bar(
        self,
        time_str: str = "--:--",
        battery_percent: int = 100,
        signal_strength: int = 4,
        charging: bool = False,
        external_power: bool = False,
        power_available: bool = True,
    ) -> None:
        """
        Draw status bar at top of screen.

        Portrait layout uses slightly taller status bar (25px vs 20px)
        to accommodate the narrower width.
        """
        # Draw background
        self.rectangle(0, 0, self.WIDTH, self.STATUS_BAR_HEIGHT, fill=self.COLOR_DARK_GRAY)

        # Draw time (centered) - adjusted for narrower width
        time_x = (self.WIDTH - len(time_str) * 7) // 2
        self.text(time_str, time_x, 4, color=self.COLOR_WHITE, font_size=14)

        # Draw battery indicator (right side) - scaled for portrait
        battery_x = self.WIDTH - 45
        battery_y = 6
        battery_width = 35
        battery_height = 12

        # Battery outline
        self.rectangle(
            battery_x,
            battery_y,
            battery_x + battery_width,
            battery_y + battery_height,
            outline=self.COLOR_WHITE,
            width=1,
        )

        # Battery tip
        self.rectangle(
            battery_x + battery_width,
            battery_y + 3,
            battery_x + battery_width + 3,
            battery_y + battery_height - 3,
            fill=self.COLOR_WHITE,
        )

        # Battery fill
        fill_width = int((battery_width - 4) * (battery_percent / 100))
        if fill_width > 0:
            battery_color = self.COLOR_GREEN if battery_percent > 20 else self.COLOR_RED
            self.rectangle(
                battery_x + 2,
                battery_y + 2,
                battery_x + 2 + fill_width,
                battery_y + battery_height - 2,
                fill=battery_color,
            )

        indicator = ""
        if not power_available:
            indicator = "?"
        elif charging:
            indicator = "C"
        elif external_power:
            indicator = "P"

        if indicator:
            self.text(
                indicator,
                battery_x - 14,
                battery_y - 1,
                color=self.COLOR_YELLOW if indicator == "?" else self.COLOR_WHITE,
                font_size=12,
            )

        # Draw signal strength (left side)
        signal_x = 5
        signal_y = 10
        bar_width = 3
        bar_spacing = 2

        for i in range(4):
            bar_height = 4 + (i * 2)
            bar_color = self.COLOR_WHITE if i < signal_strength else self.COLOR_DARK_GRAY

            self.rectangle(
                signal_x + (i * (bar_width + bar_spacing)),
                signal_y + (12 - bar_height),
                signal_x + (i * (bar_width + bar_spacing)) + bar_width,
                signal_y + 12,
                fill=bar_color,
            )

    def update(self) -> None:
        """
        Flush buffer to physical display.

        Converts RGB888 PIL buffer to RGB565 format and sends to Whisplay display.
        """
        if self.buffer is None:
            logger.warning("No buffer to display")
            return

        if not self.simulate and self.device:
            try:
                started_at = time.monotonic()
                convert_started_at = started_at
                pixel_data = self._convert_to_rgb565()
                convert_seconds = max(0.0, time.monotonic() - convert_started_at)

                device_started_at = time.monotonic()
                self.device.draw_image(0, 0, self.WIDTH, self.HEIGHT, pixel_data)
                device_seconds = max(0.0, time.monotonic() - device_started_at)
                total_seconds = max(0.0, time.monotonic() - started_at)
                self._record_full_frame_timing(
                    convert_seconds=convert_seconds,
                    device_seconds=device_seconds,
                    total_seconds=total_seconds,
                )
            except Exception as e:
                logger.error(f"Failed to update Whisplay display: {e}")
        else:
            logger.debug("Whisplay display update (simulated)")

    def save_screenshot(self, path: str) -> bool:
        """Save the current PIL shadow buffer as a PNG screenshot.

        The shadow buffer is kept in sync with every LVGL flush callback,
        so this captures what the app most recently sent to the display.

        Args:
            path: File path to write the PNG image to.

        Returns:
            True if the screenshot was saved, False if no buffer exists.
        """
        if not self.shadow_buffer_sync_enabled:
            if self.ui_backend is None or not getattr(self.ui_backend, "initialized", False):
                logger.info(
                    "Shadow-buffer screenshots are disabled for hardware LVGL; using LVGL readback instead"
                )
                return self.save_screenshot_readback(path)

            logger.info(
                "Shadow-buffer screenshots are disabled for hardware LVGL; forcing one redraw into the PIL buffer"
            )
            self._force_shadow_buffer_sync = True
            try:
                self.ui_backend.force_refresh()
            except Exception as e:
                logger.error("Failed to refresh the LVGL scene for shadow screenshot: {}", e)
                return False
            finally:
                self._force_shadow_buffer_sync = False

        if self.buffer is None:
            logger.warning("No buffer available for screenshot")
            return False
        try:
            self.buffer.save(path, "PNG")
            logger.info("Shadow buffer screenshot saved to {}", path)
            return True
        except Exception as e:
            logger.error("Failed to save screenshot to {}: {}", path, e)
            return False

    def save_screenshot_readback(self, path: str) -> bool:
        """Save a screenshot by reading back from LVGL's internal object tree.

        Uses lv_snapshot_take() via the C shim to capture what LVGL has
        actually rendered, regardless of the shadow buffer state.

        Args:
            path: File path to write the PNG image to.

        Returns:
            True if the screenshot was saved, False on failure.
        """
        if self.ui_backend is None or not self.ui_backend.initialized:
            logger.warning("LVGL backend not available for readback screenshot")
            return False

        binding = self.ui_backend.binding
        if binding is None:
            logger.warning("LVGL binding not available for readback screenshot")
            return False

        try:
            pixel_data = binding.snapshot(self.WIDTH, self.HEIGHT)
            if pixel_data is None:
                logger.error("LVGL snapshot returned no data")
                return False

            img = self._rgb565_to_image(self.WIDTH, self.HEIGHT, pixel_data)
            img.save(path, "PNG")
            logger.info("LVGL readback screenshot saved to {}", path)
            return True
        except Exception as e:
            logger.error("Failed to save LVGL readback screenshot: {}", e)
            return False

    def get_backend_kind(self) -> str:
        """Return the active UI rendering backend."""

        if (
            self.ui_backend is not None
            and self.renderer == "lvgl"
            and getattr(self.ui_backend, "initialized", False)
        ):
            return "lvgl"
        return "pil"

    def get_ui_backend(self):
        """Return the optional Whisplay LVGL backend."""

        return self.ui_backend

    def reset_ui_backend(self) -> None:
        """Reset any active LVGL scene before handing off to another renderer."""

        if self.ui_backend is not None:
            self.ui_backend.reset()

    def set_backlight(self, brightness: float) -> None:
        """
        Set backlight brightness (0.0 to 1.0).

        Whisplay uses 0-100 scale internally, so we convert.
        """
        if not self.simulate and self.device:
            try:
                # Convert 0.0-1.0 to 0-100
                whisplay_brightness = int(brightness * 100)
                self.device.set_backlight(whisplay_brightness)
                logger.debug(f"Whisplay backlight set to {brightness} ({whisplay_brightness}%)")
            except Exception as e:
                logger.error(f"Failed to set Whisplay backlight: {e}")

    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        """Calculate rendered text dimensions."""
        font = self._load_font(font_size)

        bbox = self.draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    def cleanup(self) -> None:
        """Cleanup Whisplay display resources."""
        if self.ui_backend is not None:
            try:
                self.ui_backend.cleanup()
            except Exception as e:
                logger.error(f"Error during LVGL backend cleanup: {e}")

        if self.device:
            try:
                self.device.set_backlight(0)  # Turn off backlight
                self.device.set_rgb(0, 0, 0)  # Turn off LED
                self.device.cleanup()  # Call driver cleanup
                logger.info("Whisplay display cleaned up")
            except Exception as e:
                logger.error(f"Error during Whisplay cleanup: {e}")
