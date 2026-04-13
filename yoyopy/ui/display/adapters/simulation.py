"""
Simulation display adapter for YoyoPod.

This adapter implements the DisplayHAL interface for simulation mode,
rendering to a web-based canvas viewer instead of physical hardware.

Features:
- Pixel-perfect 240×280 display rendering
- Real-time WebSocket updates to browser
- Full PIL drawing capabilities
- No hardware dependencies

Author: YoyoPod Team
Date: 2025-11-30
"""

from yoyopy.ui.display.hal import DisplayHAL
from typing import Optional, Tuple
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from loguru import logger
import base64
import io


class SimulationDisplayAdapter(DisplayHAL):
    """
    Simulation display adapter for browser-based display.

    This adapter provides a pixel-perfect simulation of the Whisplay HAT
    display (240×280) rendered in a web browser using HTML5 Canvas.

    All drawing operations are performed on a PIL Image buffer, which is
    then converted to PNG and sent to the browser via WebSocket.

    Technical Notes:
    - Uses RGB888 color format (standard RGB)
    - Display updates are sent as base64-encoded PNG images
    - WebSocket connection managed by web server module
    """

    # Display configuration (match the Whisplay profile)
    DISPLAY_TYPE = "simulation"
    SIMULATED_HARDWARE = "whisplay"
    WIDTH = 240
    HEIGHT = 280
    ORIENTATION = "portrait"
    STATUS_BAR_HEIGHT = 25

    def __init__(self, simulate: bool = True) -> None:
        """
        Initialize the simulation display adapter.

        Args:
            simulate: Ignored (always True for simulation adapter)
        """
        self.simulate = True  # Always in simulation mode
        self.buffer: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self.web_server = None  # Will be set by web server module
        self._rgb565_framebuffer: Optional[bytearray] = None

        # Create PIL drawing buffer
        self._create_buffer()

        # Create RGB565 framebuffer for LVGL flush compositing
        self._rgb565_framebuffer = bytearray(self.WIDTH * self.HEIGHT * 2)

        logger.info("Simulation display adapter initialized (240x280 portrait, Whisplay profile)")
        logger.info("Display will be available at http://localhost:5000")

    def _create_buffer(self) -> None:
        """Create a new PIL drawing buffer."""
        self.buffer = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.COLOR_BLACK)
        self.draw = ImageDraw.Draw(self.buffer)

    def get_buffer_as_png_base64(self) -> str:
        """
        Convert current buffer to base64-encoded PNG.

        Returns:
            Base64-encoded PNG image string

        Example:
            >>> adapter = SimulationDisplayAdapter()
            >>> adapter.clear()
            >>> png_data = adapter.get_buffer_as_png_base64()
            >>> print(png_data[:20])
            'iVBORw0KGgoAAAANS...'
        """
        if self.buffer is None:
            self._create_buffer()

        # Convert PIL Image to PNG bytes
        buffered = io.BytesIO()
        self.buffer.save(buffered, format="PNG")
        png_bytes = buffered.getvalue()

        # Encode as base64
        b64_str = base64.b64encode(png_bytes).decode("utf-8")
        return b64_str

    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        """
        Clear the display with specified color.

        Args:
            color: RGB tuple (r, g, b) where each component is 0-255.
                   If None, defaults to COLOR_BLACK.
        """
        if color is None:
            color = self.COLOR_BLACK

        if self.draw:
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
        """
        Draw text at the specified position.

        Args:
            text: The string to display
            x: X coordinate (pixels from left)
            y: Y coordinate (pixels from top)
            color: RGB tuple for text color (default: COLOR_WHITE)
            font_size: Font size in pixels
            font_path: Optional path to TTF font file
        """
        if color is None:
            color = self.COLOR_WHITE

        if self.draw is None:
            return

        try:
            # Load font
            if font_path and font_path.exists():
                font = ImageFont.truetype(str(font_path), font_size)
            else:
                # Try to load default font, fall back to PIL default
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size
                    )
                except Exception:
                    font = ImageFont.load_default()

            # Draw text
            self.draw.text((x, y), text, fill=color, font=font)

        except Exception as e:
            logger.warning(f"Failed to render text: {e}")

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
        """
        Draw a rectangle.

        Args:
            x1: Top-left X coordinate
            y1: Top-left Y coordinate
            x2: Bottom-right X coordinate
            y2: Bottom-right Y coordinate
            fill: RGB tuple for fill color (None = no fill)
            outline: RGB tuple for outline color (None = no outline)
            width: Outline width in pixels
        """
        if self.draw is None:
            return

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
        """
        Draw a circle.

        Args:
            x: Center X coordinate
            y: Center Y coordinate
            radius: Circle radius in pixels
            fill: RGB tuple for fill color (None = no fill)
            outline: RGB tuple for outline color (None = no outline)
            width: Outline width in pixels
        """
        if self.draw is None:
            return

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
        """
        Draw a line.

        Args:
            x1: Start X coordinate
            y1: Start Y coordinate
            x2: End X coordinate
            y2: End Y coordinate
            color: RGB tuple for line color (default: COLOR_WHITE)
            width: Line width in pixels
        """
        if color is None:
            color = self.COLOR_WHITE

        if self.draw is None:
            return

        self.draw.line([(x1, y1), (x2, y2)], fill=color, width=width)

    def polygon(
        self,
        points: list,
        fill: Optional[Tuple[int, int, int]] = None,
        outline: Optional[Tuple[int, int, int]] = None,
        width: int = 1,
    ) -> None:
        """
        Draw a polygon.

        Args:
            points: List of (x, y) tuples defining polygon vertices
            fill: RGB tuple for fill color (None = no fill)
            outline: RGB tuple for outline color (None = no outline)
            width: Outline width in pixels
        """
        if self.draw is None:
            return

        self.draw.polygon(points, fill=fill, outline=outline, width=width)

    def image(
        self,
        image_path: Path,
        x: int,
        y: int,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """
        Draw an image from file.

        Args:
            image_path: Path to image file (PNG, JPG, etc.)
            x: X coordinate (top-left corner)
            y: Y coordinate (top-left corner)
            width: Resize width (None to keep original)
            height: Resize height (None to keep original)
        """
        if self.buffer is None:
            return

        try:
            # Load image
            img = Image.open(image_path)

            # Resize if dimensions provided
            if width or height:
                # Calculate dimensions preserving aspect ratio if only one is provided
                if width and not height:
                    aspect = img.height / img.width
                    height = int(width * aspect)
                elif height and not width:
                    aspect = img.width / img.height
                    width = int(height * aspect)

                img = img.resize((width, height), Image.Resampling.LANCZOS)

            # Paste image onto buffer
            self.buffer.paste(img, (x, y))

        except Exception as e:
            logger.warning(f"Failed to draw image {image_path}: {e}")

    def get_text_size(
        self, text: str, font_size: int = 16, font_path: Optional[Path] = None
    ) -> Tuple[int, int]:
        """
        Get the dimensions of rendered text.

        Args:
            text: The string to measure
            font_size: Font size in pixels
            font_path: Optional path to TTF font file

        Returns:
            Tuple of (width, height) in pixels
        """
        if self.draw is None:
            return (0, 0)

        try:
            # Load font
            if font_path and font_path.exists():
                font = ImageFont.truetype(str(font_path), font_size)
            else:
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size
                    )
                except Exception:
                    font = ImageFont.load_default()

            # Get text bounding box
            bbox = self.draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]

            return (width, height)

        except Exception as e:
            logger.warning(f"Failed to measure text: {e}")
            # Approximate: ~10px wide per char, font_size high
            return (len(text) * int(font_size * 0.6), font_size)

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
        Draw the status bar at the top of the display.

        Args:
            time_str: Time string (e.g. "14:30")
            battery_percent: Battery level 0-100
            signal_strength: Signal bars 0-4
        """
        # Match the Whisplay portrait status-bar layout for simulation fidelity.
        self.rectangle(0, 0, self.WIDTH, self.STATUS_BAR_HEIGHT, fill=self.COLOR_DARK_GRAY)

        time_x = (self.WIDTH - len(time_str) * 7) // 2
        self.text(time_str, time_x, 4, color=self.COLOR_WHITE, font_size=14)

        battery_x = self.WIDTH - 45
        battery_y = 6
        battery_width = 35
        battery_height = 12

        self.rectangle(
            battery_x,
            battery_y,
            battery_x + battery_width,
            battery_y + battery_height,
            outline=self.COLOR_WHITE,
            width=1,
        )

        self.rectangle(
            battery_x + battery_width,
            battery_y + 3,
            battery_x + battery_width + 3,
            battery_y + battery_height - 3,
            fill=self.COLOR_WHITE,
        )

        fill_width = int((battery_width - 4) * (battery_percent / 100))
        if fill_width > 0:
            fill_color = self.COLOR_GREEN if battery_percent > 20 else self.COLOR_RED
            self.rectangle(
                battery_x + 2,
                battery_y + 2,
                battery_x + 2 + fill_width,
                battery_y + battery_height - 2,
                fill=fill_color,
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

    def draw_rgb565_region(
        self, x: int, y: int, width: int, height: int, pixel_data: bytes
    ) -> None:
        """Receive RGB565 region from LVGL flush, composite into framebuffer, and push to browser."""
        if self._rgb565_framebuffer is None:
            return

        # Write region into the RGB565 framebuffer at the correct offset
        src_offset = 0
        for row in range(height):
            dst_row = y + row
            if dst_row >= self.HEIGHT:
                break
            dst_offset = (dst_row * self.WIDTH + x) * 2
            row_bytes = min(width, self.WIDTH - x) * 2
            self._rgb565_framebuffer[dst_offset : dst_offset + row_bytes] = (
                pixel_data[src_offset : src_offset + row_bytes]
            )
            src_offset += width * 2

        # Convert full framebuffer to PNG and push to browser
        self._push_rgb565_to_browser()

    def _push_rgb565_to_browser(self) -> None:
        """Convert the RGB565 framebuffer to PNG and send via WebSocket."""
        if self._rgb565_framebuffer is None or self.web_server is None:
            return

        # Convert RGB565 to RGB888 PIL image
        img = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        pixels = []
        buf = self._rgb565_framebuffer
        for i in range(0, len(buf), 2):
            val = (buf[i] << 8) | buf[i + 1]
            r = (val >> 11) & 0x1F
            g = (val >> 5) & 0x3F
            b = val & 0x1F
            pixels.append((r << 3, g << 2, b << 3))
        img.putdata(pixels)

        # Encode as base64 PNG
        png_buffer = io.BytesIO()
        img.save(png_buffer, format="PNG")
        png_data = base64.b64encode(png_buffer.getvalue()).decode("ascii")
        self.web_server.send_display_update(png_data)

    def get_flush_target(self) -> "SimulationDisplayAdapter | None":
        """Return self as LVGL flush target."""
        return self

    def get_backend_kind(self) -> str:
        """Return 'lvgl' when an LVGL backend is attached, otherwise 'pil'."""
        backend = getattr(self, "ui_backend", None)
        if backend is not None and getattr(backend, "initialized", False):
            return "lvgl"
        return "pil"

    def get_ui_backend(self):
        """Return the attached LVGL backend, if any."""
        return getattr(self, "ui_backend", None)

    def update(self) -> None:
        """
        Update the display by sending buffer to web browser.

        This method converts the current PIL buffer to a PNG image,
        encodes it as base64, and sends it to connected browsers via WebSocket.
        """
        # Convert buffer to base64 PNG
        png_data = self.get_buffer_as_png_base64()

        # Send to web server (if available)
        if self.web_server:
            self.web_server.send_display_update(png_data)

    def set_backlight(self, brightness: float) -> None:
        """
        Set backlight brightness (no-op for simulation).

        Args:
            brightness: Brightness level 0.0-1.0
        """
        # No backlight in simulation mode
        pass

    def cleanup(self) -> None:
        """Clean up display resources."""
        self.buffer = None
        self.draw = None
        logger.info("Simulation display adapter cleaned up")
