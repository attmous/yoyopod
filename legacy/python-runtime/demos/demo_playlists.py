#!/usr/bin/env python3
"""
Demo application for playlist browsing with the current YoYoPod UI stack.

Controls:
- `a`: Select or load playlist
- `b`: Back
- `x`: Up
- `y`: Down
"""

import sys
import time

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod.audio.mopidy_client import MopidyClient
from yoyopod_cli.pi.support.display import Display
from yoyopod_cli.pi.support.input import InputAction, get_input_manager
from yoyopod.ui.screens.manager import ScreenManager
from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
from yoyopod.ui.screens.music.playlist import PlaylistScreen
from yoyopod.ui.screens.navigation.menu import MenuScreen

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
    """Run playlist browsing demo."""
    logger.info("=" * 60)
    logger.info("YoYoPod Playlist Browser Demo")
    logger.info("=" * 60)

    display = Display(simulate="--simulate" in sys.argv)
    input_manager = get_input_manager(display.get_adapter(), simulate=display.simulate)
    if input_manager is None:
        logger.error("No input manager available for the detected display adapter")
        return 1

    logger.info("Initializing display...")
    display.clear(display.COLOR_BLACK)
    display.text("Connecting to Mopidy...", 10, 100, color=display.COLOR_WHITE, font_size=16)
    display.update()

    logger.info("Connecting to Mopidy server...")
    mopidy = MopidyClient(host="localhost", port=6680)
    try:
        if not mopidy.connect():
            logger.error("Failed to connect to Mopidy server on localhost:6680")
            return 1
    except Exception as exc:
        logger.error(f"Error connecting to Mopidy: {exc}")
        return 1

    context = AppContext()

    screen_manager = ScreenManager(display, input_manager)
    screen_manager.register_screen(
        "menu",
        MenuScreen(display, context, items=["Browse Playlists", "Now Playing", "Back"]),
    )
    screen_manager.register_screen("playlists", PlaylistScreen(display, context, mopidy_client=mopidy))
    now_playing_screen = NowPlayingScreen(display, context, mopidy_client=mopidy)
    screen_manager.register_screen("now_playing", now_playing_screen)
    screen_manager.push_screen("menu")

    input_manager.start()
    mopidy.start_polling()

    def on_track_change(track) -> None:
        logger.info(f"Track changed: {track.name if track else 'None'}")
        if screen_manager.current_screen is now_playing_screen:
            now_playing_screen.render()

    mopidy.on_track_change(on_track_change)

    logger.info("Playlist browser demo running")
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
        mopidy.stop_polling()
        mopidy.cleanup()
        input_manager.stop()
        display.cleanup()
        logger.info("Demo ended")

    return 0


if __name__ == "__main__":
    sys.exit(main())
