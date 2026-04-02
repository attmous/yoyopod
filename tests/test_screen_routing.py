#!/usr/bin/env python3
"""Routing-focused tests for the declarative screen navigation layer."""

from __future__ import annotations

import pytest

from yoyopy.app_context import AppContext
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputAction, InputManager
from yoyopy.ui.screens import HomeScreen, MenuScreen, NavigationRequest, Screen, ScreenManager, ScreenRouter


class RoutableStubScreen(Screen):
    """Minimal screen double that can emit simple route requests."""

    def __init__(self, display: Display, context: AppContext | None = None) -> None:
        super().__init__(display, context, "RoutableStub")

    def render(self) -> None:
        """No-op render used by routing tests."""

    def on_back(self, data=None) -> None:
        """Request a standard back route."""
        self.request_route("back")


@pytest.fixture
def display() -> Display:
    """Create a simulation display and clean it up after the test."""
    test_display = Display(simulate=True)
    try:
        yield test_display
    finally:
        test_display.cleanup()


def test_screen_router_covers_live_menu_labels() -> None:
    """The router should cover the menu labels used by the app and demos."""
    router = ScreenRouter()
    expected_routes = {
        "Back": NavigationRequest.pop(),
        "Load Playlist": NavigationRequest.push("playlists"),
        "Music": NavigationRequest.push("now_playing"),
        "Now Playing": NavigationRequest.push("now_playing"),
        "Browse Playlists": NavigationRequest.push("playlists"),
        "Playlists": NavigationRequest.push("playlists"),
        "VoIP Status": NavigationRequest.push("call"),
        "Call Contact": NavigationRequest.push("contacts"),
        "Contacts": NavigationRequest.push("contacts"),
    }

    for label, expected_request in expected_routes.items():
        assert router.resolve("menu", "select", payload=label) == expected_request


def test_screen_manager_routes_menu_labels_through_stack(display: Display) -> None:
    """Menu labels should resolve through the router and preserve stack navigation."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    home = HomeScreen(display, context)
    menu = MenuScreen(display, context, items=["Load Playlist", "Back"])
    playlists = RoutableStubScreen(display, context)

    screen_manager.register_screen("home", home)
    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("playlists", playlists)

    screen_manager.replace_screen("home")
    assert screen_manager.current_screen is home

    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is menu

    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is playlists

    input_manager.simulate_action(InputAction.BACK)
    assert screen_manager.current_screen is menu

    menu.selected_index = 1
    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is home
