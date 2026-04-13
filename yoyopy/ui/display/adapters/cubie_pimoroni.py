"""
Pimoroni Display HAT Mini adapter for non-Pi boards (Cubie A7Z, etc.).

Uses the ST7789SpiDriver for display output and gpiod for RGB LED control.
Implements the same DisplayHAL interface as the Pi-native PimoroniDisplayAdapter
but without any dependency on displayhatmini or RPi.GPIO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from yoyopy.config.models import GpioPin, PimoroniGpioConfig
from yoyopy.ui.display.hal import DisplayHAL

from yoyopy.ui.gpiod_compat import HAS_GPIOD, open_chip, request_output


class CubiePimoroniAdapter(DisplayHAL):
    """DisplayHAL adapter for the Pimoroni Display HAT Mini on non-Pi boards."""

    DISPLAY_TYPE = "pimoroni"
    WIDTH = 320
    HEIGHT = 240
    ORIENTATION = "landscape"
    STATUS_BAR_HEIGHT = 20

    def __init__(
        self,
        simulate: bool = False,
        gpio_config: PimoroniGpioConfig | None = None,
    ) -> None:
        self.simulate = simulate
        self.buffer: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self._driver = None
        self._led_lines: dict[str, object] = {}
        self._led_chips: list[object] = []

        self._create_buffer()

        if not self.simulate:
            cfg = gpio_config or PimoroniGpioConfig()
            try:
                from yoyopy.ui.display.adapters.st7789_spi import ST7789SpiDriver

                self._driver = ST7789SpiDriver(
                    spi_bus=cfg.spi_bus,
                    spi_device=cfg.spi_device,
                    spi_speed_hz=cfg.spi_speed_hz,
                    dc_chip=cfg.dc.chip if cfg.dc else "gpiochip0",
                    dc_line=cfg.dc.line if cfg.dc else 109,
                    cs_chip=cfg.cs.chip if cfg.cs else "gpiochip0",
                    cs_line=cfg.cs.line if cfg.cs else 110,
                    backlight_chip=cfg.backlight.chip if cfg.backlight else "gpiochip1",
                    backlight_line=cfg.backlight.line if cfg.backlight else 35,
                )
                self._driver.init()
                self._driver.set_backlight(True)
                self._init_led(cfg)
                logger.info("Cubie Pimoroni adapter initialized (320x240 landscape)")
            except Exception as e:
                logger.error("Failed to initialize Cubie Pimoroni display: {}", e)
                logger.info("Falling back to simulation mode")
                self.simulate = True
                self._driver = None
        else:
            logger.info("Cubie Pimoroni adapter running in simulation mode")

    def _init_led(self, cfg: PimoroniGpioConfig) -> None:
        """Initialize RGB LED GPIO lines."""
        if not HAS_GPIOD:
            return
        for name, pin in [("r", cfg.led_r), ("g", cfg.led_g), ("b", cfg.led_b)]:
            if pin is None:
                continue
            try:
                chip = open_chip(pin.chip)
                self._led_chips.append(chip)
                line = request_output(chip, pin.line, f"pimoroni-led-{name}", default_val=0)
                self._led_lines[name] = line
            except Exception as e:
                logger.warning("Failed to acquire LED {} GPIO: {}", name, e)

    def set_led(self, r: float, g: float, b: float) -> None:
        """Set RGB LED state (on/off per channel, 0.0 = off, >0.0 = on)."""
        for name, value in [("r", r), ("g", g), ("b", b)]:
            line = self._led_lines.get(name)
            if line is not None:
                try:
                    line.set_value(1 if value > 0 else 0)
                except Exception as e:
                    logger.warning("Failed to set LED {}: {}", name, e)

    def _create_buffer(self) -> None:
        """Create a new PIL drawing buffer."""
        self.buffer = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.COLOR_BLACK)
        self.draw = ImageDraw.Draw(self.buffer)

    def _pil_to_rgb565(self, image: Image.Image) -> bytes:
        """Convert PIL RGB image to RGB565 bytes for SPI."""
        raw = image.tobytes()
        width, height = image.size
        rgb565 = bytearray(width * height * 2)
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            j = (i // 3) * 2
            rgb565[j] = (val >> 8) & 0xFF
            rgb565[j + 1] = val & 0xFF
        return bytes(rgb565)

    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        if color is None:
            color = self.COLOR_BLACK
        self.draw.rectangle([(0, 0), (self.WIDTH, self.HEIGHT)], fill=color)

    def text(
        self,
        text: str,
        x: int,
        y: int,
        color: Optional[Tuple[int, int, int]] = None,
        font_size: int = 16,
        font_path: Optional[Path] = None,
    ) -> None:
        if color is None:
            color = self.COLOR_WHITE
        try:
            if font_path and font_path.exists():
                font = ImageFont.truetype(str(font_path), font_size)
            else:
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        font_size,
                    )
                except Exception:
                    font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
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
        try:
            img = Image.open(image_path)
            if width and height:
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            self.buffer.paste(img, (x, y))
        except Exception as e:
            logger.error("Failed to load image {}: {}", image_path, e)

    def status_bar(
        self,
        time_str: str = "--:--",
        battery_percent: int = 100,
        signal_strength: int = 4,
        charging: bool = False,
        external_power: bool = False,
        power_available: bool = True,
    ) -> None:
        self.rectangle(0, 0, self.WIDTH, self.STATUS_BAR_HEIGHT, fill=self.COLOR_DARK_GRAY)
        time_x = (self.WIDTH - len(time_str) * 8) // 2
        self.text(time_str, time_x, 2, color=self.COLOR_WHITE, font_size=14)

        battery_x = self.WIDTH - 50
        battery_y = 4
        bw = 40
        bh = 12
        self.rectangle(battery_x, battery_y, battery_x + bw, battery_y + bh,
                        outline=self.COLOR_WHITE, width=1)
        self.rectangle(battery_x + bw, battery_y + 3,
                        battery_x + bw + 3, battery_y + bh - 3, fill=self.COLOR_WHITE)
        fill_width = int((bw - 4) * (battery_percent / 100))
        if fill_width > 0:
            battery_color = self.COLOR_GREEN if battery_percent > 20 else self.COLOR_RED
            self.rectangle(battery_x + 2, battery_y + 2,
                            battery_x + 2 + fill_width, battery_y + bh - 2,
                            fill=battery_color)

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

        signal_x = 5
        signal_y = 8
        bar_w = 3
        bar_spacing = 2
        for i in range(4):
            bar_h = 4 + (i * 2)
            bar_color = self.COLOR_WHITE if i < signal_strength else self.COLOR_DARK_GRAY
            self.rectangle(
                signal_x + (i * (bar_w + bar_spacing)),
                signal_y + (12 - bar_h),
                signal_x + (i * (bar_w + bar_spacing)) + bar_w,
                signal_y + 12,
                fill=bar_color,
            )

    def update(self) -> None:
        if self.buffer is None:
            return
        if not self.simulate and self._driver:
            try:
                pixel_data = self._pil_to_rgb565(self.buffer)
                self._driver.draw_image(0, 0, self.WIDTH, self.HEIGHT, pixel_data)
            except Exception as e:
                logger.error("Failed to update Cubie Pimoroni display: {}", e)

    def draw_rgb565_region(
        self, x: int, y: int, width: int, height: int, pixel_data: bytes
    ) -> None:
        """Receive RGB565 region from LVGL flush and push to ST7789 via SPI."""
        if not self.simulate and self._driver:
            try:
                self._driver.draw_image(x, y, width, height, pixel_data)
            except Exception as e:
                logger.error("Failed to draw LVGL region: {}", e)

    def get_flush_target(self) -> "CubiePimoroniAdapter | None":
        """Return self as LVGL flush target when hardware is available."""
        if not self.simulate and self._driver:
            return self
        return None

    def set_backlight(self, brightness: float) -> None:
        if not self.simulate and self._driver:
            self._driver.set_backlight(brightness > 0)

    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                font_size,
            )
        except Exception:
            font = ImageFont.load_default()
        bbox = self.draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    def cleanup(self) -> None:
        for line in self._led_lines.values():
            try:
                line.set_value(0)
                line.release()
            except Exception:
                pass
        for chip in self._led_chips:
            try:
                chip.close()
            except Exception:
                pass
        self._led_lines.clear()
        self._led_chips.clear()

        if self._driver:
            self._driver.cleanup()
            self._driver = None

        logger.info("Cubie Pimoroni adapter cleaned up")
