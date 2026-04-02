"""
Display hardware factory for YoyoPod.

This module provides factory functions to create the appropriate display
adapter based on hardware detection or configuration.

The factory supports:
- Automatic hardware detection
- Manual hardware selection
- Environment variable override
- Simulation mode for testing

Author: YoyoPod Team
Date: 2025-11-30
"""

import os

from loguru import logger

from yoyopy.ui.display.display_hal import DisplayHAL
from yoyopy.ui.display.whisplay_paths import find_whisplay_driver


def detect_hardware() -> str:
    """
    Auto-detect which display hardware is connected.

    Detection logic (in order of priority):
    1. Check environment variable YOYOPOD_DISPLAY
    2. Check for Whisplay driver in configured/common locations
    3. Check for DisplayHATMini library availability
    4. Default to simulation mode

    Returns:
        Hardware type: "whisplay", "pimoroni", or "simulation"

    Examples:
        >>> detect_hardware()
        'whisplay'  # If Whisplay driver found

        >>> os.environ['YOYOPOD_DISPLAY'] = 'pimoroni'
        >>> detect_hardware()
        'pimoroni'  # Environment override
    """
    # Priority 1: Environment variable override
    env_display = os.getenv("YOYOPOD_DISPLAY")
    if env_display:
        hardware = env_display.lower()
        logger.info(f"Display hardware set by YOYOPOD_DISPLAY={hardware}")
        return hardware

    # Priority 2: Check for Whisplay driver file
    whisplay_driver_path = find_whisplay_driver()
    if whisplay_driver_path:
        logger.info(f"Detected Whisplay HAT (driver found at {whisplay_driver_path})")
        return "whisplay"

    # Priority 3: Check for Pimoroni library
    try:
        import displayhatmini
        logger.info("Detected Pimoroni Display HAT Mini (library imported successfully)")
        return "pimoroni"
    except Exception as e:
        logger.debug(f"DisplayHATMini import failed during detection: {e}")

    # Priority 4: No hardware detected, default to simulation
    logger.warning("No display hardware detected - defaulting to simulation mode")
    logger.info("To force hardware type, set YOYOPOD_DISPLAY environment variable")
    return "simulation"


def get_display(hardware: str = "auto", simulate: bool = False) -> DisplayHAL:
    """
    Factory function to create the appropriate display adapter.

    This is the main entry point for creating display instances. It handles
    hardware auto-detection, adapter selection, and initialization.

    Args:
        hardware: Hardware type selector:
            - "auto": Auto-detect hardware (default)
            - "whisplay": Force Whisplay HAT
            - "pimoroni": Force Pimoroni Display HAT Mini
            - "simulation": Force simulation mode
        simulate: Force simulation mode regardless of hardware parameter

    Returns:
        DisplayHAL: Initialized display adapter instance

    Raises:
        ValueError: If hardware type is unknown

    Examples:
        >>> # Auto-detect hardware
        >>> display = get_display()
        >>> print(f"{display.WIDTH}x{display.HEIGHT}")
        240x280  # If Whisplay detected

        >>> # Force specific hardware
        >>> display = get_display("whisplay")
        >>> display.ORIENTATION
        'portrait'

        >>> # Simulation mode (no hardware required)
        >>> display = get_display(simulate=True)
        >>> display.clear()
        >>> display.update()  # No-op in simulation

        >>> # Override via hardware parameter
        >>> display = get_display("pimoroni")
        >>> display.WIDTH
        320
    """
    # If simulate=True, force simulation hardware regardless of auto-detection
    if simulate:
        hardware = "simulation"
        logger.info("Forcing simulation mode (--simulate flag)")

    # Auto-detect if requested (and not already forced to simulation)
    if hardware == "auto":
        hardware = detect_hardware()

    # Normalize to lowercase
    hardware = hardware.lower()

    # Create appropriate adapter
    if hardware == "whisplay":
        logger.info("Creating Whisplay display adapter (240×280 portrait)")
        from yoyopy.ui.display.adapters.whisplay import WhisplayDisplayAdapter

        return WhisplayDisplayAdapter(simulate=simulate)

    elif hardware == "pimoroni":
        logger.info("Creating Pimoroni display adapter (320×240 landscape)")
        from yoyopy.ui.display.adapters.pimoroni import PimoroniDisplayAdapter

        return PimoroniDisplayAdapter(simulate=simulate)

    elif hardware == "simulation":
        logger.info("Creating simulation display adapter (240×280 portrait)")
        # Use dedicated simulation adapter with web server support
        from yoyopy.ui.display.adapters.simulation import SimulationDisplayAdapter

        adapter = SimulationDisplayAdapter(simulate=True)

        # Start web server for browser display
        if simulate or hardware == "simulation":
            try:
                from yoyopy.ui.web_server import get_server
                server = get_server()
                adapter.web_server = server
                server.start()
                logger.info("Web server started - view display at http://localhost:5000")
            except Exception as e:
                logger.warning(f"Failed to start web server: {e}")
                logger.warning("Simulation display will work without web view")

        return adapter

    else:
        # Unknown hardware type
        valid_types = ["auto", "whisplay", "pimoroni", "simulation"]
        raise ValueError(
            f"Unknown display hardware type: '{hardware}'. "
            f"Valid options: {', '.join(valid_types)}"
        )


def get_hardware_info(adapter: DisplayHAL) -> dict:
    """
    Get information about a display adapter.

    Useful for debugging and logging hardware configuration.

    Args:
        adapter: Display adapter instance

    Returns:
        Dictionary with hardware information:
            - type: Adapter class name
            - width: Display width in pixels
            - height: Display height in pixels
            - orientation: "landscape" or "portrait"
            - status_bar_height: Status bar height in pixels
            - simulated: True if running in simulation mode

    Example:
        >>> display = get_display()
        >>> info = get_hardware_info(display)
        >>> print(info)
        {
            'type': 'WhisplayDisplayAdapter',
            'width': 240,
            'height': 280,
            'orientation': 'portrait',
            'status_bar_height': 25,
            'simulated': False
        }
    """
    return {
        'type': adapter.__class__.__name__,
        'width': adapter.WIDTH,
        'height': adapter.HEIGHT,
        'orientation': adapter.ORIENTATION,
        'status_bar_height': adapter.STATUS_BAR_HEIGHT,
        'simulated': adapter.simulate
    }
