"""Display hardware factory for the LVGL-only runtime."""

from __future__ import annotations

import os

from loguru import logger

from yoyopod.config.models import PimoroniGpioConfig
from yoyopod.ui.display.hal import DisplayHAL
from yoyopod.ui.display.adapters.whisplay_paths import find_whisplay_driver

VALID_DISPLAY_TYPES = {"auto", "whisplay", "pimoroni", "simulation"}


def _get_pimoroni_gpio_config() -> PimoroniGpioConfig | None:
    """Return Pimoroni GPIO config from the active board config when available."""

    try:
        from yoyopod.config.manager import ConfigManager

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

    gpio_config = _get_pimoroni_gpio_config()
    if gpio_config is not None and gpio_config.dc is not None and gpio_config.backlight is not None:
        logger.info("Detected Pimoroni/ST7789 LVGL path from board GPIO config")
        return "pimoroni"

    logger.warning("No supported display hardware detected - defaulting to simulation mode")
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
        from yoyopod.ui.display.adapters.simulation_web.server import get_server

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
    whisplay_renderer: str = "lvgl",
    whisplay_lvgl_buffer_lines: int = 40,
) -> DisplayHAL:
    """Create the appropriate display adapter."""

    hardware = _resolve_display_hardware(hardware, simulate)

    if hardware == "whisplay":
        logger.info(
            "Creating Whisplay display adapter with renderer={}",
            whisplay_renderer,
        )
        from yoyopod.ui.display.adapters.whisplay import WhisplayDisplayAdapter

        return WhisplayDisplayAdapter(
            simulate=False,
            renderer=whisplay_renderer,
            lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
        )

    if hardware == "pimoroni":
        logger.info("Creating Pimoroni LVGL display adapter")
        from yoyopod.ui.display.adapters.pimoroni import PimoroniDisplayAdapter

        adapter = PimoroniDisplayAdapter(
            simulate=False,
            lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
            gpio_config=_get_pimoroni_gpio_config(),
        )
        if adapter.simulate:
            return _attach_simulation_preview(adapter)
        return adapter

    if hardware == "simulation":
        logger.info("Creating simulation display adapter on the shared LVGL path")
        from yoyopod.ui.display.adapters.simulation import SimulationDisplayAdapter

        return _attach_simulation_preview(
            SimulationDisplayAdapter(
                lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
            )
        )

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
