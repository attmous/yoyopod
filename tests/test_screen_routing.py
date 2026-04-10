#!/usr/bin/env python3
"""Routing-focused tests for the declarative screen navigation layer."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Callable

import pytest

from yoyopy.app_context import AppContext
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputAction, InputManager
from yoyopy.ui.screens import (
    AskScreen,
    HubScreen,
    HomeScreen,
    MenuScreen,
    NavigationRequest,
    Screen,
    ScreenManager,
    ScreenRouter,
    VoiceCommandsScreen,
)
from yoyopy.voice import VoiceCaptureResult, VoiceSettings, VoiceTranscript


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
        "Listen": NavigationRequest.push("listen"),
        "Talk": NavigationRequest.push("call"),
        "Ask": NavigationRequest.push("ask"),
        "Setup": NavigationRequest.push("power"),
        "Load Playlist": NavigationRequest.push("playlists"),
        "Music": NavigationRequest.push("listen"),
        "Now Playing": NavigationRequest.push("now_playing"),
        "Browse Playlists": NavigationRequest.push("playlists"),
        "Playlists": NavigationRequest.push("playlists"),
        "VoIP Status": NavigationRequest.push("call"),
        "Call Contact": NavigationRequest.push("contacts"),
        "Contacts": NavigationRequest.push("contacts"),
        "Power Status": NavigationRequest.push("power"),
    }

    for label, expected_request in expected_routes.items():
        assert router.resolve("menu", "select", payload=label) == expected_request


def test_screen_router_covers_call_hub_routes() -> None:
    """The Talk flow should resolve its people-first routes through the router."""
    router = ScreenRouter()

    assert router.resolve("call", "open_contact") == NavigationRequest.push("talk_contact")
    assert router.resolve("call", "call_started") == NavigationRequest.push("outgoing_call")
    assert router.resolve("talk_contact", "voice_note") == NavigationRequest.push("voice_note")
    assert router.resolve("talk_contact", "call_started") == NavigationRequest.push("outgoing_call")
    assert router.resolve("contacts", "open_contact") == NavigationRequest.push("talk_contact")
    assert router.resolve("contacts", "voice_note_selected") == NavigationRequest.push("voice_note")


def test_screen_router_covers_whisplay_hub_routes() -> None:
    """The Whisplay action hub should route each root card to the correct screen."""
    router = ScreenRouter()

    assert router.resolve("hub", "select", payload="Listen") == NavigationRequest.push("listen")
    assert router.resolve("hub", "select", payload="Talk") == NavigationRequest.push("call")
    assert router.resolve("hub", "select", payload="Ask") == NavigationRequest.push("ask")
    assert router.resolve("hub", "select", payload="Setup") == NavigationRequest.push("power")
    assert router.resolve("hub", "select", payload="Power") == NavigationRequest.push("power")


def test_screen_router_covers_local_listen_routes() -> None:
    """The local-first Listen menu should route into playlists, recents, and shuffle."""
    router = ScreenRouter()

    assert router.resolve("listen", "open_playlists") == NavigationRequest.push("playlists")
    assert router.resolve("listen", "open_recent") == NavigationRequest.push("recent_tracks")
    assert router.resolve("listen", "shuffle_started") == NavigationRequest.push("now_playing")


def test_screen_router_covers_ask_routes() -> None:
    """The unified Ask screen should route call_started and shuffle_started."""
    router = ScreenRouter()

    assert router.resolve("ask", "back") == NavigationRequest.pop()
    assert router.resolve("ask", "call_started") == NavigationRequest.push("outgoing_call")
    assert router.resolve("ask", "shuffle_started") == NavigationRequest.push("now_playing")


def test_screen_router_covers_hub_hold_ask() -> None:
    """Hold on the Hub should route to the Ask screen."""
    router = ScreenRouter()

    assert router.resolve("hub", "hold_ask") == NavigationRequest.push("ask")


def test_screen_manager_routes_menu_labels_through_stack(display: Display) -> None:
    """Menu labels should resolve through the router and preserve stack navigation."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    home = HomeScreen(display, context)
    menu = MenuScreen(display, context, items=["Load Playlist", "Back"])
    playlists = RoutableStubScreen(display, context)
    power = RoutableStubScreen(display, context)

    screen_manager.register_screen("home", home)
    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("playlists", playlists)
    screen_manager.register_screen("power", power)

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


def test_screen_manager_routes_power_status_through_stack(display: Display) -> None:
    """Power Status should route through the stack like any other menu destination."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    menu = MenuScreen(display, context, items=["Power Status"])
    power = RoutableStubScreen(display, context)

    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("power", power)

    screen_manager.replace_screen("menu")
    input_manager.simulate_action(InputAction.SELECT)

    assert screen_manager.current_screen is power


def test_screen_manager_routes_whisplay_hub_cards_through_stack(display: Display) -> None:
    """The one-button hub should route its cards through the same declarative router."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    hub = HubScreen(display, context)
    listen = RoutableStubScreen(display, context)
    call = RoutableStubScreen(display, context)
    ask = RoutableStubScreen(display, context)
    power = RoutableStubScreen(display, context)

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("listen", listen)
    screen_manager.register_screen("call", call)
    screen_manager.register_screen("ask", ask)
    screen_manager.register_screen("power", power)

    screen_manager.replace_screen("hub")
    assert screen_manager.current_screen is hub

    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is listen

    screen_manager.replace_screen("hub")
    hub.selected_index = 1
    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is call

    screen_manager.replace_screen("hub")
    hub.selected_index = 2
    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is ask

    screen_manager.replace_screen("hub")
    hub.selected_index = 3
    input_manager.simulate_action(InputAction.SELECT)
    assert screen_manager.current_screen is power


def test_screen_manager_can_schedule_actions_for_main_thread(display: Display) -> None:
    """A scheduled ScreenManager should defer screen actions until the scheduler runs them."""

    context = AppContext()
    input_manager = InputManager()
    scheduled_callbacks: list[Callable[[], None]] = []
    screen_manager = ScreenManager(
        display,
        input_manager,
        action_scheduler=scheduled_callbacks.append,
    )

    hub = HubScreen(display, context)
    listen = RoutableStubScreen(display, context)

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("listen", listen)

    screen_manager.replace_screen("hub")
    input_manager.simulate_action(InputAction.SELECT)

    assert screen_manager.current_screen is hub
    assert len(scheduled_callbacks) == 1

    scheduled_callbacks.pop()()
    assert screen_manager.current_screen is listen


def test_ask_screen_routes_to_selected_subflow() -> None:
    """Ask should expose Voice Commands and AI Requests as first-level choices."""

    ask = AskScreen(display=object(), context=AppContext())

    assert ask.items()[0].title == "Voice Commands"

    ask.on_select()
    assert ask.consume_navigation_request() == NavigationRequest.route(
        "select", payload="Voice Commands"
    )

    ask.on_advance()
    ask.on_select()
    assert ask.consume_navigation_request() == NavigationRequest.route(
        "select", payload="AI Requests"
    )


class _FakeContact:
    def __init__(self, name: str, sip_address: str, notes: str = "") -> None:
        self.name = name
        self.sip_address = sip_address
        self.notes = notes

    @property
    def display_name(self) -> str:
        return self.notes or self.name


class _FakeConfigManager:
    def __init__(self, contacts: list[_FakeContact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[_FakeContact]:
        return self._contacts

    def get_capture_device_id(self) -> str | None:
        return None

    def get_app_settings(self):
        return SimpleNamespace(
            voice=SimpleNamespace(
                commands_enabled=False,
                ai_requests_enabled=False,
                screen_read_enabled=True,
                stt_enabled=True,
                tts_enabled=False,
                stt_backend="dummy-stt",
                tts_backend="dummy-tts",
                vosk_model_path="models/custom-model",
                sample_rate_hz=22050,
                record_seconds=6,
                tts_rate_wpm=180,
                tts_voice="en-us",
            )
        )

    def get_default_output_volume(self) -> int:
        return 61


class _FakeVoipManager:
    def __init__(self) -> None:
        self.make_calls: list[tuple[str, str]] = []
        self.mute_calls = 0
        self.unmute_calls = 0

    def make_call(self, sip_address: str, contact_name: str = "") -> bool:
        self.make_calls.append((sip_address, contact_name))
        return True

    def mute(self) -> bool:
        self.mute_calls += 1
        return True

    def unmute(self) -> bool:
        self.unmute_calls += 1
        return True


class _FakeVoiceService:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.capture_calls = 0
        self.speak_calls: list[str] = []
        self.last_audio_path: Path | None = None

    def capture_available(self) -> bool:
        return True

    def stt_available(self) -> bool:
        return True

    def tts_available(self) -> bool:
        return True

    def capture_audio(self, request) -> VoiceCaptureResult:
        self.capture_calls += 1
        with NamedTemporaryFile(
            prefix="voice-command-test-", suffix=".wav", delete=False
        ) as handle:
            path = Path(handle.name)
        path.write_bytes(b"RIFF")
        self.last_audio_path = path
        return VoiceCaptureResult(audio_path=path, recorded=True)

    def transcribe(self, audio_path) -> VoiceTranscript:
        return VoiceTranscript(text=self.transcript, confidence=0.92)

    def match_command(self, transcript: str):
        from yoyopy.voice.commands import match_voice_command

        return match_voice_command(transcript)

    def speak(self, text: str) -> bool:
        self.speak_calls.append(text)
        return True


def test_voice_commands_screen_applies_local_device_actions() -> None:
    """Voice commands should update mic and volume state through local hooks."""

    context = AppContext()
    volume_up_calls: list[int] = []
    voip_manager = _FakeVoipManager()
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        voip_manager=voip_manager,
        volume_up_action=lambda step: volume_up_calls.append(step) or 55,
        mute_action=voip_manager.mute,
        unmute_action=voip_manager.unmute,
    )

    screen.on_voice_command({"transcript": "volume up"})
    assert volume_up_calls == [5]
    assert context.voice.last_spoken_text == "Volume is 55."

    screen.on_voice_command({"transcript": "mute mic"})
    assert context.voice.mic_muted is True
    assert voip_manager.mute_calls == 1
    assert context.voice.last_spoken_text == "Voice commands mic is muted."

    screen.on_voice_command({"transcript": "unmute mic"})
    assert context.voice.mic_muted is False
    assert voip_manager.unmute_calls == 1
    assert context.voice.last_spoken_text == "Voice commands mic is live."


def test_voice_commands_screen_can_start_music_from_local_hook() -> None:
    """Basic play-music commands should route into the local music flow."""

    screen = VoiceCommandsScreen(
        display=object(),
        context=AppContext(),
        play_music_action=lambda: True,
    )

    screen.on_voice_command({"transcript": "play music"})

    assert screen.consume_navigation_request() == NavigationRequest.route("shuffle_started")


def test_voice_commands_screen_can_place_call_for_named_contact() -> None:
    """Call commands should resolve child-facing labels and trigger VoIP dialing."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    screen.on_voice_command({"transcript": "call mama"})

    assert context.talk_contact_name == "Mama"
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]
    assert screen.consume_navigation_request() == NavigationRequest.route("call_started")


def test_voice_commands_screen_can_place_call_for_parent_aliases() -> None:
    """Parent aliases like mom and dad should resolve against kid-facing labels."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [
                _FakeContact("Hagar", "sip:mama@example.com", notes="Mama"),
                _FakeContact("Moustafa", "sip:dad@example.com", notes="Dad"),
            ]
        ),
        voip_manager=voip_manager,
    )

    screen.on_voice_command({"transcript": "call mom"})
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]
    assert screen.consume_navigation_request() == NavigationRequest.route("call_started")

    screen.on_voice_command({"transcript": "call dad"})
    assert voip_manager.make_calls[-1] == ("sip:dad@example.com", "Dad")
    assert screen.consume_navigation_request() == NavigationRequest.route("call_started")


def test_voice_commands_screen_select_can_capture_and_execute_command() -> None:
    """Selecting command mode should capture speech and execute the transcript."""

    context = AppContext()
    service = _FakeVoiceService("mute mic")
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _settings: service,
    )

    screen.on_select()

    assert service.capture_calls == 1
    assert context.voice.mic_muted is True
    assert context.voice.last_transcript == "mute mic"
    assert context.voice.tts_available is True
    assert service.last_audio_path is not None
    assert not service.last_audio_path.exists()


def test_voice_commands_screen_select_in_simulation_still_uses_local_capture() -> None:
    """Simulation mode should mirror the screen only and still use Pi-side capture."""

    class _FakeDisplay:
        simulate = True

    context = AppContext()
    service = _FakeVoiceService("call mom")
    screen = VoiceCommandsScreen(
        display=_FakeDisplay(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _settings: service,
    )

    screen.on_select()

    assert service.capture_calls == 1
    assert context.voice.last_transcript == "call mom"
    assert service.last_audio_path is not None
    assert not service.last_audio_path.exists()


def test_voice_commands_screen_fallback_settings_keep_configured_voice_defaults() -> None:
    """Missing providers should still inherit configured backend/model voice settings."""

    context = AppContext()
    context.configure_voice(commands_enabled=True, ai_requests_enabled=True, screen_read_enabled=True)
    context.set_mic_muted(True)
    context.set_volume(77)
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager([]),
    )

    settings = screen._voice_settings()

    assert settings.commands_enabled is True
    assert settings.ai_requests_enabled is True
    assert settings.screen_read_enabled is True
    assert settings.stt_backend == "dummy-stt"
    assert settings.tts_backend == "dummy-tts"
    assert settings.vosk_model_path == "models/custom-model"
    assert settings.capture_device_id is None
    assert settings.sample_rate_hz == 22050
    assert settings.record_seconds == 6
    assert settings.tts_rate_wpm == 180
    assert settings.tts_voice == "en-us"
    assert settings.output_volume == 77
    assert settings.mic_muted is True


def test_voice_commands_screen_ignores_stale_results_after_back() -> None:
    """Leaving the screen should invalidate late transcripts from the old listen cycle."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = VoiceCommandsScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    screen._capture_in_flight = True
    screen._listen_generation = 7
    generation = screen._listen_generation

    screen.on_back()
    screen._dispatch_listen_result("call mom", capture_failed=False, generation=generation)

    assert voip_manager.make_calls == []
    assert context.voice.last_transcript == ""
