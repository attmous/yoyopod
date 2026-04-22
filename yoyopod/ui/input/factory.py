"""
Input factory for auto-detecting and creating input adapters.

Automatically selects the appropriate input adapter based on
hardware detection and configuration.
"""

from typing import Any, Dict, Optional

from loguru import logger

from yoyopod.config.models import AppInputConfig
from yoyopod.ui.input.hal import InputAction, InteractionProfile
from yoyopod.ui.input.manager import InputManager


def _get_display_type(display_adapter: object) -> str:
    """Return the typed display identity used by the factories."""

    display_type = getattr(display_adapter, "DISPLAY_TYPE", None)
    if isinstance(display_type, str) and display_type.strip():
        return display_type.strip().lower()

    adapter_name = display_adapter.__class__.__name__
    if adapter_name == "WhisplayDisplayAdapter":
        return "whisplay"
    return adapter_name.lower()


def _get_simulated_hardware(display_adapter: object) -> str | None:
    """Return the hardware profile mirrored by a simulation adapter, if any."""

    simulated_hardware = getattr(display_adapter, "SIMULATED_HARDWARE", None)
    if not isinstance(simulated_hardware, str) or not simulated_hardware.strip():
        return None
    return simulated_hardware.strip().lower()


def get_input_manager(
    display_adapter: object,
    config: Optional[Dict[str, Any]] = None,
    *,
    input_settings: AppInputConfig | None = None,
    simulate: bool = False,
) -> Optional[InputManager]:
    """
    Create input manager with appropriate adapters based on hardware.

    Automatically detects the display hardware type and creates matching
    input adapters. Can also add voice input or other adapters based on config.

    Args:
        display_adapter: Display adapter instance (to determine hardware type)
        config: Legacy configuration dict with input settings (optional)
        input_settings: Typed input settings from the canonical app config
        simulate: Run in simulation mode (no hardware)

    Returns:
        Configured InputManager instance, or None if no input available
    """
    config = config or {}
    input_config = config.get("input", {})
    if not isinstance(input_config, dict):
        input_config = {}

    manager = InputManager(interaction_profile=InteractionProfile.STANDARD)
    adapter_name = display_adapter.__class__.__name__
    display_type = _get_display_type(display_adapter)

    logger.info("Creating input manager...")
    logger.debug(f"  Display adapter: {adapter_name}")
    logger.debug(f"  Display type: {display_type}")

    if display_type == "pimoroni":
        logger.info("  Detected Pimoroni Display HAT Mini")
        display_device = getattr(display_adapter, "device", None)
        gpio_input_config = (
            input_settings.pimoroni_gpio
            if input_settings is not None
            else input_config.get("pimoroni_gpio", {})
        )

        # Try Pi-native displayhatmini button reading first
        _has_displayhatmini = False
        if display_device or simulate:
            try:
                if not simulate:
                    from displayhatmini import DisplayHATMini  # noqa: F401
                from yoyopod.ui.input.adapters.four_button import FourButtonInputAdapter

                button_adapter = FourButtonInputAdapter(
                    display_device=display_device,
                    simulate=simulate,
                )
                manager.add_adapter(button_adapter)
                logger.info("  -> Added 4-button input (A, B, X, Y) via displayhatmini")
                _has_displayhatmini = True
            except ImportError:
                pass

        # Fallback: gpiod-based buttons
        if not _has_displayhatmini and gpio_input_config:
            from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

            button_adapter = GpiodButtonAdapter(
                pin_config=gpio_input_config,
                simulate=simulate,
            )
            manager.add_adapter(button_adapter)
            logger.info("  -> Added 4-button input (A, B, X, Y) via gpiod")
        elif not _has_displayhatmini:
            logger.warning("  -> No displayhatmini or GPIO config for button input")

    elif display_type == "whisplay":
        logger.info("  Detected Whisplay HAT")
        whisplay_device = getattr(display_adapter, "device", None)
        enable_navigation = (
            input_settings.ptt_navigation
            if input_settings is not None
            else input_config.get("ptt_navigation", True)
        )
        if enable_navigation:
            manager.set_interaction_profile(InteractionProfile.ONE_BUTTON)
        else:
            logger.warning(
                "  -> Whisplay raw PTT mode is experimental; keeping standard interaction profile",
            )
        debounce_time = float(
            input_settings.whisplay_debounce_ms
            if input_settings is not None
            else input_config.get("whisplay_debounce_ms", 50)
        ) / 1000.0
        double_click_time = float(
            input_settings.whisplay_double_tap_ms
            if input_settings is not None
            else input_config.get("whisplay_double_tap_ms", 300)
        ) / 1000.0
        long_press_time = float(
            input_settings.whisplay_long_hold_ms
            if input_settings is not None
            else input_config.get("whisplay_long_hold_ms", 800)
        ) / 1000.0
        adapter_simulate = bool(simulate or display_type == "simulation" or whisplay_device is None)

        if whisplay_device or adapter_simulate:
            from yoyopod.ui.input.adapters.ptt_button import PTTInputAdapter

            ptt_adapter = PTTInputAdapter(
                whisplay_device=whisplay_device,
                enable_navigation=enable_navigation,
                debounce_time=debounce_time,
                double_click_time=double_click_time,
                long_press_time=long_press_time,
                simulate=adapter_simulate,
            )
            manager.add_adapter(ptt_adapter)

            if enable_navigation:
                logger.info("  -> Added one-button Whisplay navigation")
                logger.info(
                    "  -> Gesture timings: {}ms debounce, {}ms double tap, {}ms hold",
                    int(debounce_time * 1000),
                    int(double_click_time * 1000),
                    int(long_press_time * 1000),
                )
            else:
                logger.info(
                    "  -> Added experimental raw PTT input (press/release only)",
                )
        else:
            logger.warning("  -> No Whisplay device available for PTT input")

        if simulate:
            try:
                from yoyopod.ui.display.adapters.simulation_web.server import get_server

                server = get_server()

                def web_input_handler(action: str) -> None:
                    """Handle browser button input while simulating the Whisplay profile."""
                    if enable_navigation:
                        action_map = {
                            "UP": InputAction.ADVANCE,
                            "DOWN": InputAction.ADVANCE,
                            "SELECT": InputAction.SELECT,
                            "BACK": InputAction.BACK,
                        }
                    else:
                        action_map = {
                            "SELECT": InputAction.PTT_PRESS,
                            "BACK": InputAction.PTT_RELEASE,
                        }

                    mapped_action = action_map.get(action)
                    if mapped_action is not None:
                        manager.simulate_action(mapped_action)

                server.set_input_callback(web_input_handler)
                logger.info("  -> Added web button input (browser UI)")
            except Exception as exc:
                logger.warning(f"  -> Failed to connect web input: {exc}")

        if input_config.get("enable_voice", False):
            logger.info("  -> Voice input requested but not yet implemented")

    elif display_type == "simulation":
        simulated_hardware = _get_simulated_hardware(display_adapter)
        if simulated_hardware:
            logger.info(
                "  Detected simulation display with {} output profile",
                simulated_hardware,
            )
        else:
            logger.info("  Detected simulation display")

        from yoyopod.ui.input.adapters.keyboard import get_keyboard_adapter

        keyboard_adapter = get_keyboard_adapter()
        manager.add_adapter(keyboard_adapter)
        logger.info("  -> Added keyboard input (Enter, Esc, Arrow keys)")

        try:
            from yoyopod.ui.display.adapters.simulation_web.server import get_server

            server = get_server()

            def web_input_handler(action: str) -> None:
                """Handle input from the simulation web UI buttons."""
                action_map = {
                    "SELECT": InputAction.SELECT,
                    "BACK": InputAction.BACK,
                    "UP": InputAction.UP,
                    "DOWN": InputAction.DOWN,
                }

                mapped_action = action_map.get(action)
                if mapped_action is not None:
                    manager.simulate_action(mapped_action)

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
    display_type = _get_display_type(display_adapter)
    simulated_hardware = _get_simulated_hardware(display_adapter)

    if display_type == "pimoroni":
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

    if display_type == "whisplay":
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

    if display_type == "simulation" and simulated_hardware == "whisplay":
        return {
            "type": "keyboard",
            "hardware": "Simulation (Whisplay display profile)",
            "buttons": 4,
            "capabilities": [
                "SELECT (Enter / browser select)",
                "BACK (Esc / browser back)",
                "UP (Arrow Up / browser up)",
                "DOWN (Arrow Down / browser down)",
            ],
            "description": "Whisplay-sized simulation with standard keyboard/web input",
        }

    return {
        "type": "unknown",
        "hardware": adapter_name,
        "buttons": 0,
        "capabilities": [],
        "description": "No input hardware detected",
    }
