"""
Display hardware factory for YoyoPod.

This module provides factory functions to create the appropriate display
adapter based on hardware detection or configuration.
"""

from __future__ import annotations

import os

from loguru import logger

from yoyopy.config.models import PimoroniGpioConfig
from yoyopy.ui.display.hal import DisplayHAL
from yoyopy.ui.display.adapters.whisplay_paths import find_whisplay_driver

VALID_DISPLAY_TYPES = {"auto", "whisplay", "pimoroni", "simulation"}


def _get_pimoroni_gpio_config() -> PimoroniGpioConfig | None:
    """Return PimoroniGpioConfig from the active board config, or None."""
    try:
        from yoyopy.config.manager import ConfigManager

        mgr = ConfigManager()
        return mgr.app_settings.display.pimoroni_gpio
    except Exception:
        return None


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


def _try_attach_lvgl_backend(adapter: DisplayHAL) -> bool:
    """Attempt to wire an LvglDisplayBackend to the adapter's flush target.

    Returns True if LVGL was successfully attached, False otherwise.
    """
    flush_target = adapter.get_flush_target()
    if flush_target is None:
        return False

    try:
        from yoyopy.ui.lvgl_binding import LvglDisplayBackend

        backend = LvglDisplayBackend(flush_target=flush_target)
        if backend.initialize():
            adapter.ui_backend = backend
            logger.info(
                "LVGL backend attached to {} ({}x{})",
                adapter.__class__.__name__,
                flush_target.WIDTH,
                flush_target.HEIGHT,
            )
            return True
        else:
            logger.info("LVGL backend available but failed to initialize")
            return False
    except Exception as exc:
        logger.debug("LVGL backend not available: {}", exc)
        return False


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
        # Try Pi-native displayhatmini first
        try:
            import displayhatmini  # noqa: F401

            logger.info("Creating Pimoroni display adapter (320x240 landscape, displayhatmini)")
            from yoyopy.ui.display.adapters.pimoroni import PimoroniDisplayAdapter

            return PimoroniDisplayAdapter(simulate=False)
        except Exception:
            pass

        # Fallback: Cubie-native spidev + gpiod adapter
        gpio_config = _get_pimoroni_gpio_config()
        if gpio_config is not None and (gpio_config.dc is not None or gpio_config.cs is not None):
            logger.info("Creating Cubie Pimoroni display adapter (320x240 landscape, spidev + gpiod)")
            from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

            adapter = CubiePimoroniAdapter(simulate=False, gpio_config=gpio_config)
            _try_attach_lvgl_backend(adapter)
            return adapter

        logger.warning("Pimoroni requested but no displayhatmini or GPIO config available")
        logger.info("Falling back to Pimoroni simulation mode")
        from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

        return CubiePimoroniAdapter(simulate=True)

    if hardware == "simulation":
        logger.info("Creating simulation display adapter (240x280 portrait, Whisplay profile)")
        from yoyopy.ui.display.adapters.simulation import SimulationDisplayAdapter

        adapter = _attach_simulation_preview(SimulationDisplayAdapter())
        _try_attach_lvgl_backend(adapter)
        return adapter

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
