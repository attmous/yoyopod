"""Focused tests for the VoIP call hub screen."""

from __future__ import annotations

import pytest

from yoyopy.app_context import AppContext
from yoyopy.config import Contact
from yoyopy.ui.display import Display
from yoyopy.ui.screens import CallScreen, NavigationRequest


class FakeConfigManager:
    """Minimal contact source for call-screen tests."""

    def __init__(self, contacts: list[Contact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[Contact]:
        return list(self._contacts)


class FakeVoIPManager:
    """Minimal VoIP manager double for call-screen actions."""

    def __init__(
        self,
        *,
        running: bool = True,
        registered: bool = True,
        registration_state: str = "ok",
        call_state: str = "idle",
        make_call_result: bool = True,
        caller_name: str = "Unknown",
        caller_address: str = "",
    ) -> None:
        self.status = {
            "running": running,
            "registered": registered,
            "registration_state": registration_state,
            "call_state": call_state,
            "sip_identity": "sip:test@example.com",
        }
        self.make_call_result = make_call_result
        self.make_calls: list[tuple[str, str | None]] = []
        self.caller_name = caller_name
        self.caller_address = caller_address

    def get_status(self) -> dict:
        return dict(self.status)

    def get_caller_info(self) -> dict:
        return {
            "display_name": self.caller_name,
            "address": self.caller_address,
        }

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        self.make_calls.append((sip_address, contact_name))
        return self.make_call_result


@pytest.fixture
def display() -> Display:
    """Create a simulation display and clean it up after the test."""
    test_display = Display(simulate=True)
    try:
        yield test_display
    finally:
        test_display.cleanup()


def test_call_screen_prefers_favorites_and_adds_contacts_shortcut(display: Display) -> None:
    """The VoIP hub should highlight favorite quick calls before the full list."""
    contacts = [
        Contact(name="Bob", sip_address="sip:bob@example.com", favorite=False),
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True),
        Contact(name="Carol", sip_address="sip:carol@example.com", favorite=True),
    ]
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=FakeVoIPManager(),
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()

    assert [target.title for target in screen.quick_targets] == [
        "Alice",
        "Carol",
        "All Contacts",
    ]


def test_call_screen_falls_back_to_all_contacts_when_no_favorites(display: Display) -> None:
    """The VoIP hub should still offer quick calls when favorites are not configured."""
    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=False),
        Contact(name="Bob", sip_address="sip:bob@example.com", favorite=False),
    ]
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=FakeVoIPManager(),
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()

    assert [target.title for target in screen.quick_targets] == ["Alice", "Bob"]


def test_call_screen_select_calls_selected_quick_contact(display: Display) -> None:
    """Selecting a ready quick contact should place the call and route to outgoing."""
    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True),
    ]
    voip_manager = FakeVoIPManager(running=True, registered=True)
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=voip_manager,
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.render()
    screen.on_select()

    assert voip_manager.make_calls == [("sip:alice@example.com", "Alice")]
    assert screen.consume_navigation_request() == NavigationRequest.route("call_started")


def test_call_screen_select_opens_contacts_when_voip_is_not_ready(display: Display) -> None:
    """Selecting from the VoIP hub while SIP is down should still open the contact list."""
    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True),
    ]
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=FakeVoIPManager(running=False, registered=False, registration_state="failed"),
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("browse_contacts")


def test_call_screen_browse_target_routes_to_full_contacts(display: Display) -> None:
    """The explicit All Contacts shortcut should route to the full contact list."""
    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True),
        Contact(name="Bob", sip_address="sip:bob@example.com", favorite=False),
    ]
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=FakeVoIPManager(),
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.selected_index = len(screen.quick_targets) - 1
    screen.render()
    screen.on_select()

    assert screen.quick_targets[-1].title == "All Contacts"
    assert screen.consume_navigation_request() == NavigationRequest.route("browse_contacts")


def test_call_screen_render_smoke_includes_active_call_context(display: Display) -> None:
    """Rendering should stay stable when the VoIP hub reflects an active call state."""
    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True),
    ]
    voip_manager = FakeVoIPManager(
        running=True,
        registered=True,
        call_state="connected",
        caller_name="Alice",
        caller_address="sip:alice@example.com",
    )
    screen = CallScreen(
        display,
        AppContext(),
        voip_manager=voip_manager,
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.render()

    assert screen._call_context_lines(voip_manager.get_status()) == (
        "Call connected",
        "Alice",
    )
