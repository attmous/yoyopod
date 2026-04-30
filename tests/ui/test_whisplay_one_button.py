"""Focused tests for the Whisplay-native one-button UI flow."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoyopod.backends.music import MockMusicBackend, Track
from yoyopod.core import AppContext
from yoyopod.integrations.call import VoiceNoteDraft
from yoyopod.integrations.music import LocalMusicService, RecentTrackHistoryStore
from yoyopod.ui.display import Display
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens.music.now_playing import (
    NowPlayingSnapshot,
    NowPlayingScreen,
    build_now_playing_actions,
    build_now_playing_state_provider,
)
from yoyopod.ui.screens.music.playlist import PlaylistScreen
from yoyopod.ui.screens.music.recent import RecentTracksScreen
from yoyopod.ui.screens.navigation.hub import (
    HubListenSnapshot,
    HubScreen,
    build_hub_listen_subtitle_provider,
)
from yoyopod.ui.screens.navigation.listen import ListenScreen
from yoyopod.ui.screens.router import NavigationRequest
from yoyopod.ui.screens.voip.call_actions import CallActions
from yoyopod.ui.screens.voip.contact_list import ContactListScreen
from yoyopod.ui.screens.voip.in_call import InCallScreen
from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen
from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen
from yoyopod.ui.screens.voip.quick_call import CallScreen
from yoyopod.ui.screens.voip.talk_contact import TalkContactScreen
from yoyopod.ui.screens.voip.voice_note import (
    VoiceNoteScreen,
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

    def load_playlist_file(self, path: str) -> bool:
        self.loaded_playlists.append(path)
        return super().load_playlist_file(path)


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

    def preferred_call_target(
        self,
        *,
        gsm_enabled: bool = False,
    ) -> tuple[str | None, str]:
        if self.sip_address.strip():
            return "sip", self.sip_address.strip()
        return None, ""

    def is_callable(self, *, gsm_enabled: bool = False) -> bool:
        route, _ = self.preferred_call_target(gsm_enabled=gsm_enabled)
        return bool(route)


class FakePeopleDirectory:
    """Minimal people-directory returning test contacts."""

    def __init__(self, contacts: list[FakeContact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[FakeContact]:
        return list(self._contacts)

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[FakeContact]:
        return [
            contact for contact in self._contacts if contact.is_callable(gsm_enabled=gsm_enabled)
        ]


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


def _call_actions(voip_manager: FakeVoIPManager) -> CallActions:
    return CallActions(
        answer_call=voip_manager.answer_call,
        reject_call=voip_manager.reject_call,
        hangup_call=voip_manager.hangup,
        make_call=voip_manager.make_call,
    )


def _now_playing_snapshot_provider(backend: FakeMusicBackend):
    def provider() -> NowPlayingSnapshot:
        return NowPlayingSnapshot(
            is_connected=backend.is_connected,
            track=backend.get_current_track(),
            playback_state=backend.get_playback_state(),
            time_position=float(backend.get_time_position()),
        )

    return provider


def _toggle_playback_action(backend: FakeMusicBackend):
    def action() -> None:
        if backend.get_playback_state() == "playing":
            backend.pause()
        else:
            backend.play()

    return action


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
    backend = FakeMusicBackend()
    music_service = LocalMusicService(backend)
    hub = HubScreen(
        display,
        one_button_context,
        listen_subtitle_provider=build_hub_listen_subtitle_provider(
            display,
            snapshot_provider=lambda: HubListenSnapshot(
                is_connected=backend.is_connected,
                track=backend.get_current_track(),
                playback_state=backend.get_playback_state(),
                playlist_count=music_service.playlist_count(),
            ),
        ),
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


def test_listen_screen_can_resolve_music_service_and_shuffle_via_app(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Listen should use the app seam for library reads and shuffle actions when available."""

    backend = FakeMusicBackend()
    music_service = LocalMusicService(backend)
    service_calls: list[tuple[str, str, object]] = []
    app = SimpleNamespace(
        context=one_button_context,
        get_music_library=lambda: music_service,
        services=SimpleNamespace(
            call=lambda domain, service, data=None: service_calls.append((domain, service, data))
            or True
        ),
    )
    screen = ListenScreen(display, app=app)

    screen.enter()
    assert [item.key for item in screen.items] == ["playlists", "recent", "shuffle"]

    screen.selected_index = 2
    screen.on_select()

    assert len(service_calls) == 1
    assert service_calls[0][0:2] == ("music", "shuffle_all")
    assert screen.consume_navigation_request() == NavigationRequest.route("shuffle_started")


def test_listen_screen_falls_back_when_app_shuffle_service_is_unregistered(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Listen should fall back to the local library when shuffle service is absent."""

    backend = FakeMusicBackend()
    music_service = LocalMusicService(backend)
    music_service.shuffle_all = lambda: True  # type: ignore[method-assign]

    def raise_missing_service(domain: str, service: str, data=None) -> bool:
        raise KeyError(f"Unknown service: {domain}.{service}")

    app = SimpleNamespace(
        context=one_button_context,
        get_music_library=lambda: music_service,
        services=SimpleNamespace(call=raise_missing_service),
    )
    screen = ListenScreen(display, app=app)

    screen.enter()
    screen.selected_index = 2
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("shuffle_started")


def test_hub_select_requests_setup_route_for_setup_card(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Whisplay hub should open Setup from its fourth root card."""
    hub = HubScreen(
        display,
        one_button_context,
        listen_subtitle_provider=build_hub_listen_subtitle_provider(display),
    )

    hub.selected_index = 3
    hub.on_select()

    assert hub.consume_navigation_request() == NavigationRequest.route("select", payload="Setup")


def test_hub_cards_use_mode_specific_hero_tiles(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The root cards should use different hero-tile fills per mode."""
    hub = HubScreen(
        display,
        one_button_context,
        listen_subtitle_provider=build_hub_listen_subtitle_provider(display),
    )

    listen_fill = hub.tile_fill_color("listen")
    talk_fill = hub.tile_fill_color("talk")

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
        listen_subtitle_provider=build_hub_listen_subtitle_provider(
            display,
            snapshot_provider=lambda: HubListenSnapshot(
                is_connected=backend.is_connected,
                track=backend.get_current_track(),
                playback_state=backend.get_playback_state(),
                playlist_count=None,
            ),
        ),
    )

    assert hub._listen_subtitle().startswith("Playing ")


def test_hub_can_resolve_music_dependencies_from_app(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Hub should derive music summaries from the owning app when no managers are passed."""

    backend = FakeMusicBackend()
    backend.current_track = Track(
        uri="/music/golden-hour.mp3",
        name="Golden Hour",
        artists=["Kacey Musgraves"],
        length=214000,
    )
    backend.play()
    app = SimpleNamespace(
        context=one_button_context,
        music_backend=backend,
        get_music_library=lambda: LocalMusicService(FakeMusicBackend()),
    )
    hub = HubScreen(display, app=app)

    hub.enter()

    assert hub._listen_subtitle().startswith("Playing ")


def test_hub_talk_subtitle_uses_cached_context_status_without_polling_voip_manager(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """The Hub Talk subtitle should come from cached context state, not live manager polling."""

    class PollingVoIPManager:
        def get_status(self) -> dict[str, object]:
            raise AssertionError("HubScreen should not poll get_status() during render")

    one_button_context.update_voip_status(
        configured=True,
        ready=False,
        running=True,
        registration_state="progress",
    )
    hub = HubScreen(
        display,
        one_button_context,
        listen_subtitle_provider=build_hub_listen_subtitle_provider(display),
    )

    assert hub._talk_subtitle() == "Connecting"


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
            snapshot_provider=_now_playing_snapshot_provider(backend),
        ),
        actions=build_now_playing_actions(
            context=one_button_context,
            toggle_playback_action=_toggle_playback_action(backend),
            previous_track_action=backend.previous_track,
            next_track_action=backend.next_track,
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


def test_now_playing_actions_can_use_music_services_from_app(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Now Playing should prefer the app music services when they exist."""

    service_calls: list[tuple[str, str, object]] = []
    app = SimpleNamespace(
        context=one_button_context,
        states=SimpleNamespace(get_value=lambda entity, default=None: "paused"),
        services=SimpleNamespace(
            call=lambda domain, service, data=None: service_calls.append((domain, service, data))
            or True
        ),
    )
    screen = NowPlayingScreen(display, app=app)

    screen.on_select()
    screen.on_advance()
    screen.on_up()

    assert [call[:2] for call in service_calls] == [
        ("music", "resume"),
        ("music", "next_track"),
        ("music", "previous_track"),
    ]


def test_now_playing_actions_fall_back_when_app_music_services_are_unregistered(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Now Playing should still control playback when app music services are absent."""

    backend = FakeMusicBackend()
    backend.play()

    def raise_missing_service(domain: str, service: str, data=None) -> bool:
        raise KeyError(f"Unknown service: {domain}.{service}")

    app = SimpleNamespace(
        context=one_button_context,
        states=SimpleNamespace(get_value=lambda entity, default=None: "playing"),
        services=SimpleNamespace(call=raise_missing_service),
        music_backend=backend,
    )
    screen = NowPlayingScreen(
        display,
        app=app,
        state_provider=build_now_playing_state_provider(app=app, music_backend=backend),
        actions=build_now_playing_actions(app=app, music_backend=backend),
    )

    screen.on_select()
    screen.on_advance()
    screen.on_up()

    assert backend.pause_calls == 1
    assert backend.next_track_calls == 1


def test_playlist_advance_wraps_and_select_loads_playlist(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Playlists should wrap on ADVANCE and load the current selection on SELECT."""
    backend = FakeMusicBackend()
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    playlist_path = music_dir / "alpha.m3u"
    playlist_path.write_text("#EXTM3U\nsong.mp3\n", encoding="utf-8")
    screen = PlaylistScreen(
        display,
        one_button_context,
        music_service=LocalMusicService(backend, music_dir=music_dir),
    )
    screen.render = lambda: None

    screen.enter()
    screen.selected_index = len(screen.playlists) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert backend.loaded_playlists == [str(playlist_path)]
    assert screen.consume_navigation_request() == NavigationRequest.route("playlist_loaded")


def test_playlist_screen_can_use_app_music_services(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Playlists should resolve library data and load commands through the app seam."""

    backend = FakeMusicBackend()
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    (music_dir / "alpha.m3u").write_text("#EXTM3U\nsong.mp3\n", encoding="utf-8")
    music_service = LocalMusicService(backend, music_dir=music_dir)
    service_calls: list[tuple[str, str, object]] = []
    app = SimpleNamespace(
        context=one_button_context,
        get_music_library=lambda: music_service,
        services=SimpleNamespace(
            call=lambda domain, service, data=None: service_calls.append((domain, service, data))
            or True
        ),
    )
    screen = PlaylistScreen(display, app=app)
    screen.render = lambda: None

    screen.enter()
    screen.on_select()

    assert screen.playlists
    assert [call[:2] for call in service_calls] == [("music", "load_playlist")]
    assert screen.consume_navigation_request() == NavigationRequest.route("playlist_loaded")


def test_playlist_screen_falls_back_when_app_music_service_is_unregistered(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Playlists should fall back to the local library when the app service is absent."""

    backend = FakeMusicBackend()
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    playlist_path = music_dir / "alpha.m3u"
    playlist_path.write_text("#EXTM3U\nsong.mp3\n", encoding="utf-8")
    music_service = LocalMusicService(backend, music_dir=music_dir)

    def raise_missing_service(domain: str, service: str, data=None) -> bool:
        raise KeyError(f"Unknown service: {domain}.{service}")

    app = SimpleNamespace(
        context=one_button_context,
        get_music_library=lambda: music_service,
        services=SimpleNamespace(call=raise_missing_service),
    )
    screen = PlaylistScreen(display, app=app)
    screen.render = lambda: None

    screen.enter()
    screen.on_select()

    assert backend.loaded_playlists == [str(playlist_path)]
    assert screen.consume_navigation_request() == NavigationRequest.route("playlist_loaded")


def test_recent_tracks_select_routes_to_now_playing(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Recent track playback should route into Now Playing once the track is queued."""
    backend = FakeMusicBackend()
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track_path = music_dir / "alpha-song.mp3"
    track_path.write_bytes(b"audio")
    service = LocalMusicService(
        backend,
        music_dir=music_dir,
        recent_store=RecentTrackHistoryStore(tmp_path / "recent_tracks.json"),
    )
    service.record_recent_track(
        Track(
            uri=str(track_path),
            name="Alpha Song",
            artists=["Artist"],
            album="Album",
        )
    )
    screen = RecentTracksScreen(display, one_button_context, music_service=service)
    screen.render = lambda: None

    screen.enter()
    screen.on_select()

    assert screen.consume_navigation_request() == NavigationRequest.route("track_loaded")


def test_recent_tracks_fall_back_when_app_music_service_is_unregistered(
    display: Display,
    one_button_context: AppContext,
    tmp_path,
) -> None:
    """Recent playback should fall back to the local library when the app service is absent."""

    backend = FakeMusicBackend()
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track_path = music_dir / "alpha-song.mp3"
    track_path.write_bytes(b"audio")
    service = LocalMusicService(
        backend,
        music_dir=music_dir,
        recent_store=RecentTrackHistoryStore(tmp_path / "recent_tracks.json"),
    )
    service.record_recent_track(
        Track(
            uri=str(track_path),
            name="Alpha Song",
            artists=["Artist"],
            album="Album",
        )
    )

    def raise_missing_service(domain: str, service: str, data=None) -> bool:
        raise KeyError(f"Unknown service: {domain}.{service}")

    app = SimpleNamespace(
        context=one_button_context,
        get_music_library=lambda: service,
        services=SimpleNamespace(call=raise_missing_service),
    )
    screen = RecentTracksScreen(display, app=app)
    screen.render = lambda: None

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
        contacts_provider=lambda: FakePeopleDirectory(contacts).get_callable_contacts(),
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
        contacts_provider=lambda: FakePeopleDirectory(contacts).get_callable_contacts(),
    )

    screen.enter()
    screen.on_select()

    assert one_button_context.talk.selected_contact_name == "Mama"
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

    assert one_button_context.talk.active_voice_note.recipient_name == "Mama"
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
        contacts_provider=lambda: FakePeopleDirectory(contacts).get_callable_contacts(),
        actions=_call_actions(voip_manager),
    )

    screen.enter()
    screen.selected_index = len(screen.contacts) - 1
    screen.on_advance()
    screen.on_select()

    assert screen.selected_index == 0
    assert one_button_context.talk.selected_contact_name == "Alice"
    assert one_button_context.talk.selected_contact_address == "sip:alice@example.com"
    assert voip_manager.make_calls == []
    assert screen.consume_navigation_request() == NavigationRequest.route("open_contact")


def test_incoming_call_select_answers_and_back_rejects(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Incoming-call actions should defer navigation to coordinator call-state events."""
    voip_manager = FakeVoIPManager()
    screen = IncomingCallScreen(display, one_button_context, actions=_call_actions(voip_manager))

    screen.on_advance()
    screen.on_select()
    assert voip_manager.answer_calls == 1
    assert screen.consume_navigation_request() is None

    screen.on_back()
    assert voip_manager.reject_calls == 1
    assert screen.consume_navigation_request() is None


def test_outgoing_call_back_cancels_call(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """Outgoing-call cancel should wait for backend teardown before navigation."""
    voip_manager = FakeVoIPManager()
    screen = OutgoingCallScreen(display, one_button_context, actions=_call_actions(voip_manager))

    screen.on_advance()
    screen.on_select()
    screen.on_back()

    assert voip_manager.hangup_calls == 1
    assert screen.consume_navigation_request() is None


def test_in_call_advance_toggles_mute_and_back_hangs_up(
    display: Display,
    one_button_context: AppContext,
) -> None:
    """In-call actions should leave teardown navigation to the coordinator."""
    voip_manager = FakeVoIPManager()
    screen = InCallScreen(display, one_button_context, voip_manager=voip_manager)

    screen.on_advance()
    screen.on_back()

    assert voip_manager.toggle_mute_calls == 1
    assert voip_manager.hangup_calls == 1
    assert screen.consume_navigation_request() is None
