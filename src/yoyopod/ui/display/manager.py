"""
Display controller with Hardware Abstraction Layer (HAL).

This module provides the Display class, which acts as a facade for hardware-specific
display adapters. The class maintains backward compatibility with existing code while
supporting multiple display hardware types (Pimoroni, Whisplay, etc.).

The display system uses the following architecture:
    Display (facade) → DisplayFactory → DisplayHAL → Hardware-specific adapter

This allows the rest of the application to remain hardware-independent.

Author: YoyoPod Team
Date: 2025-11-30
"""

from pathlib import Path
from typing import Any, Optional, Tuple

from yoyopod.ui.display.factory import get_display
from yoyopod.ui.display.hal import DisplayHAL


class Display:
    """
    Display controller with hardware abstraction.

    This class maintains the same API as the original Display class for backward
    compatibility, but internally delegates to hardware-specific adapters via the
    DisplayHAL interface.

    The hardware type can be specified explicitly or auto-detected. All drawing
    operations are delegated to the underlying adapter, which handles the
    hardware-specific implementation details.

    Attributes:
        WIDTH: Display width in pixels (from adapter)
        HEIGHT: Display height in pixels (from adapter)
        ORIENTATION: "landscape" or "portrait" (from adapter)
        STATUS_BAR_HEIGHT: Status bar height in pixels (from adapter)
        COLOR_*: Standard RGB color constants (from adapter)

    Examples:
        >>> # Auto-detect hardware
        >>> display = Display()
        >>> print(f"{display.WIDTH}x{display.HEIGHT} {display.ORIENTATION}")
        240x280 portrait  # If Whisplay detected

        >>> # Force specific hardware
        >>> display = Display(hardware="pimoroni")
        >>> display.WIDTH
        320

        >>> # Simulation mode
        >>> display = Display(simulate=True)
        >>> display.clear()
        >>> display.update()
    """

    def __init__(
        self,
        hardware: str = "auto",
        simulate: bool = False,
        whisplay_renderer: str = "lvgl",
        whisplay_lvgl_buffer_lines: int = 40,
    ) -> None:
        """
        Initialize display with hardware abstraction.

        Args:
            hardware: Display hardware type:
                - "auto": Auto-detect hardware (default)
                - "whisplay": Force Whisplay HAT
                - "pimoroni": Force Pimoroni Display HAT Mini
                - "simulation": Force simulation mode
            simulate: Force simulation mode regardless of hardware parameter

        Raises:
            ValueError: If hardware type is unknown
        """
        # Create appropriate adapter using factory
        self._adapter: DisplayHAL = get_display(
            hardware,
            simulate,
            whisplay_renderer=whisplay_renderer,
            whisplay_lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
        )

        # Expose adapter properties as Display properties for backward compatibility
        self.WIDTH = self._adapter.WIDTH
        self.HEIGHT = self._adapter.HEIGHT
        self.ORIENTATION = self._adapter.ORIENTATION
        self.STATUS_BAR_HEIGHT = self._adapter.STATUS_BAR_HEIGHT

        # Expose color constants
        self.COLOR_BLACK = self._adapter.COLOR_BLACK
        self.COLOR_WHITE = self._adapter.COLOR_WHITE
        self.COLOR_RED = self._adapter.COLOR_RED
        self.COLOR_GREEN = self._adapter.COLOR_GREEN
        self.COLOR_BLUE = self._adapter.COLOR_BLUE
        self.COLOR_YELLOW = self._adapter.COLOR_YELLOW
        self.COLOR_CYAN = self._adapter.COLOR_CYAN
        self.COLOR_MAGENTA = self._adapter.COLOR_MAGENTA
        self.COLOR_GRAY = self._adapter.COLOR_GRAY
        self.COLOR_DARK_GRAY = self._adapter.COLOR_DARK_GRAY

        # Expose simulate flag for compatibility
        self.simulate = self._adapter.simulate
        self.backend_kind = self._adapter.get_backend_kind()

    # Delegate all methods to adapter
    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        """Clear display with specified color."""
        self._adapter.clear(color)

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
        self._adapter.text(text, x, y, color, font_size, font_path)

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
        self._adapter.rectangle(x1, y1, x2, y2, fill, outline, width)

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
        self._adapter.circle(x, y, radius, fill, outline, width)

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
        self._adapter.line(x1, y1, x2, y2, color, width)

    def image(
        self,
        image_path: Path,
        x: int,
        y: int,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> None:
        """Draw an image from file."""
        self._adapter.image(image_path, x, y, width, height)

    def status_bar(
        self,
        time_str: str = "--:--",
        battery_percent: int = 100,
        signal_strength: int = 4,
        charging: bool = False,
        external_power: bool = False,
        power_available: bool = True,
    ) -> None:
        """Draw status bar at top of screen."""
        self._adapter.status_bar(
            time_str,
            battery_percent,
            signal_strength,
            charging,
            external_power,
            power_available,
        )

    def update(self) -> None:
        """Flush buffer to physical display."""
        self._adapter.update()

    def set_backlight(self, brightness: float) -> None:
        """Set backlight brightness (0.0 to 1.0)."""
        self._adapter.set_backlight(brightness)

    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        """Calculate rendered text dimensions."""
        return self._adapter.get_text_size(text, font_size)

    def cleanup(self) -> None:
        """Cleanup display resources."""
        self._adapter.cleanup()

    # Helper methods
    def is_portrait(self) -> bool:
        """Check if display is in portrait orientation."""
        return self._adapter.is_portrait()

    def is_landscape(self) -> bool:
        """Check if display is in landscape orientation."""
        return self._adapter.is_landscape()

    def get_orientation(self) -> str:
        """Get display orientation."""
        return self._adapter.get_orientation()

    def get_dimensions(self) -> Tuple[int, int]:
        """Get display dimensions (width, height)."""
        return self._adapter.get_dimensions()

    def get_usable_height(self) -> int:
        """Get usable height excluding status bar."""
        return self._adapter.get_usable_height()

    def get_adapter(self) -> DisplayHAL:
        """
        Get the underlying hardware adapter.

        This method is provided for advanced use cases where direct adapter
        access is needed. In most cases, the Display facade methods should
        be sufficient.

        Returns:
            DisplayHAL: The hardware adapter instance
        """
        return self._adapter

    def get_ui_backend(self) -> Any | None:
        """Return the optional backend-specific UI bridge."""

        return self._adapter.get_ui_backend()

    def reset_ui_backend(self) -> None:
        """Reset backend-specific UI state during renderer handoff."""

        self._adapter.reset_ui_backend()

    def refresh_backend_kind(self) -> str:
        """Refresh and return the active backend kind from the adapter."""

        self.backend_kind = self._adapter.get_backend_kind()
        return self.backend_kind
