#!/usr/bin/env python3
"""
Split-FSM runtime demo for YoyoPod.

This demo exercises the current music FSM and derived app runtime state.
"""

from __future__ import annotations

import sys
import time

from loguru import logger

from yoyopod.app_context import AppContext
from yoyopod.coordinators.registry import AppRuntimeState, CoordinatorRuntime
from yoyopod.fsm import CallFSM, CallInterruptionPolicy, MusicFSM
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputAction, get_input_manager
from yoyopod.ui.screens.manager import ScreenManager
from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
from yoyopod.ui.screens.navigation.home import HomeScreen
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
    """Run the split runtime demo."""
    logger.info("Starting YoyoPod runtime-state demo")
    logger.info("=" * 50)

    context = AppContext()
    demo_playlist = context.create_demo_playlist()
    context.set_playlist(demo_playlist)
    context.update_system_status(battery=85, signal=3, connected=True)
    logger.info(f"Demo playlist loaded: {len(demo_playlist.tracks)} tracks")

    display = Display(simulate="--simulate" in sys.argv)
    input_manager = get_input_manager(display.get_adapter(), simulate=display.simulate)
    if input_manager is None:
        logger.error("No input manager available for the detected display adapter")
        return 1

    screen_manager = ScreenManager(display)
    home_screen = HomeScreen(display, context)
    menu_screen = MenuScreen(display, context)
    now_playing_screen = NowPlayingScreen(display, context)

    screen_manager.register_screen("home", home_screen)
    screen_manager.register_screen("menu", menu_screen)
    screen_manager.register_screen("now_playing", now_playing_screen)

    runtime = CoordinatorRuntime(
        music_fsm=MusicFSM(),
        call_fsm=CallFSM(),
        call_interruption_policy=CallInterruptionPolicy(),
        screen_manager=screen_manager,
        power_manager=None,
        music_backend=None,
        config_manager=None,
        ui_state=AppRuntimeState.IDLE,
    )

    def log_runtime_state(trigger: str) -> None:
        state_change = runtime.sync_app_state(trigger)
        track = context.get_current_track()
        logger.info(
            "State: {} | Screen: {} | Track: {}",
            state_change.current_state.value,
            screen_manager.get_current_screen().name if screen_manager.get_current_screen() else "none",
            track.title if track else "None",
        )

    def show_home() -> None:
        runtime.set_ui_state(AppRuntimeState.IDLE, trigger="show_home")
        screen_manager.clear_stack()
        screen_manager.replace_screen("home")
        log_runtime_state("show_home")

    def show_menu(push: bool) -> None:
        runtime.set_ui_state(AppRuntimeState.MENU, trigger="show_menu")
        if push:
            screen_manager.push_screen("menu")
        else:
            screen_manager.replace_screen("menu")
        log_runtime_state("show_menu")

    def show_now_playing() -> None:
        screen_manager.push_screen("now_playing")
        log_runtime_state("show_now_playing")

    def start_playback() -> None:
        if context.play():
            runtime.music_fsm.transition("play")
            log_runtime_state("play")

    def toggle_playback() -> None:
        if runtime.music_fsm.state.value == "playing":
            context.pause()
            runtime.music_fsm.transition("pause")
        elif runtime.music_fsm.state.value == "paused":
            context.resume()
            runtime.music_fsm.transition("play")
        else:
            context.play()
            runtime.music_fsm.transition("play")
        log_runtime_state("toggle_playback")
        screen_manager.refresh_current_screen()

    def handle_select(_data=None) -> None:
        current_screen = screen_manager.get_current_screen()

        if current_screen == home_screen:
            show_menu(push=True)
            return

        if current_screen == menu_screen:
            selected = menu_screen.get_selected()
            if selected == "Settings":
                logger.info("Settings not implemented in this demo")
                return
            if selected == "Back":
                screen_manager.pop_screen()
                runtime.set_ui_state(AppRuntimeState.IDLE, trigger="menu_back")
                log_runtime_state("menu_back")
                return

            start_playback()
            show_now_playing()
            return

        if current_screen == now_playing_screen:
            toggle_playback()

    def handle_back(_data=None) -> None:
        current_screen = screen_manager.get_current_screen()

        if current_screen == menu_screen:
            screen_manager.pop_screen()
            runtime.set_ui_state(AppRuntimeState.IDLE, trigger="back_to_home")
            log_runtime_state("back_to_home")
        elif current_screen == now_playing_screen:
            screen_manager.pop_screen()
            runtime.set_ui_state(AppRuntimeState.MENU, trigger="back_to_menu")
            log_runtime_state("back_to_menu")

    def handle_up(_data=None) -> None:
        current_screen = screen_manager.get_current_screen()

        if current_screen == menu_screen:
            menu_screen.select_previous()
            screen_manager.refresh_current_screen()
        elif current_screen == now_playing_screen:
            previous_track = context.previous_track()
            logger.info(f"Previous track: {previous_track.title if previous_track else 'None'}")
            screen_manager.refresh_current_screen()
            log_runtime_state("previous_track")

    def handle_down(_data=None) -> None:
        current_screen = screen_manager.get_current_screen()

        if current_screen == menu_screen:
            menu_screen.select_next()
            screen_manager.refresh_current_screen()
        elif current_screen == now_playing_screen:
            next_track = context.next_track()
            logger.info(f"Next track: {next_track.title if next_track else 'None'}")
            screen_manager.refresh_current_screen()
            log_runtime_state("next_track")

    input_manager.on_action(InputAction.SELECT, handle_select)
    input_manager.on_action(InputAction.BACK, handle_back)
    input_manager.on_action(InputAction.UP, handle_up)
    input_manager.on_action(InputAction.DOWN, handle_down)

    show_home()
    input_manager.start()

    try:
        if display.simulate:
            logger.info("Simulation mode commands: a, b, x, y, state, quit")
            while True:
                try:
                    cmd = input("> ").strip().lower()
                except EOFError:
                    break

                if cmd in {"quit", "q", "exit"}:
                    break
                if cmd == "state":
                    log_runtime_state("inspect")
                    logger.info(f"Playing: {context.media.playback.is_playing}")
                    continue
                if cmd == "help":
                    logger.info("Commands: a, b, x, y, state, quit")
                    continue

                action = ACTION_MAP.get(cmd)
                if action is None:
                    logger.warning(f"Unknown command: {cmd}")
                    continue

                input_manager.simulate_action(action)
        else:
            logger.info("Demo running on hardware. Press Ctrl+C to exit.")
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    finally:
        input_manager.stop()
        display.cleanup()
        logger.info(f"Final state: {runtime.get_state_name()}")
        logger.info("Demo stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
