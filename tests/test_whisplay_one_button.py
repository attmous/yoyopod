"""Focused tests for the Whisplay-native one-button UI flow."""

from __future__ import annotations

import pytest

from yoyopod.app_context import AppContext
from yoyopod.audio import (
    LocalMusicService,
    MockMusicBackend,
    Playlist,
    RecentTrackHistoryStore,
    Track,
)
from yoyopod.communication.calling import VoiceNoteDraft
from yoyopod.ui.display import Display
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens import (
    CallScreen,
    ContactListScreen,
    HubScreen,
    InCallScreen,
    IncomingCallScreen,
    ListenScreen,
    NavigationRequest,
    NowPlayingScreen,
    OutgoingCallScreen,
    PlaylistScreen,
    RecentTracksScreen,
    TalkContactScreen,
    VoiceNoteScreen,
)
from yoyopod.ui.screens.music.now_playing import (
    build_now_playing_actions,
    build_now_playing_state_provider,
)
from yoyopod.ui.screens.voip.voice_note import (
    build_voice_note_actions,
    build_voice_note_state_provider,
)


class FakeMusicBackend(MockMusicBackend):
    """Minimal music backend double for one-button screen tests."""

    def __init__(self) -> None:
        super().__init__()
        self.start()
        self.current_track = Track(
            uri="/music/track.mp3", name="Track", artists=["Artist"], length=120000
        )
        self.next_track_calls = 0
        self.play_calls = 0
        self.pause_calls = 0
        self.playlists = [
            Playlist("m3u:alpha", "Alpha"),
            Playlist("m3u:beta", "Beta"),
        ]
        self.loaded_playlists: list[str] = []

    def next_track(self) -> bool:
        self.next_track_calls += 1
        return super().next_track()

    def play(self) -> bool:
        self.play_calls += 1
        return super().play()

    def pause(self) -> bool:
        self.pause_calls += 1
        return super().pause()

    def get_playlists(self, fetch_track_counts: bool = False) -> list[Playlist]:
        return list(self.playlists)

    def load_playlist(self, playlist_uri: str) -> bool:
        self.loaded_playlists.append(playlist_uri)
        return True

    def load_track_uris(self, track_uris: list[str]) -> bool:
        if track_uris:
            self._playback_state = "playing"
        return True


class FakeContact:
    """Minimal contact record for VoIP screen tests."""

    def __init__(
        self, name: str, sip_address: str, favorite: bool = False, notes: str = ""
    ) -> None:
        self.name = name
        self.sip_address = sip_address
        self.favorite = favorite
        self.notes = notes

    @property
    def display_name(self) -> str:
        return self.notes or self.name


class FakePeopleDirectory:
    """Minimal people-directory returning test contacts."""

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
        self.latest_notes: dict[str, object] = {}
        self.active_voice_note: VoiceNoteDraft | None = None
        self.started_recordings: list[tuple[str, str]] = []
        self.send_attempts = 0

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

    def latest_voice_note_for_contact(self, sip_address: str):
        return self.latest_notes.get(sip_address)

    def play_latest_voice_note(self, sip_address: str) -> bool:
        return True

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        return

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.started_recordings.append((recipient_address, recipient_name))
        self.active_voice_note = VoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name,
            file_path="data/voice_notes/test.wav",
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        if self.active_voice_note is None:
            return None
        self.active_voice_note.duration_ms = 2500
        self.active_voice_note.send_state = "review"
        self.active_voice_note.status_text = "Ready to send"
        return self.active_voice_note

    def cancel_voice_note_recording(self) -> bool:
        self.active_voice_note = None
        return True

    def discard_active_voice_note(self) -> None:
        self.active_voice_note = None

    def send_active_voice_note(self) -> bool:
        self.send_attempts += 1
        if self.active_voice_note is None:
            return False
        self.active_voice_note.send_state = "sending"
        self.active_voice_note.status_text = "Sending..."
        return True

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        return self.active_voice_note


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
    music_service = LocalMusicService(FakeMusicBackend())
    hub = HubScreen(
        display,
        one_button_context,
        music_backend=FakeMusicBackend(),
        local_music_service=music_service,
        voip_manager=FakeVoIPManager(),
    )

    hub.selected_index = 3
    hub.on_advance()

    assert hub.selected_index == 0


def test_listen_screen_select_opens_local_playlist_flow(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Listen should route its Playlists row into the playlist browser."""
    screen = ListenScreen(
        display,
        one_button_context,
        music_service=LocalMusicService(FakeMusicBackend()),
    )

    screen.enter()
    screen.selected_index = 0
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("open_playlists")


def test_listen_screen_select_opens_recent_tracks(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Listen should route its Recent row into the recent-tracks browser."""
    screen = ListenScreen(
        display,
        one_button_context,
        music_service=LocalMusicService(FakeMusicBackend()),
    )

    screen.enter()
    screen.selected_index = 1
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("open_recent")


def test_hub_select_requests_setup_route_for_setup_card(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Whisplay hub should open Setup from its fourth root card."""
    hub = HubScreen(
        display,
        one_button_context,
        music_backend=FakeMusicBackend(),
        local_music_service=LocalMusicService(FakeMusicBackend()),
        voip_manager=FakeVoIPManager(),
    )

    hub.selected_index = 3
    hub.on_select()

    assert hub.consume_navigation_request() == NavigationRequest.route("select", payload="Setup")


def test_hub_cards_use_mode_specific_hero_tiles(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The root cards should tint their centered hero tile differently per mode."""
    hub = HubScreen(
        display,
        one_button_context,
        music_backend=FakeMusicBackend(),
        local_music_service=LocalMusicService(FakeMusicBackend()),
        voip_manager=FakeVoIPManager(),
    )

    hub.selected_index = 0
    hub.render()
    listen_fill = display.get_adapter().buffer.getpixel((86, 74))

    hub.selected_index = 1
    hub.render()
    talk_fill = display.get_adapter().buffer.getpixel((86, 74))

    assert listen_fill != talk_fill


def test_hub_listen_subtitle_handles_active_track_without_crashing(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Hub should summarize an active track without raising at render time."""

    backend = FakeMusicBackend()
    backend.current_track = Track(
        uri="/music/golden-hour.mp3",
        name="Golden Hour",
        artists=["Kacey Musgraves"],
        length=214000,
    )
    backend.play()
    hub = HubScreen(
        display,
        one_button_context,
        music_backend=backend,
        local_music_service=LocalMusicService(FakeMusicBackend()),
        voip_manager=FakeVoIPManager(),
    )

    assert hub._listen_subtitle().startswith("Playing ")


def test_now_playing_advance_and_select_follow_one_button_mapping(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Now Playing should map ADVANCE to next track and SELECT to play/pause."""
    backend = FakeMusicBackend()
    screen = NowPlayingScreen(
        display,
        one_button_context,
        state_provider=build_now_playing_state_provider(
            context=one_button_context,
            music_backend=backend,
        ),
        actions=build_now_playing_actions(
            context=one_button_context,
            music_backend=backend,
        ),
    )

    screen.on_advance()
    screen.on_select()
    screen.on_select()
    screen.on_back()

    assert backend.next_track_calls == 1
    assert backend.play_calls == 1
    assert backend.pause_calls == 1
    assert screen.consume_navigation_request() == NavigationRequest.route("back")


def test_playlist_advance_wraps_and_select_loads_playlist(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Playlists should wrap on ADVANCE and load the current selection on SELECT."""
    backend = FakeMusicBackend()
    screen = PlaylistScreen(display, one_button_context, music_service=LocalMusicService(backend))

    screen.enter()
    screen.selected_index = len(screen.playlists) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert backend.loaded_playlists == ["m3u:alpha"]
    assert screen.consume_navigation_request() == NavigationRequest.route("playlist_loaded")


def test_recent_tracks_select_routes_to_now_playing(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Recent track playback should route into Now Playing once the track is queued."""
    backend = FakeMusicBackend()
    service = LocalMusicService(
        backend,
        recent_store=RecentTrackHistoryStore(tmp_path / "recent_tracks.json"),
    )
    service.record_recent_track(
        Track(
            uri="local:track:1",
            name="Alpha Song",
            artists=["Artist"],
            album="Album",
        )
    )
    screen = RecentTracksScreen(display, one_button_context, music_service=service)

    screen.enter()
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("track_loaded")


def test_call_screen_advance_wraps_through_contacts(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Talk deck should wrap through contacts on ADVANCE."""
    contacts = [
        FakeContact("Alice", "sip:alice@example.com", favorite=True),
        FakeContact("Bob", "sip:bob@example.com", favorite=False),
    ]
    screen = CallScreen(
        display,
        one_button_context,
        voip_manager=FakeVoIPManager(),
        people_directory=FakePeopleDirectory(contacts),
    )

    screen.enter()
    screen.selected_index = len(screen.people) - 1
    screen.on_advance()

    assert screen.selected_index == 0


def test_call_screen_select_routes_to_contact_actions(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Selecting from Talk should open the contact action screen."""

    contacts = [
        FakeContact("Alice", "sip:alice@example.com", favorite=True, notes="Mama"),
    ]
    screen = CallScreen(
        display,
        one_button_context,
        voip_manager=FakeVoIPManager(),
        people_directory=FakePeopleDirectory(contacts),
    )

    screen.enter()
    screen.on_select()

    assert one_button_context.talk_contact_name == "Mama"
    assert screen.consume_navigation_request() == NavigationRequest.route("open_contact")


def test_talk_contact_screen_advance_and_select_follow_one_button_mapping(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The contact action screen should cycle actions and open voice notes."""

    one_button_context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    screen = TalkContactScreen(
        display,
        one_button_context,
        voip_manager=FakeVoIPManager(),
    )

    screen.enter()
    screen.on_advance()
    screen.on_select()

    assert one_button_context.voice_note_recipient_name == "Mama"
    assert screen.consume_navigation_request() == NavigationRequest.route("voice_note")


def test_voice_note_screen_uses_hold_to_record_in_one_button_mode(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Voice notes should start on raw hold and stop on release in one-button mode."""

    one_button_context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    voip_manager = FakeVoIPManager()
    screen = VoiceNoteScreen(
        display,
        one_button_context,
        state_provider=build_voice_note_state_provider(
            context=one_button_context,
            voip_manager=voip_manager,
        ),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()
    assert screen.wants_ptt_passthrough()

    screen.on_ptt_press({"stage": "hold_started"})
    assert screen.current_view_model()[0] == "Recording"

    screen.on_ptt_release({"hold_started": True})
    assert screen.current_view_model()[0] == "Review"

    screen.on_select()
    assert screen.current_view_model()[0] == "Sending"
    assert voip_manager.send_attempts == 1


def test_contact_list_advance_wraps_and_select_opens_contact(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The contact list should wrap on ADVANCE and open TalkContact on SELECT."""
    voip_manager = FakeVoIPManager()
    contacts = [
        FakeContact("Alice", "sip:alice@example.com", favorite=True),
        FakeContact("Bob", "sip:bob@example.com", favorite=False),
    ]
    screen = ContactListScreen(
        display,
        one_button_context,
        voip_manager=voip_manager,
        people_directory=FakePeopleDirectory(contacts),
    )

    screen.enter()
    screen.selected_index = len(screen.contacts) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert one_button_context.talk_contact_name == "Alice"
    assert one_button_context.talk_contact_address == "sip:alice@example.com"
    assert voip_manager.make_calls == []
    assert screen.consume_navigation_request() == NavigationRequest.route("open_contact")


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
