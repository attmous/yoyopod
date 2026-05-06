#!/usr/bin/env python3
"""
Demo application for VoIP calling with the current YoYoPod UI stack.

Controls:
- `a`: Select, answer, or confirm
- `b`: Back, reject, or hang up
- `x`: Up or mute
- `y`: Down
"""

import sys
import time

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod_cli.config import ConfigManager
from yoyopod.voip import RegistrationState, VoIPConfig, VoIPManager
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputAction, get_input_manager
from yoyopod.ui.screens.manager import ScreenManager
from yoyopod.ui.screens.navigation.menu import MenuScreen
from yoyopod.ui.screens.voip.contact_list import ContactListScreen
from yoyopod.ui.screens.voip.in_call import InCallScreen
from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen
from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen
from yoyopod.ui.screens.voip.quick_call import CallScreen

ACTION_MAP = {
    "a": InputAction.SELECT,
    "b": InputAction.BACK,
    "x": InputAction.UP,
    "y": InputAction.DOWN,
}

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


def main() -> int:
    """Run VoIP demo."""
    logger.info("=" * 60)
    logger.info("YoYoPod VoIP Demo")
    logger.info("=" * 60)

    display = Display(simulate="--simulate" in sys.argv)
    input_manager = get_input_manager(display.get_adapter(), simulate=display.simulate)
    if input_manager is None:
        logger.error("No input manager available for the detected display adapter")
        return 1

    logger.info("Initializing display...")
    display.clear(display.COLOR_BLACK)
    display.text("Initializing VoIP...", 10, 100, color=display.COLOR_WHITE, font_size=16)
    display.update()

    context = AppContext()
    config_manager = ConfigManager(config_dir="config")
    voip_config = VoIPConfig.from_config_manager(config_manager)
    voip_manager = VoIPManager(voip_config, config_manager=config_manager)

    contacts = config_manager.get_contacts()
    logger.info(f"Loaded {len(contacts)} contacts")

    try:
        if not voip_manager.start():
            logger.error("Failed to start VoIP manager")
            return 1
    except Exception as exc:
        logger.error(f"Error starting VoIP: {exc}")
        return 1

    screen_manager = ScreenManager(display, input_manager)
    screen_manager.register_screen("menu", MenuScreen(display, context, items=["VoIP Status", "Call Contact"]))
    call_screen = CallScreen(display, context, voip_manager=voip_manager, config_manager=config_manager)
    contact_list_screen = ContactListScreen(
        display,
        context,
        voip_manager=voip_manager,
        config_manager=config_manager,
    )
    outgoing_call_screen = OutgoingCallScreen(display, context, voip_manager=voip_manager)
    incoming_call_screen = IncomingCallScreen(display, context, voip_manager=voip_manager)
    in_call_screen = InCallScreen(display, context, voip_manager=voip_manager)

    screen_manager.register_screen("call", call_screen)
    screen_manager.register_screen("contacts", contact_list_screen)
    screen_manager.register_screen("outgoing_call", outgoing_call_screen)
    screen_manager.register_screen("incoming_call", incoming_call_screen)
    screen_manager.register_screen("in_call", in_call_screen)
    screen_manager.push_screen("menu")

    def on_registration_change(state: RegistrationState) -> None:
        logger.info(f"Registration state changed: {state.value}")
        if screen_manager.current_screen is call_screen:
            call_screen.render()

    def on_incoming_call(caller_address: str, caller_name: str) -> None:
        logger.info(f"Incoming call from: {caller_name} ({caller_address})")
        incoming_call_screen.caller_address = caller_address
        incoming_call_screen.caller_name = caller_name
        incoming_call_screen.ring_animation_frame = 0
        if screen_manager.current_screen is not incoming_call_screen:
            screen_manager.push_screen("incoming_call")

    def on_call_state_change(state) -> None:
        logger.info(f"Call state changed: {state.value}")
        if state.value in {"connected", "streams_running"}:
            if screen_manager.current_screen is not in_call_screen:
                screen_manager.push_screen("in_call")
        elif state.value == "released":
            while screen_manager.current_screen in [in_call_screen, incoming_call_screen, outgoing_call_screen]:
                if not screen_manager.pop_screen():
                    break

    voip_manager.on_registration_change(on_registration_change)
    voip_manager.on_incoming_call(on_incoming_call)
    voip_manager.on_call_state_change(on_call_state_change)

    input_manager.start()

    logger.info("VoIP demo running")
    if display.simulate:
        logger.info("Simulation mode commands: a, b, x, y, quit")

    try:
        if display.simulate:
            while True:
                try:
                    cmd = input("> ").strip().lower()
                except EOFError:
                    break

                if cmd in {"quit", "q", "exit"}:
                    break
                if cmd == "help":
                    logger.info("Commands: a, b, x, y, quit")
                    continue

                action = ACTION_MAP.get(cmd)
                if action is None:
                    logger.warning(f"Unknown command: {cmd}")
                    continue

                input_manager.simulate_action(action)
        else:
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        voip_manager.stop()
        input_manager.stop()
        display.cleanup()
        logger.info("Demo ended")

    return 0


if __name__ == "__main__":
    sys.exit(main())
