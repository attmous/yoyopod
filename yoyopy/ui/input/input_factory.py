"""
Input factory for auto-detecting and creating input adapters.

Automatically selects the appropriate input adapter based on
hardware detection and configuration.
"""

from typing import Dict, Any, Optional
from loguru import logger

from yoyopy.ui.input.input_manager import InputManager


def get_input_manager(
    display_adapter: object,
    config: Optional[Dict[str, Any]] = None,
    simulate: bool = False
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

    Example:
        from yoyopy.ui.display import Display
        from yoyopy.ui.input import get_input_manager

        display = Display(hardware="auto")
        input_manager = get_input_manager(
            display.get_adapter(),
            config={'input': {'enable_voice': False}}
        )

        if input_manager:
            input_manager.start()
    """
    config = config or {}
    input_config = config.get('input', {})

    # Create InputManager
    manager = InputManager()

    # Determine hardware type from display adapter
    adapter_name = display_adapter.__class__.__name__

    logger.info("Creating input manager...")
    logger.debug(f"  Display adapter: {adapter_name}")

    # ===== Pimoroni Display HAT Mini (4 buttons) =====
    if adapter_name == "PimoroniDisplayAdapter":
        logger.info("  Detected Pimoroni Display HAT Mini")

        # Get display device for button access
        display_device = getattr(display_adapter, 'device', None)

        if display_device or simulate:
            # Create 4-button adapter
            from yoyopy.ui.input.adapters.four_button import FourButtonInputAdapter

            button_adapter = FourButtonInputAdapter(
                display_device=display_device,
                simulate=simulate
            )
            manager.add_adapter(button_adapter)
            logger.info("  → Added 4-button input (A, B, X, Y)")
        else:
            logger.warning("  → No display device available for button input")

    # ===== Whisplay HAT (PTT button) =====
    elif adapter_name == "WhisplayDisplayAdapter":
        logger.info("  Detected Whisplay HAT")

        # Get Whisplay device for button access
        whisplay_device = getattr(display_adapter, 'device', None)

        # Check if navigation via PTT button is enabled
        enable_navigation = input_config.get('ptt_navigation', True)

        if whisplay_device or simulate:
            # Create PTT button adapter
            from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter

            ptt_adapter = PTTInputAdapter(
                whisplay_device=whisplay_device,
                enable_navigation=enable_navigation,
                simulate=simulate
            )
            manager.add_adapter(ptt_adapter)

            if enable_navigation:
                logger.info("  → Added PTT button input (press/release + navigation)")
            else:
                logger.info("  → Added PTT button input (press/release only)")
        else:
            logger.warning("  → No Whisplay device available for PTT input")

        # Optional: Add voice input for Whisplay (future)
        if input_config.get('enable_voice', False):
            logger.info("  → Voice input requested but not yet implemented")
            # TODO: Add VoiceInputAdapter when implemented

    # ===== Simulation Display Adapter (keyboard + web input) =====
    elif adapter_name == "SimulationDisplayAdapter":
        logger.info("  Detected Simulation Display Adapter")

        # Add keyboard input adapter
        from yoyopy.ui.input.adapters.keyboard import get_keyboard_adapter

        keyboard_adapter = get_keyboard_adapter()
        manager.add_adapter(keyboard_adapter)
        logger.info("  → Added keyboard input (Enter, Esc, Arrow keys)")

        # Connect web server input to keyboard adapter (reuse same callbacks)
        try:
            from yoyopy.ui.web_server import get_server
            server = get_server()

            def web_input_handler(action: str):
                """Handle input from web UI buttons."""
                from yoyopy.ui.input.input_hal import InputAction

                # Map action string to InputAction
                action_map = {
                    'SELECT': InputAction.SELECT,
                    'BACK': InputAction.BACK,
                    'UP': InputAction.UP,
                    'DOWN': InputAction.DOWN
                }

                if action in action_map:
                    # Simulate the action through the manager
                    manager.simulate_action(action_map[action])

            server.set_input_callback(web_input_handler)
            logger.info("  → Added web button input (browser UI)")

        except Exception as e:
            logger.warning(f"  → Failed to connect web input: {e}")

    # ===== Simulation mode or unknown hardware =====
    else:
        logger.info(f"  Unknown display adapter: {adapter_name}")
        if simulate:
            logger.info("  → Running in simulation mode (no input hardware)")
        else:
            logger.warning("  → No input adapters available for this hardware")
            return None

    # Check if any adapters were added
    if not manager.adapters:
        logger.warning("No input adapters configured")
        return None

    # Log capabilities
    capabilities = manager.get_capabilities()
    logger.info(f"  Input capabilities: {len(capabilities)} action(s)")
    logger.debug(f"    Actions: {[a.value for a in capabilities]}")

    return manager


def get_input_info(display_adapter: object) -> Dict[str, Any]:
    """
    Get information about available input methods.

    Args:
        display_adapter: Display adapter instance

    Returns:
        Dict with input hardware information

    Example:
        info = get_input_info(display.get_adapter())
        print(f"Input type: {info['type']}")
        print(f"Capabilities: {info['capabilities']}")
    """
    adapter_name = display_adapter.__class__.__name__

    if adapter_name == "PimoroniDisplayAdapter":
        return {
            'type': 'four_button',
            'hardware': 'Pimoroni Display HAT Mini',
            'buttons': 4,
            'capabilities': [
                'SELECT (Button A)',
                'BACK (Button B)',
                'UP (Button X)',
                'DOWN (Button Y)',
                'HOME (Long press B)',
            ],
            'description': '4-button interface for menu navigation'
        }

    elif adapter_name == "WhisplayDisplayAdapter":
        return {
            'type': 'ptt_button',
            'hardware': 'Whisplay HAT',
            'buttons': 1,
            'capabilities': [
                'PTT_PRESS (Button press)',
                'PTT_RELEASE (Button release)',
                'SELECT (Single click)',
                'BACK (Double click)',
            ],
            'description': 'PTT button with voice input support'
        }

    else:
        return {
            'type': 'unknown',
            'hardware': adapter_name,
            'buttons': 0,
            'capabilities': [],
            'description': 'No input hardware detected'
        }
