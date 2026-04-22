#!/usr/bin/env python3
"""Integration-style test for semantic input navigation in simulation mode."""

from typing import Any, Callable, Optional

from yoyopod.core import AppContext
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputAction, InputManager
from yoyopod.ui.input.hal import InputHAL
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.manager import ScreenManager
from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
from yoyopod.ui.screens.music.now_playing import build_now_playing_actions
from yoyopod.ui.screens.navigation.home import HomeScreen
from yoyopod.ui.screens.navigation.menu import MenuScreen


class _ModeTrackingAdapter(InputHAL):
    """Record screen-manager input mode changes without real hardware."""

    def __init__(self) -> None:
        self.callbacks: dict[InputAction, list[Callable[[Optional[Any]], None]]] = {}
        self.raw_ptt_passthrough = False
        self.double_tap_select_enabled = True

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None],
    ) -> None:
        self.callbacks.setdefault(action, []).append(callback)

    def clear_callbacks(self) -> None:
        self.callbacks.clear()

    def get_capabilities(self) -> list[InputAction]:
        return [InputAction.ADVANCE, InputAction.BACK]

    def set_raw_ptt_passthrough(self, enabled: bool) -> None:
        self.raw_ptt_passthrough = bool(enabled)

    def set_double_tap_select_enabled(self, enabled: bool) -> None:
        self.double_tap_select_enabled = bool(enabled)


class _SimpleSetupScreen(Screen):
    """Minimal screen double that requests simple one-button navigation."""

    def render(self) -> None:
        return None

    def prefers_simple_one_button_navigation(self) -> bool:
        return True


class _PassiveScreen(Screen):
    """Minimal screen double that relies on the base semantic no-op handlers."""

    def render(self) -> None:
        return None


def test_semantic_input_navigation() -> None:
    """Semantic actions should drive the registered screens correctly."""
    display = Display(simulate=True)
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    context = AppContext()
    playlist = context.create_demo_playlist()
    context.set_playlist(playlist)

    home = HomeScreen(display, context)
    menu = MenuScreen(display, context, items=["Now Playing", "Back"])
    now_playing = NowPlayingScreen(
        display,
        context,
        actions=build_now_playing_actions(
            toggle_playback_action=context.toggle_playback,
            previous_track_action=context.previous_track,
            next_track_action=context.next_track,
        ),
    )

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

        assert not context.media.playback.is_playing
        input_manager.simulate_action(InputAction.SELECT)
        assert context.media.playback.is_playing

        input_manager.simulate_action(InputAction.SELECT)
        assert not context.media.playback.is_playing
        assert context.media.playback.is_paused

        input_manager.simulate_action(InputAction.BACK)
        assert screen_manager.current_screen is menu

        input_manager.simulate_action(InputAction.BACK)
        assert screen_manager.current_screen is home
    finally:
        display.cleanup()


def test_screen_manager_configures_simple_one_button_navigation() -> None:
    """ScreenManager should disable double-tap select for screens that request it."""
    display = Display(simulate=True)
    input_manager = InputManager()
    adapter = _ModeTrackingAdapter()
    input_manager.add_adapter(adapter)
    screen_manager = ScreenManager(display, input_manager)
    screen_manager.register_screen("simple", _SimpleSetupScreen(display, AppContext()))

    try:
        screen_manager.replace_screen("simple")
        assert adapter.raw_ptt_passthrough is False
        assert adapter.double_tap_select_enabled is False
    finally:
        display.cleanup()


def test_screen_base_requires_semantic_handlers_only() -> None:
    """The base Screen contract should not expose legacy button-named handlers."""
    display = Display(simulate=True)
    screen = _PassiveScreen(display, AppContext())

    try:
        assert not hasattr(screen, "on_button_a")
        assert not hasattr(screen, "on_button_b")
        assert not hasattr(screen, "on_button_x")
        assert not hasattr(screen, "on_button_y")

        screen.handle_action(InputAction.SELECT)
        screen.handle_action(InputAction.BACK)
        screen.handle_action(InputAction.UP)
        screen.handle_action(InputAction.DOWN)
    finally:
        display.cleanup()
