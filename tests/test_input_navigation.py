#!/usr/bin/env python3
"""Integration-style test for semantic input navigation in simulation mode."""

from yoyopy.app_context import AppContext
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputAction, InputManager
from yoyopy.ui.screens import HomeScreen, MenuScreen, NowPlayingScreen, ScreenManager


def test_semantic_input_navigation() -> None:
    """Semantic actions should drive the registered screens correctly."""
    display = Display(simulate=True)
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    context = AppContext()
    playlist = context.create_demo_playlist()
    context.set_playlist(playlist)

    home = HomeScreen(display, context)
    menu = MenuScreen(display, context)
    now_playing = NowPlayingScreen(display, context)

    screen_manager.register_screen("home", home)
    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("now_playing", now_playing)

    try:
        screen_manager.replace_screen("home")
        assert screen_manager.current_screen is home

        input_manager.simulate_action(InputAction.SELECT)
        assert screen_manager.current_screen is menu

        initial_selection = menu.selected_index
        input_manager.simulate_action(InputAction.DOWN)
        assert menu.selected_index != initial_selection

        input_manager.simulate_action(InputAction.UP)
        assert menu.selected_index == initial_selection

        input_manager.simulate_action(InputAction.SELECT)
        assert screen_manager.current_screen is now_playing

        assert not context.playback.is_playing
        input_manager.simulate_action(InputAction.SELECT)
        assert context.playback.is_playing

        input_manager.simulate_action(InputAction.SELECT)
        assert not context.playback.is_playing
        assert context.playback.is_paused

        input_manager.simulate_action(InputAction.BACK)
        assert screen_manager.current_screen is menu

        input_manager.simulate_action(InputAction.BACK)
        assert screen_manager.current_screen is home
    finally:
        display.cleanup()
