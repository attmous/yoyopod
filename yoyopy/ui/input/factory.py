"""
Input factory for auto-detecting and creating input adapters.

Automatically selects the appropriate input adapter based on
hardware detection and configuration.
"""

from typing import Any, Dict, Optional

from loguru import logger

from yoyopy.ui.input.hal import InputAction, InteractionProfile
from yoyopy.ui.input.manager import InputManager


def get_input_manager(
    display_adapter: object,
    config: Optional[Dict[str, Any]] = None,
    simulate: bool = False,
) -> Optional[InputManager]:
    """
    Create input manager with appropriate adapters based on hardware.

    Automatically detects the display hardware type and creates matching
    input adapters. Can also add voice input or other adapters based on config.

    Args:
        display_adapter: Display adapter instance (to determine hardware type)
        config: Configuration dict with input settings (optional)
        simulate: Run in simulation mode (no hardware)

    Returns:
        Configured InputManager instance, or None if no input available
    """
    config = config or {}
    input_config = config.get("input", {})

    manager = InputManager(interaction_profile=InteractionProfile.STANDARD)
    adapter_name = display_adapter.__class__.__name__

    logger.info("Creating input manager...")
    logger.debug(f"  Display adapter: {adapter_name}")

    if adapter_name == "PimoroniDisplayAdapter":
        logger.info("  Detected Pimoroni Display HAT Mini")
        display_device = getattr(display_adapter, "device", None)

        if display_device or simulate:
            from yoyopy.ui.input.adapters.four_button import FourButtonInputAdapter

            button_adapter = FourButtonInputAdapter(
                display_device=display_device,
                simulate=simulate,
            )
            manager.add_adapter(button_adapter)
            logger.info("  -> Added 4-button input (A, B, X, Y)")
        else:
            logger.warning("  -> No display device available for button input")

    elif adapter_name == "WhisplayDisplayAdapter":
        logger.info("  Detected Whisplay HAT")
        manager.set_interaction_profile(InteractionProfile.ONE_BUTTON)
        whisplay_device = getattr(display_adapter, "device", None)
        enable_navigation = input_config.get("ptt_navigation", True)
        debounce_time = float(input_config.get("whisplay_debounce_ms", 50)) / 1000.0
        double_click_time = float(input_config.get("whisplay_double_tap_ms", 300)) / 1000.0
        long_press_time = float(input_config.get("whisplay_long_hold_ms", 800)) / 1000.0

        if whisplay_device or simulate:
            from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter

            ptt_adapter = PTTInputAdapter(
                whisplay_device=whisplay_device,
                enable_navigation=enable_navigation,
                debounce_time=debounce_time,
                double_click_time=double_click_time,
                long_press_time=long_press_time,
                simulate=simulate,
            )
            manager.add_adapter(ptt_adapter)

            if enable_navigation:
                logger.info("  -> Added one-button Whisplay navigation")
                logger.info(
                    "  -> Gesture timings: %dms debounce, %dms double tap, %dms hold",
                    int(debounce_time * 1000),
                    int(double_click_time * 1000),
                    int(long_press_time * 1000),
                )
            else:
                logger.info("  -> Added PTT button input (press/release only)")
        else:
            logger.warning("  -> No Whisplay device available for PTT input")

        if input_config.get("enable_voice", False):
            logger.info("  -> Voice input requested but not yet implemented")

    elif adapter_name == "SimulationDisplayAdapter":
        logger.info("  Detected Simulation Display Adapter")
        from yoyopy.ui.input.adapters.keyboard import get_keyboard_adapter

        keyboard_adapter = get_keyboard_adapter()
        manager.add_adapter(keyboard_adapter)
        logger.info("  -> Added keyboard input (Enter, Esc, Arrow keys)")

        try:
            from yoyopy.ui.web_server import get_server

            server = get_server()

            def web_input_handler(action: str) -> None:
                """Handle input from web UI buttons."""
                action_map = {
                    "SELECT": InputAction.SELECT,
                    "BACK": InputAction.BACK,
                    "UP": InputAction.UP,
                    "DOWN": InputAction.DOWN,
                }

                if action in action_map:
                    manager.simulate_action(action_map[action])

            server.set_input_callback(web_input_handler)
            logger.info("  -> Added web button input (browser UI)")
        except Exception as exc:
            logger.warning(f"  -> Failed to connect web input: {exc}")

    else:
        logger.info(f"  Unknown display adapter: {adapter_name}")
        if simulate:
            logger.info("  -> Running in simulation mode (no input hardware)")
        else:
            logger.warning("  -> No input adapters available for this hardware")
            return None

    if not manager.adapters:
        logger.warning("No input adapters configured")
        return None

    capabilities = manager.get_capabilities()
    logger.info(f"  Input capabilities: {len(capabilities)} action(s)")
    logger.debug(f"    Actions: {[action.value for action in capabilities]}")
    logger.info(f"  Interaction profile: {manager.interaction_profile.value}")

    return manager


def get_input_info(display_adapter: object) -> Dict[str, Any]:
    """
    Get information about available input methods.

    Args:
        display_adapter: Display adapter instance

    Returns:
        Dict with input hardware information
    """
    adapter_name = display_adapter.__class__.__name__

    if adapter_name == "PimoroniDisplayAdapter":
        return {
            "type": "four_button",
            "hardware": "Pimoroni Display HAT Mini",
            "buttons": 4,
            "capabilities": [
                "SELECT (Button A)",
                "BACK (Button B)",
                "UP (Button X)",
                "DOWN (Button Y)",
                "HOME (Long press B)",
            ],
            "description": "4-button interface for menu navigation",
        }

    if adapter_name == "WhisplayDisplayAdapter":
        return {
            "type": "ptt_button",
            "hardware": "Whisplay HAT",
            "buttons": 1,
            "capabilities": [
                "ADVANCE (Single tap)",
                "SELECT (Double tap)",
                "BACK (Long hold)",
            ],
            "description": "Single-button carousel and list navigation",
        }

    return {
        "type": "unknown",
        "hardware": adapter_name,
        "buttons": 0,
        "capabilities": [],
        "description": "No input hardware detected",
    }
