"""
Hardware Abstraction Layer (HAL) for YoYoPod display subsystem.

This module defines the abstract interface that all display hardware
adapters must implement, enabling support for multiple display types
(Whisplay hardware, Pimoroni/ST7789 hardware, and simulation) with a unified API.

Author: YoYoPod Team
Date: 2025-11-30
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple
from pathlib import Path


class DisplayHAL(ABC):
    """
    Abstract base class for display hardware adapters.

    All display implementations must inherit
    from this class and implement all abstract methods.

    This ensures a consistent API across different hardware backends,
    allowing the rest of the application to remain hardware-agnostic.

    Attributes:
        WIDTH: Display width in pixels
        HEIGHT: Display height in pixels
        ORIENTATION: "landscape" or "portrait"
        STATUS_BAR_HEIGHT: Height reserved for status bar in pixels
        COLOR_*: Standard RGB color constants
    """

    # Display dimensions (must be set by subclass)
    DISPLAY_TYPE: str = "unknown"
    SIMULATED_HARDWARE: str | None = None
    WIDTH: int = 0
    HEIGHT: int = 0
    ORIENTATION: str = "landscape"  # "landscape" or "portrait"
    STATUS_BAR_HEIGHT: int = 20

    # Standard color palette (RGB tuples)
    COLOR_BLACK = (0, 0, 0)
    COLOR_WHITE = (255, 255, 255)
    COLOR_RED = (255, 0, 0)
    COLOR_GREEN = (0, 255, 0)
    COLOR_BLUE = (0, 0, 255)
    COLOR_YELLOW = (255, 255, 0)
    COLOR_CYAN = (0, 255, 255)
    COLOR_MAGENTA = (255, 0, 255)
    COLOR_GRAY = (128, 128, 128)
    COLOR_DARK_GRAY = (64, 64, 64)

    @abstractmethod
    def __init__(self, simulate: bool = False) -> None:
        """
        Initialize the display hardware.

        Args:
            simulate: If True, run in simulation mode without hardware
        """
        pass

    @abstractmethod
    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        """
        Clear the display with specified color.

        Args:
            color: RGB tuple (r, g, b) where each component is 0-255.
                   If None, defaults to COLOR_BLACK.
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
            x1, y1: Top-left corner coordinates
            x2, y2: Bottom-right corner coordinates
            fill: RGB tuple for fill color (None for transparent)
            outline: RGB tuple for border color (None for no border)
            width: Border width in pixels
        """
        pass

    @abstractmethod
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
            x, y: Center point coordinates
            radius: Circle radius in pixels
            fill: RGB tuple for fill color (None for transparent)
            outline: RGB tuple for border color (None for no border)
            width: Border width in pixels
        """
        pass

    @abstractmethod
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
            x1, y1: Start point coordinates
            x2, y2: End point coordinates
            color: RGB tuple for line color (default: COLOR_WHITE)
            width: Line width in pixels
        """
        pass

    @abstractmethod
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
            x, y: Top-left corner position to draw image
            width: Resize width (None to keep original)
            height: Resize height (None to keep original)
        """
        pass

    @abstractmethod
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
        Draw a status bar at the top of the screen.

        The status bar typically shows:
        - Signal strength (left): 0-4 bars
        - Time (center): HH:MM format
        - Battery (right): Percentage with icon

        Args:
            time_str: Time string to display (e.g., "14:30")
            battery_percent: Battery level 0-100
            signal_strength: Signal bars 0-4 (0=no signal, 4=full)
            charging: Whether the device is actively charging
            external_power: Whether external power is currently attached
            power_available: Whether live power telemetry is currently available
        """
        pass

    @abstractmethod
    def update(self) -> None:
        """
        Flush the drawing buffer to the physical display.

        This method must be called after drawing operations to make
        changes visible on the screen. Implementations typically use
        double-buffering for flicker-free updates.
        """
        pass

    @abstractmethod
    def set_backlight(self, brightness: float) -> None:
        """
        Set display backlight brightness.

        Args:
            brightness: Brightness level from 0.0 (off) to 1.0 (max)
        """
        pass

    @abstractmethod
    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        """
        Calculate the size of rendered text.

        Useful for centering text or checking if it fits in available space.

        Args:
            text: The string to measure
            font_size: Font size in pixels

        Returns:
            (width, height) tuple in pixels
        """
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """
        Cleanup hardware resources on shutdown.

        This method should:
        - Turn off backlight
        - Clear display
        - Release GPIO pins
        - Free any allocated memory
        """
        pass

    def get_backend_kind(self) -> str:
        """Return the active UI backend kind for this display adapter."""

        return "unavailable"

    def get_ui_backend(self) -> Any | None:
        """Return an optional backend-specific UI bridge."""

        return None

    def reset_ui_backend(self) -> None:
        """Reset backend-specific UI state during renderer handoff."""

        return None

    # Helper methods (default implementations, can be overridden)
    def get_orientation(self) -> str:
        """
        Get display orientation.

        Returns:
            "landscape" or "portrait"
        """
        return self.ORIENTATION

    def is_portrait(self) -> bool:
        """
        Check if display is in portrait orientation.

        Returns:
            True if HEIGHT > WIDTH
        """
        return self.ORIENTATION == "portrait"

    def is_landscape(self) -> bool:
        """
        Check if display is in landscape orientation.

        Returns:
            True if WIDTH > HEIGHT
        """
        return self.ORIENTATION == "landscape"

    def get_dimensions(self) -> Tuple[int, int]:
        """
        Get display dimensions.

        Returns:
            (width, height) tuple in pixels
        """
        return (self.WIDTH, self.HEIGHT)

    def get_usable_height(self) -> int:
        """
        Get usable height excluding status bar.

        Returns:
            Height in pixels available for content
        """
        return self.HEIGHT - self.STATUS_BAR_HEIGHT
