"""Focused tests for the Whisplay-native one-button UI flow."""

from __future__ import annotations

import pytest

from yoyopy.app_context import AppContext
from yoyopy.ui.display import Display
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import (
    CallScreen,
    ContactListScreen,
    HubScreen,
    InCallScreen,
    IncomingCallScreen,
    NavigationRequest,
    NowPlayingScreen,
    OutgoingCallScreen,
    PlaylistScreen,
)


class FakeTrack:
    """Minimal Mopidy track double."""

    def __init__(self, name: str = "Track", artist: str = "Artist") -> None:
        self.name = name
        self._artist = artist
        self.length = 120000

    def get_artist_string(self) -> str:
        return self._artist


class FakePlaylist:
    """Minimal Mopidy playlist double."""

    def __init__(self, name: str, uri: str) -> None:
        self.name = name
        self.uri = uri
        self.track_count = 0


class FakeMopidyClient:
    """Minimal Mopidy double for one-button screen tests."""

    def __init__(self) -> None:
        self.is_connected = True
        self.playback_state = "stopped"
        self.track = FakeTrack()
        self.next_track_calls = 0
        self.play_calls = 0
        self.pause_calls = 0
        self.playlists = [
            FakePlaylist("Alpha", "playlist:alpha"),
            FakePlaylist("Beta", "playlist:beta"),
        ]
        self.loaded_playlists: list[str] = []

    def get_current_track(self) -> FakeTrack | None:
        return self.track

    def get_playback_state(self) -> str:
        return self.playback_state

    def get_time_position(self) -> int:
        return 0

    def next_track(self) -> bool:
        self.next_track_calls += 1
        return True

    def previous_track(self) -> bool:
        return True

    def play(self) -> bool:
        self.play_calls += 1
        self.playback_state = "playing"
        return True

    def pause(self) -> bool:
        self.pause_calls += 1
        self.playback_state = "paused"
        return True

    def get_playlists(self, fetch_track_counts: bool = False) -> list[FakePlaylist]:
        return list(self.playlists)

    def load_playlist(self, playlist_uri: str) -> bool:
        self.loaded_playlists.append(playlist_uri)
        return True


class FakeContact:
    """Minimal contact record for VoIP screen tests."""

    def __init__(self, name: str, sip_address: str, favorite: bool = False) -> None:
        self.name = name
        self.sip_address = sip_address
        self.favorite = favorite


class FakeConfigManager:
    """Minimal config manager returning test contacts."""

    def __init__(self, contacts: list[FakeContact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[FakeContact]:
        return list(self._contacts)


class FakeVoIPManager:
    """Minimal VoIP double for one-button screen tests."""

    def __init__(self) -> None:
        self.running = True
        self.registered = True
        self.call_state = "idle"
        self.answer_calls = 0
        self.reject_calls = 0
        self.hangup_calls = 0
        self.toggle_mute_calls = 0
        self.is_muted = False
        self.make_calls: list[tuple[str, str | None]] = []

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "registered": self.registered,
            "registration_state": "ok",
            "call_state": self.call_state,
            "sip_identity": "sip:test@example.com",
        }

    def get_caller_info(self) -> dict:
        return {"display_name": "Alice", "address": "sip:alice@example.com"}

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        self.make_calls.append((sip_address, contact_name))
        return True

    def answer_call(self) -> bool:
        self.answer_calls += 1
        return True

    def reject_call(self) -> bool:
        self.reject_calls += 1
        return True

    def hangup(self) -> bool:
        self.hangup_calls += 1
        return True

    def toggle_mute(self) -> bool:
        self.toggle_mute_calls += 1
        self.is_muted = not self.is_muted
        return self.is_muted

    def get_call_duration(self) -> int:
        return 42


@pytest.fixture
def display() -> Display:
    """Create a simulation display and clean it up after each test."""
    test_display = Display(simulate=True)
    try:
        yield test_display
    finally:
        test_display.cleanup()


@pytest.fixture
def one_button_context() -> AppContext:
    """Create a Whisplay-mode app context."""
    return AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)


def test_hub_advance_wraps_from_last_card_to_first(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Whisplay root hub should wrap its carousel on ADVANCE."""
    hub = HubScreen(
        display,
        one_button_context,
        mopidy_client=FakeMopidyClient(),
        voip_manager=FakeVoIPManager(),
    )

    hub.selected_index = 2
    hub.on_advance()

    assert hub.selected_index == 0


def test_now_playing_advance_and_select_follow_one_button_mapping(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Now Playing should map ADVANCE to next track and SELECT to play/pause."""
    mopidy = FakeMopidyClient()
    screen = NowPlayingScreen(display, one_button_context, mopidy_client=mopidy)

    screen.on_advance()
    screen.on_select()
    screen.on_select()
    screen.on_back()

    assert mopidy.next_track_calls == 1
    assert mopidy.play_calls == 1
    assert mopidy.pause_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("back")


def test_playlist_advance_wraps_and_select_loads_playlist(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Playlists should wrap on ADVANCE and load the current selection on SELECT."""
    mopidy = FakeMopidyClient()
    screen = PlaylistScreen(display, one_button_context, mopidy_client=mopidy)

    screen.enter()
    screen.selected_index = len(screen.playlists) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert mopidy.loaded_playlists == ["playlist:alpha"]
    assert screen.consume_navigation_request() == NavigationRequest.route("playlist_loaded")


def test_call_screen_advance_wraps_through_quick_targets(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The call hub should wrap through quick-call targets on ADVANCE."""
    contacts = [
        FakeContact("Alice", "sip:alice@example.com", favorite=True),
        FakeContact("Bob", "sip:bob@example.com", favorite=False),
    ]
    screen = CallScreen(
        display,
        one_button_context,
        voip_manager=FakeVoIPManager(),
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.selected_index = len(screen.quick_targets) - 1
    screen.on_advance()

    assert screen.selected_index == 0


def test_contact_list_advance_wraps_and_select_calls_contact(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The contact list should wrap on ADVANCE and call on SELECT."""
    voip_manager = FakeVoIPManager()
    contacts = [
        FakeContact("Alice", "sip:alice@example.com", favorite=True),
        FakeContact("Bob", "sip:bob@example.com", favorite=False),
    ]
    screen = ContactListScreen(
        display,
        one_button_context,
        voip_manager=voip_manager,
        config_manager=FakeConfigManager(contacts),
    )

    screen.enter()
    screen.selected_index = len(screen.contacts) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert voip_manager.make_calls == [("sip:alice@example.com", "Alice")]
    assert screen.consume_navigation_request() == NavigationRequest.route("call_started")


def test_incoming_call_select_answers_and_back_rejects(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Incoming calls should answer on SELECT and reject on BACK."""
    voip_manager = FakeVoIPManager()
    screen = IncomingCallScreen(display, one_button_context, voip_manager=voip_manager)

    screen.on_advance()
    screen.on_select()
    assert voip_manager.answer_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("call_answered")

    screen.on_back()
    assert voip_manager.reject_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("call_rejected")


def test_outgoing_call_back_cancels_call(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Outgoing calls should cancel on BACK in one-button mode."""
    voip_manager = FakeVoIPManager()
    screen = OutgoingCallScreen(display, one_button_context, voip_manager=voip_manager)

    screen.on_advance()
    screen.on_select()
    screen.on_back()

    assert voip_manager.hangup_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("call_hangup")


def test_in_call_advance_toggles_mute_and_back_hangs_up(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """In-call view should use ADVANCE for mute and BACK for hangup."""
    voip_manager = FakeVoIPManager()
    screen = InCallScreen(display, one_button_context, voip_manager=voip_manager)

    screen.on_advance()
    screen.on_back()

    assert voip_manager.toggle_mute_calls == 1
    assert voip_manager.hangup_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("call_hangup")
