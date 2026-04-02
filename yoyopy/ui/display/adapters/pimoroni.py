"""
Pimoroni Display HAT Mini adapter for YoyoPod.

This adapter implements the DisplayHAL interface for the Pimoroni Display HAT Mini,
featuring a 320×240 pixel landscape display with ST7789 driver.

Hardware Specs:
- Display: 320×240 pixels (landscape orientation)
- Driver: ST7789 (SPI interface)
- Buttons: 4 tactile buttons (A, B, X, Y)
- LED: RGB LED
- Library: displayhatmini

Author: YoyoPod Team
Date: 2025-11-30
"""

from yoyopy.ui.display.display_hal import DisplayHAL
from typing import Optional, Tuple
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from loguru import logger

try:
    from displayhatmini import DisplayHATMini
    HAS_HARDWARE = True
except Exception as e:
    HAS_HARDWARE = False
    logger.warning(
        f"DisplayHATMini library unavailable or unusable ({e}) - "
        "adapter will run in simulation mode"
    )


class PimoroniDisplayAdapter(DisplayHAL):
    """
    Hardware adapter for Pimoroni Display HAT Mini.

    This adapter wraps the DisplayHATMini library and implements the standard
    DisplayHAL interface, enabling hardware-independent code in the rest of
    the application.

    The Pimoroni HAT features a 320×240 pixel landscape display, making it
    suitable for side-by-side layouts and wider content.
    """

    # Display configuration
    WIDTH = 320
    HEIGHT = 240
    ORIENTATION = "landscape"
    STATUS_BAR_HEIGHT = 20

    def __init__(self, simulate: bool = False) -> None:
        """
        Initialize the Pimoroni Display HAT Mini.

        Args:
            simulate: If True, run in simulation mode without hardware
        """
        self.simulate = simulate or not HAS_HARDWARE
        self.buffer: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self.device = None

        # Create PIL drawing buffer
        self._create_buffer()

        if not self.simulate:
            try:
                # Initialize DisplayHATMini with buffer and backlight PWM
                self.device = DisplayHATMini(self.buffer, backlight_pwm=True)
                self.device.set_backlight(1.0)  # Full brightness
                self.device.set_led(0.1, 0.0, 0.5)  # Purple LED indicator
                logger.info("Pimoroni Display HAT Mini initialized (320×240 landscape)")
            except Exception as e:
                logger.error(f"Failed to initialize Pimoroni display hardware: {e}")
                logger.info("Falling back to simulation mode")
                self.simulate = True
                self.device = None
        else:
            logger.info("Pimoroni display adapter running in simulation mode")

    def _create_buffer(self) -> None:
        """Create a new PIL drawing buffer."""
        self.buffer = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.COLOR_BLACK)
        self.draw = ImageDraw.Draw(self.buffer)

    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        """Clear the display with specified color."""
        if color is None:
            color = self.COLOR_BLACK

        self.draw.rectangle([(0, 0), (self.WIDTH, self.HEIGHT)], fill=color)
        logger.debug(f"Pimoroni display cleared with color {color}")

    def text(
        self,
        text: str,
        x: int,
        y: int,
        color: Optional[Tuple[int, int, int]] = None,
        font_size: int = 16,
        font_path: Optional[Path] = None
    ) -> None:
        """Draw text at specified position."""
        if color is None:
            color = self.COLOR_WHITE

        try:
            if font_path and font_path.exists():
                font = ImageFont.truetype(str(font_path), font_size)
            else:
                # Try to use default system font
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        font_size
                    )
                except:
                    font = ImageFont.load_default()
        except Exception as e:
            logger.warning(f"Failed to load font: {e}, using default")
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
        width: int = 1
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
        width: int = 1
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
        width: int = 1
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
        height: Optional[int] = None
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
        signal_strength: int = 4
    ) -> None:
        """Draw status bar at top of screen."""
        # Draw background
        self.rectangle(
            0, 0,
            self.WIDTH, self.STATUS_BAR_HEIGHT,
            fill=self.COLOR_DARK_GRAY
        )

        # Draw time (centered)
        time_x = (self.WIDTH - len(time_str) * 8) // 2
        self.text(time_str, time_x, 2, color=self.COLOR_WHITE, font_size=14)

        # Draw battery indicator (right side)
        battery_x = self.WIDTH - 50
        battery_y = 4
        battery_width = 40
        battery_height = 12

        # Battery outline
        self.rectangle(
            battery_x, battery_y,
            battery_x + battery_width, battery_y + battery_height,
            outline=self.COLOR_WHITE,
            width=1
        )

        # Battery tip
        self.rectangle(
            battery_x + battery_width, battery_y + 3,
            battery_x + battery_width + 3, battery_y + battery_height - 3,
            fill=self.COLOR_WHITE
        )

        # Battery fill
        fill_width = int((battery_width - 4) * (battery_percent / 100))
        if fill_width > 0:
            battery_color = self.COLOR_GREEN if battery_percent > 20 else self.COLOR_RED
            self.rectangle(
                battery_x + 2, battery_y + 2,
                battery_x + 2 + fill_width, battery_y + battery_height - 2,
                fill=battery_color
            )

        # Draw signal strength (left side)
        signal_x = 5
        signal_y = 8
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
                fill=bar_color
            )

    def update(self) -> None:
        """Flush buffer to physical display."""
        if self.buffer is None:
            logger.warning("No buffer to display")
            return

        if not self.simulate and self.device:
            try:
                self.device.display()
                logger.debug("Pimoroni display updated")
            except Exception as e:
                logger.error(f"Failed to update Pimoroni display: {e}")
        else:
            logger.debug("Pimoroni display update (simulated)")

    def set_backlight(self, brightness: float) -> None:
        """Set backlight brightness (0.0 to 1.0)."""
        if not self.simulate and self.device:
            try:
                self.device.set_backlight(brightness)
                logger.debug(f"Pimoroni backlight set to {brightness}")
            except Exception as e:
                logger.error(f"Failed to set Pimoroni backlight: {e}")

    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        """Calculate rendered text dimensions."""
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                font_size
            )
        except:
            font = ImageFont.load_default()

        bbox = self.draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    def cleanup(self) -> None:
        """Cleanup Pimoroni display resources."""
        if self.device:
            try:
                self.device.set_backlight(0.0)  # Turn off backlight
                self.device.set_led(0, 0, 0)    # Turn off LED
                logger.info("Pimoroni display cleaned up")
            except Exception as e:
                logger.error(f"Error during Pimoroni cleanup: {e}")
