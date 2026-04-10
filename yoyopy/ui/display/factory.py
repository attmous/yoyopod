"""
Display hardware factory for YoyoPod.

This module provides factory functions to create the appropriate display
adapter based on hardware detection or configuration.
"""

from __future__ import annotations

import os

from loguru import logger

from yoyopy.ui.display.hal import DisplayHAL
from yoyopy.ui.display.adapters.whisplay_paths import find_whisplay_driver

VALID_DISPLAY_TYPES = {"auto", "whisplay", "pimoroni", "simulation"}


def _normalize_display_hardware(hardware: str) -> str:
    """Normalize and validate a display hardware selector."""

    normalized = (hardware or "auto").strip().lower()
    if normalized not in VALID_DISPLAY_TYPES:
        valid = ", ".join(sorted(VALID_DISPLAY_TYPES))
        raise ValueError(f"Unknown display hardware type: '{hardware}'. Valid options: {valid}")
    return normalized


def detect_hardware() -> str:
    """Auto-detect which display hardware is connected."""

    env_display = os.getenv("YOYOPOD_DISPLAY")
    if env_display:
        hardware = _normalize_display_hardware(env_display)
        logger.info("Display hardware set by YOYOPOD_DISPLAY={}", hardware)
        if hardware != "auto":
            return hardware

    whisplay_driver_path = find_whisplay_driver()
    if whisplay_driver_path:
        logger.info("Detected Whisplay HAT (driver found at {})", whisplay_driver_path)
        return "whisplay"

    try:
        import displayhatmini  # noqa: F401

        logger.info("Detected Pimoroni Display HAT Mini (library imported successfully)")
        return "pimoroni"
    except Exception as exc:
        logger.debug("DisplayHATMini import failed during detection: {}", exc)

    logger.warning("No display hardware detected - defaulting to simulation mode")
    logger.info("To force hardware type, set YOYOPOD_DISPLAY environment variable")
    return "simulation"


def _resolve_display_hardware(hardware: str, simulate: bool) -> str:
    """Resolve the effective display adapter selection for this app run."""

    requested_hardware = _normalize_display_hardware(hardware)

    if simulate:
        if requested_hardware == "simulation":
            logger.info("Using simulation display (--simulate flag)")
        else:
            logger.info(
                "Forcing simulation display (--simulate flag) instead of {}",
                requested_hardware,
            )
        return "simulation"

    if requested_hardware == "auto":
        return detect_hardware()

    return requested_hardware


def _attach_simulation_preview(adapter: DisplayHAL) -> DisplayHAL:
    """Attach the browser preview transport to the simulation adapter."""

    try:
        from yoyopy.ui.web_server import get_server

        server = get_server()
        adapter.web_server = server
        server.start()
        logger.info("Web server started - view display at http://localhost:5000")
    except Exception as exc:
        logger.warning("Failed to start web server: {}", exc)
        logger.warning("Simulation display will work without web view")

    return adapter


def get_display(
    hardware: str = "auto",
    simulate: bool = False,
    *,
    whisplay_renderer: str = "pil",
    whisplay_lvgl_buffer_lines: int = 40,
) -> DisplayHAL:
    """Create the appropriate display adapter."""

    hardware = _resolve_display_hardware(hardware, simulate)

    if hardware == "whisplay":
        logger.info(
            "Creating Whisplay display adapter with renderer={}",
            whisplay_renderer,
        )
        from yoyopy.ui.display.adapters.whisplay import WhisplayDisplayAdapter

        return WhisplayDisplayAdapter(
            simulate=False,
            renderer=whisplay_renderer,
            lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
        )

    if hardware == "pimoroni":
        logger.info("Creating Pimoroni display adapter (320x240 landscape)")
        from yoyopy.ui.display.adapters.pimoroni import PimoroniDisplayAdapter

        return PimoroniDisplayAdapter(simulate=False)

    if hardware == "simulation":
        logger.info("Creating simulation display adapter (240x280 portrait, Whisplay profile)")
        from yoyopy.ui.display.adapters.simulation import SimulationDisplayAdapter

        return _attach_simulation_preview(SimulationDisplayAdapter())

    valid_types = ", ".join(sorted(VALID_DISPLAY_TYPES))
    raise ValueError(f"Unknown display hardware type: '{hardware}'. Valid options: {valid_types}")


def get_hardware_info(adapter: DisplayHAL) -> dict[str, object]:
    """Return debugging information about a display adapter."""

    return {
        "display_type": getattr(adapter, "DISPLAY_TYPE", "unknown"),
        "simulated_hardware": getattr(adapter, "SIMULATED_HARDWARE", None),
        "type": adapter.__class__.__name__,
        "width": adapter.WIDTH,
        "height": adapter.HEIGHT,
        "orientation": adapter.ORIENTATION,
        "status_bar_height": adapter.STATUS_BAR_HEIGHT,
        "simulated": adapter.simulate,
        "renderer": adapter.get_backend_kind(),
    }
