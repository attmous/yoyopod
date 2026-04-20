#!/usr/bin/env python3
"""
Interactive YoyoPod UI demo using the current HAL-based stack.

Controls:
- `a`: Select
- `b`: Back
- `x`: Up
- `y`: Down
"""

import sys
import time

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputAction, get_input_manager
from yoyopod.ui.screens import HomeScreen, MenuScreen, NowPlayingScreen, ScreenManager

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


def build_context() -> AppContext:
    """Create a demo context with an active playlist."""
    context = AppContext()
    playlist = context.create_demo_playlist()
    context.set_playlist(playlist)
    context.update_system_status(battery=85, signal=3, connected=True)
    context.play()
    context.media.playback.position = 54.0
    return context


def main() -> int:
    """Run the interactive demo."""
    logger.info("Starting YoyoPod interactive demo")
    logger.info("=" * 50)
    logger.info("Controls: A=select, B=back, X=up, Y=down")
    logger.info("=" * 50)

    display = Display(simulate="--simulate" in sys.argv)
    input_manager = get_input_manager(display.get_adapter(), simulate=display.simulate)
    if input_manager is None:
        logger.error("No input manager available for the detected display adapter")
        return 1

    context = build_context()

    screen_manager = ScreenManager(display, input_manager)
    screen_manager.register_screen("home", HomeScreen(display, context))
    screen_manager.register_screen("menu", MenuScreen(display, context))
    screen_manager.register_screen("now_playing", NowPlayingScreen(display, context))
    screen_manager.replace_screen("home")

    input_manager.start()

    try:
        if display.simulate:
            logger.info("Simulation mode commands: a, b, x, y, quit")
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
            logger.info("Interactive demo running on hardware. Press Ctrl+C to exit.")
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    finally:
        input_manager.stop()
        display.cleanup()
        logger.info("Demo stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
