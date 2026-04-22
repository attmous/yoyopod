"""
Display HAL for YoyoPod.

Provides hardware abstraction for the LVGL-backed display runtime:
- PiSugar Whisplay HAT (240×280 portrait)
- Simulation mode that mirrors the Whisplay LVGL profile

The Display class provides a unified interface that works with any supported hardware.
"""

from yoyopod.ui.display.factory import detect_hardware, get_display, get_hardware_info
from yoyopod.ui.display.hal import DisplayHAL
from yoyopod.ui.display.manager import Display

__all__ = [
    'DisplayHAL',
    'Display',
    'get_display',
    'detect_hardware',
    'get_hardware_info',
]
