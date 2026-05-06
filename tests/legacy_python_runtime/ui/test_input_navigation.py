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


class _TrackingInputManager(InputManager):
    """Record callback registration and clearing across screen navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.registration_calls: list[InputAction] = []
        self.clear_calls = 0

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None],
    ) -> None:
        self.registration_calls.append(action)
        super().on_action(action, callback)

    def clear_callbacks(self) -> None:
        self.clear_calls += 1
        super().clear_callbacks()


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


class _DynamicModeScreen(Screen):
    """Minimal screen double with mutable per-screen input mode flags."""

    def __init__(self, display: Display, context: AppContext) -> None:
        super().__init__(display, context, "DynamicMode")
        self.raw_ptt_passthrough = False
        self.simple_one_button_navigation = False

    def render(self) -> None:
        return None

    def wants_ptt_passthrough(self) -> bool:
        return self.raw_ptt_passthrough

    def prefers_simple_one_button_navigation(self) -> bool:
        return self.simple_one_button_navigation


class _ActionRecordingScreen(Screen):
    """Minimal screen double that records semantic actions and renders."""

    def __init__(self, display: Display) -> None:
        super().__init__(display, AppContext(), "ActionRecording")
        self.select_calls = 0
        self.render_calls = 0

    def on_select(self, data: Optional[Any] = None) -> None:
        self.select_calls += 1

    def render(self) -> None:
        self.render_calls += 1


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
    now_playing = NowPlayingScreen(display, context)
    home.render = lambda: None
    menu.render = lambda: None
    now_playing.render = lambda: None

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


def test_screen_manager_registers_semantic_dispatch_once() -> None:
    """Navigation should not clear and re-register semantic input callbacks."""
    display = Display(simulate=True)
    input_manager = _TrackingInputManager()
    screen_manager = ScreenManager(display, input_manager)
    first = _PassiveScreen(display, AppContext())
    second = _PassiveScreen(display, AppContext())
    first.render = lambda: None
    second.render = lambda: None

    screen_manager.register_screen("first", first)
    screen_manager.register_screen("second", second)

    try:
        assert input_manager.registration_calls == list(InputAction)

        screen_manager.replace_screen("first")
        screen_manager.push_screen("second")
        assert screen_manager.pop_screen() is True

        assert input_manager.registration_calls == list(InputAction)
        assert input_manager.clear_calls == 0
        assert all(len(input_manager.callbacks[action]) == 1 for action in InputAction)
    finally:
        display.cleanup()


def test_screen_manager_refreshes_input_modes_without_rebinding_callbacks() -> None:
    """Dynamic screen mode changes should only reconfigure adapters, not callbacks."""
    display = Display(simulate=True)
    input_manager = _TrackingInputManager()
    adapter = _ModeTrackingAdapter()
    input_manager.add_adapter(adapter)
    screen_manager = ScreenManager(display, input_manager)
    screen = _DynamicModeScreen(display, AppContext())
    screen_manager.register_screen("dynamic", screen)

    try:
        screen_manager.replace_screen("dynamic")
        assert adapter.raw_ptt_passthrough is False
        assert adapter.double_tap_select_enabled is True

        screen.raw_ptt_passthrough = True
        screen.simple_one_button_navigation = True
        screen_manager.refresh_current_screen_input_modes()

        assert adapter.raw_ptt_passthrough is True
        assert adapter.double_tap_select_enabled is False
        assert input_manager.registration_calls == list(InputAction)
        assert input_manager.clear_calls == 0
    finally:
        display.cleanup()


def test_screen_manager_reports_actual_action_and_visible_refresh() -> None:
    """Input latency should be sampled from the screen action, not only activity."""
    display = Display(simulate=True)
    input_manager = InputManager()
    handled_actions: list[str | None] = []
    visible_refreshes: list[float] = []

    def record_visible_refresh(*, refreshed_at: float) -> None:
        visible_refreshes.append(refreshed_at)

    screen_manager = ScreenManager(
        display,
        input_manager,
        on_action_handled=lambda action_name, handled_at: handled_actions.append(
            action_name
        ),
        on_visible_refresh=record_visible_refresh,
    )
    screen = _ActionRecordingScreen(display)
    screen_manager.register_screen("action", screen)

    try:
        screen_manager.replace_screen("action")
        handled_actions.clear()
        visible_refreshes.clear()

        input_manager.simulate_action(InputAction.SELECT)

        assert screen.select_calls == 1
        assert handled_actions == ["select"]
        assert len(visible_refreshes) == 1
        assert screen.render_calls >= 2
    finally:
        display.cleanup()


def test_screen_manager_skips_visible_refresh_metric_when_display_asleep() -> None:
    """A render while asleep should not consume the pending visible-refresh marker."""
    display = Display(simulate=True)
    input_manager = InputManager()
    visible_refreshes: list[float] = []

    def record_visible_refresh(*, refreshed_at: float) -> None:
        visible_refreshes.append(refreshed_at)

    screen_manager = ScreenManager(
        display,
        input_manager,
        on_visible_refresh=record_visible_refresh,
        is_screen_visible=lambda: False,
    )
    screen = _ActionRecordingScreen(display)
    screen_manager.register_screen("action", screen)

    try:
        screen_manager.replace_screen("action")
        visible_refreshes.clear()

        input_manager.simulate_action(InputAction.SELECT)

        assert screen.select_calls == 1
        assert visible_refreshes == []
        assert screen.render_calls >= 2
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
