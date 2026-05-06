#!/usr/bin/env python3
"""Routing-focused tests for the declarative screen navigation layer."""

from __future__ import annotations

import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Callable

import pytest

from yoyopod.core import AppContext
from yoyopod.core.loop import RuntimeLoopService
from yoyopod.ui.display import Display
from yoyopod.ui.input import InputAction, InputManager
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.manager import ScreenManager, VisibleTickRefreshResult
from yoyopod.ui.screens.navigation.ask import AskScreen
from yoyopod.ui.screens.navigation.home import HomeScreen
from yoyopod.ui.screens.navigation.hub import HubScreen
from yoyopod.ui.screens.navigation.menu import MenuScreen
from yoyopod.ui.screens.router import NavigationRequest, ScreenRouter
from yoyopod.integrations.voice import (
    VoiceCaptureResult,
    VoiceSettings,
    VoiceTranscript,
)


class RoutableStubScreen(Screen):
    """Minimal screen double that can emit simple route requests."""

    def __init__(self, display: Display, context: AppContext | None = None) -> None:
        super().__init__(display, context, "RoutableStub")

    def render(self) -> None:
        """No-op render used by routing tests."""

    def on_back(self, data=None) -> None:
        """Request a standard back route."""
        self.request_route("back")


class HookAwareStubScreen(Screen):
    """Minimal screen double that exposes refresh-hook counters."""

    def __init__(
        self,
        display: Display,
        context: AppContext | None = None,
        *,
        keep_visible_tick_dirty: bool = True,
    ) -> None:
        super().__init__(display, context, "HookAwareStub")
        self.render_calls = 0
        self.refresh_for_visible_tick_calls = 0
        self.keep_visible_tick_dirty = keep_visible_tick_dirty

    def render(self) -> None:
        """Count renders performed by the screen manager."""
        self.render_calls += 1

    def refresh_for_visible_tick(self) -> None:
        """Count visible-tick refreshes before render."""
        self.refresh_for_visible_tick_calls += 1
        if self.keep_visible_tick_dirty:
            self.mark_dirty()

    @staticmethod
    def wants_visible_tick_refresh() -> bool:
        """Opt into the shared visible-tick refresh path."""

        return True


class FakeLvglPumpBackend:
    """Minimal LVGL backend double for runtime-pump tests."""

    def __init__(self) -> None:
        self.initialized = True
        self.pump_calls: list[int] = []

    def pump(self, delta_ms: int) -> None:
        self.pump_calls.append(delta_ms)


class FakeLvglPumpApp:
    """Small app double that exposes only the LVGL pump dependencies."""

    def __init__(
        self,
        *,
        screen_manager: ScreenManager,
        backend: FakeLvglPumpBackend,
        overlay_runtime: object | None = None,
    ) -> None:
        self.screen_manager = screen_manager
        self._lvgl_backend = backend
        self._lvgl_input_bridge = None
        self._last_lvgl_pump_at = 0.0
        self._voip_iterate_interval_seconds = 0.02
        self.cross_screen_overlays = overlay_runtime
        self.app_state_runtime = None
        self.bus = SimpleNamespace(pending_count=lambda: 0)
        self.scheduler = SimpleNamespace(pending_count=lambda: 0)

    def _pending_main_thread_callback_count(self) -> int:
        return 0


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


def test_ask_router_supports_safe_voice_route_actions() -> None:
    from yoyopod.ui.screens.router import ScreenRouter

    router = ScreenRouter()

    assert router.resolve("ask", "open_talk").target == "call"
    assert router.resolve("ask", "open_listen").target == "listen"
    assert router.resolve("ask", "open_setup").target == "power"
    assert router.resolve("ask", "go_home").operation == "replace"
    assert router.resolve("ask", "go_home").target == "hub"


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
    home.render = lambda: None
    menu.render = lambda: None

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
    menu.render = lambda: None

    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("power", power)

    screen_manager.replace_screen("menu")
    input_manager.simulate_action(InputAction.SELECT)

    assert screen_manager.current_screen is power


def test_screen_manager_routes_visible_screen_renders_through_refresh_hook(
    display: Display,
) -> None:
    """Push/pop/replace should invoke the visible-screen refresh hook before render."""

    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    menu = RoutableStubScreen(display, context)
    power = HookAwareStubScreen(display, context)
    other = RoutableStubScreen(display, context)

    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("power", power)
    screen_manager.register_screen("other", other)

    screen_manager.replace_screen("power")

    assert power.render_calls == 1
    assert power.refresh_for_visible_tick_calls == 1

    screen_manager.push_screen("other")
    screen_manager.pop_screen()

    assert power.render_calls == 2
    assert power.refresh_for_visible_tick_calls == 2


def test_screen_manager_only_refreshes_visible_ticks_for_opted_in_screen(
    display: Display,
) -> None:
    """Visible-tick refreshes should only render screens that opt into them."""

    context = AppContext()
    screen_manager = ScreenManager(display, input_manager=None)
    menu = RoutableStubScreen(display, context)
    power = HookAwareStubScreen(display, context)

    screen_manager.register_screen("menu", menu)
    screen_manager.register_screen("power", power)

    screen_manager.replace_screen("menu")
    assert (
        screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.NOT_ELIGIBLE
    )

    screen_manager.replace_screen("power")
    assert (
        screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.RENDERED
    )
    assert power.render_calls == 2
    assert power.refresh_for_visible_tick_calls == 2


def test_screen_manager_skips_visible_tick_render_when_screen_stays_clean(
    display: Display,
) -> None:
    """Visible ticks should skip opted-in screens that do not mark themselves dirty."""

    context = AppContext()
    screen_manager = ScreenManager(display, input_manager=None)
    power = HookAwareStubScreen(display, context, keep_visible_tick_dirty=False)

    screen_manager.register_screen("power", power)
    screen_manager.replace_screen("power")

    assert power.render_calls == 1
    assert power.refresh_for_visible_tick_calls == 1
    assert (
        screen_manager.refresh_current_screen_for_visible_tick() is VisibleTickRefreshResult.CLEAN
    )
    assert power.render_calls == 1
    assert power.refresh_for_visible_tick_calls == 2


def test_lvgl_navigation_refresh_waits_for_runtime_pump() -> None:
    """LVGL-backed navigation should defer its first visible render to the pump phase."""

    display = SimpleNamespace(backend_kind="lvgl")
    screen_manager = ScreenManager(display, input_manager=None)
    power = HookAwareStubScreen(display, AppContext())

    screen_manager.register_screen("power", power)
    screen_manager.replace_screen("power")

    assert power.render_calls == 0
    assert power.refresh_for_visible_tick_calls == 0

    backend = FakeLvglPumpBackend()
    runtime_loop = RuntimeLoopService(
        FakeLvglPumpApp(screen_manager=screen_manager, backend=backend)
    )

    runtime_loop.pump_lvgl_backend(now=10.0)

    assert power.render_calls == 1
    assert power.refresh_for_visible_tick_calls == 1
    assert backend.pump_calls == [0]


def test_lvgl_navigation_burst_coalesces_to_one_render_on_runtime_pump() -> None:
    """Repeated LVGL navigation before the next pump should render only the final screen once."""

    display = SimpleNamespace(backend_kind="lvgl")
    screen_manager = ScreenManager(display, input_manager=None)
    home = HookAwareStubScreen(display, AppContext())
    other = HookAwareStubScreen(display, AppContext())

    screen_manager.register_screen("home", home)
    screen_manager.register_screen("other", other)
    screen_manager.replace_screen("home")

    backend = FakeLvglPumpBackend()
    runtime_loop = RuntimeLoopService(
        FakeLvglPumpApp(screen_manager=screen_manager, backend=backend)
    )

    runtime_loop.pump_lvgl_backend(now=10.0)
    assert home.render_calls == 1
    assert other.render_calls == 0

    screen_manager.push_screen("other")
    screen_manager.pop_screen()

    assert home.render_calls == 1
    assert other.render_calls == 0

    runtime_loop.pump_lvgl_backend(now=10.1)

    assert home.render_calls == 2
    assert home.refresh_for_visible_tick_calls == 2
    assert other.render_calls == 0
    assert len(backend.pump_calls) == 2
    assert backend.pump_calls[0] == 0
    assert backend.pump_calls[1] > 0


def test_lvgl_pump_runs_overlay_runtime_between_navigation_flush_and_backend_pump() -> None:
    """Cross-screen overlays should render in the LVGL pump before backend timer work."""

    events: list[str] = []

    class _OrderedScreen(HookAwareStubScreen):
        def render(self) -> None:
            events.append("screen")
            super().render()

    class _OverlayRuntimeStub:
        def render_active(self, now: float) -> bool:
            events.append("overlay")
            return False

    class _OrderedBackend(FakeLvglPumpBackend):
        def pump(self, delta_ms: int) -> None:
            events.append("backend")
            super().pump(delta_ms)

    display = SimpleNamespace(backend_kind="lvgl")
    screen_manager = ScreenManager(display, input_manager=None)
    screen = _OrderedScreen(display, AppContext())
    screen_manager.register_screen("power", screen)
    screen_manager.replace_screen("power")

    runtime_loop = RuntimeLoopService(
        FakeLvglPumpApp(
            screen_manager=screen_manager,
            backend=_OrderedBackend(),
            overlay_runtime=_OverlayRuntimeStub(),
        )
    )
    runtime_loop.pump_lvgl_backend(now=10.0)

    assert events[:3] == ["screen", "overlay", "backend"]


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
    hub.render = lambda: None

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
    hub.render = lambda: None

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("listen", listen)

    screen_manager.replace_screen("hub")
    input_manager.simulate_action(InputAction.SELECT)

    assert screen_manager.current_screen is hub
    assert len(scheduled_callbacks) == 1

    scheduled_callbacks.pop()()
    assert screen_manager.current_screen is listen


def test_ask_screen_state_transitions() -> None:
    """AskScreen should transition through idle -> listening -> thinking -> reply."""

    ask = AskScreen(display=object(), context=AppContext())
    assert ask._state == "idle"
    assert ask._headline == "YoYo"
    assert ask._body == "How can I help?"

    ask._set_state("listening", "Listening", "Speak now...")
    assert ask._state == "listening"

    ask._set_state("thinking", "Thinking", "Just a moment...")
    assert ask._state == "thinking"

    ask._set_response("Volume", "Volume is 75.")
    assert ask._state == "reply"
    assert ask._headline == "Volume"
    assert ask._body == "Volume is 75."


def test_ask_screen_back_pops() -> None:
    """Back from any Ask state should pop the screen."""

    ask = AskScreen(display=object(), context=AppContext())
    ask.on_back()
    assert ask.consume_navigation_request() == NavigationRequest.route("back")


class _DeferredScheduler:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def post(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _StubVoiceRuntime:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            phase="idle",
            headline="YoYo",
            body="How can I help?",
            capture_in_flight=False,
            ptt_active=False,
            generation=0,
        )
        self.begin_entry_cycle_calls: list[tuple[bool, bool]] = []
        self.begin_ask_calls: list[bool] = []
        self.reset_conversation_calls = 0
        self.begin_listening_calls: list[bool] = []

    def bind(self, **_: object) -> None:
        return

    def cancel(self) -> None:
        return

    def begin_entry_cycle(self, *, quick_command: bool, async_capture: bool) -> None:
        self.begin_entry_cycle_calls.append((quick_command, async_capture))

    def begin_ask(self, *, async_capture: bool) -> None:
        self.begin_ask_calls.append(async_capture)

    def reset_conversation(self) -> None:
        self.reset_conversation_calls += 1

    def begin_listening(self, *, async_capture: bool) -> None:
        self.begin_listening_calls.append(async_capture)

    def finish_ptt_capture(self) -> None:
        return

    def handle_transcript(self, transcript: str) -> None:
        return

    def settings(self) -> VoiceSettings:
        return VoiceSettings()

    def defaults(self) -> VoiceSettings:
        return VoiceSettings()


def test_ask_screen_defers_entry_cycle_when_scheduler_is_available() -> None:
    """Ask entry should render first and queue auto-listen to the next main-thread turn."""

    scheduler = _DeferredScheduler()
    runtime = _StubVoiceRuntime()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        app=SimpleNamespace(scheduler=scheduler),
        voice_runtime=runtime,
    )
    manager = SimpleNamespace(current_screen=ask, action_scheduler=None)
    ask.set_screen_manager(manager)

    ask.enter()

    assert runtime.begin_entry_cycle_calls == []
    assert len(scheduler.callbacks) == 1

    scheduler.callbacks.pop()()

    assert runtime.begin_entry_cycle_calls == [(False, True)]


def test_ask_screen_skips_deferred_entry_cycle_after_navigation_away() -> None:
    """Deferred auto-listen should not start after Ask stops being the current screen."""

    scheduler = _DeferredScheduler()
    runtime = _StubVoiceRuntime()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        app=SimpleNamespace(scheduler=scheduler),
        voice_runtime=runtime,
    )
    manager = SimpleNamespace(current_screen=ask, action_scheduler=None)
    ask.set_screen_manager(manager)

    ask.enter()
    manager.current_screen = object()
    scheduler.callbacks.pop()()

    assert runtime.begin_entry_cycle_calls == []


def test_ask_screen_select_starts_normal_ask_by_default() -> None:
    """Selecting normal Ask should use the conversational Ask runtime path."""

    runtime = _StubVoiceRuntime()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        voice_runtime=runtime,
    )

    ask.on_select()

    assert runtime.begin_ask_calls == [True]
    assert runtime.begin_listening_calls == []


def test_ask_screen_select_starts_quick_command_listening() -> None:
    """Selecting quick-command Ask should preserve direct command listening."""

    runtime = _StubVoiceRuntime()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        voice_runtime=runtime,
    )
    ask.set_quick_command(True)

    ask.on_select()

    assert runtime.begin_listening_calls == [True]
    assert runtime.begin_ask_calls == []


def test_ask_screen_summary_matches_entry_mode() -> None:
    """Screen-read summaries should describe the active Ask entry mode."""

    ask = AskScreen(display=object(), context=AppContext(), voice_runtime=_StubVoiceRuntime())

    assert ask._screen_summary() == "You are on YoYo. Ask a question or say a command."

    ask.set_quick_command(True)

    assert ask._screen_summary() == "You are using YoYo. Say a command or question now."


def test_ask_screen_uses_yoyo_surface_copy() -> None:
    ask = AskScreen(display=object(), context=AppContext(), voice_runtime=_StubVoiceRuntime())

    ask._on_voice_runtime_state_changed(
        SimpleNamespace(
            phase="idle",
            headline="YoYo",
            body="How can I help?",
            capture_in_flight=False,
            ptt_active=False,
            generation=0,
        )
    )

    assert ask.current_view_model()[0] == "YoYo"
    assert ask.current_view_model()[1] == "How can I help?"


def test_ask_screen_exit_resets_conversation() -> None:
    """Leaving Ask should clear the shared conversation context."""

    runtime = _StubVoiceRuntime()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        voice_runtime=runtime,
    )

    ask.exit()

    assert runtime.reset_conversation_calls == 1


class _FakeContact:
    def __init__(self, name: str, sip_address: str, notes: str = "") -> None:
        self.name = name
        self.sip_address = sip_address
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


class _FakeConfigManager:
    def __init__(self, contacts: list[_FakeContact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[_FakeContact]:
        return self._contacts

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[_FakeContact]:
        return [
            contact
            for contact in self._contacts
            if contact.preferred_call_target(gsm_enabled=gsm_enabled)[0]
        ]

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
                sample_rate_hz=22050,
                record_seconds=6,
                tts_rate_wpm=180,
                tts_voice="en-us",
            )
        )

    def get_default_output_volume(self) -> int:
        return 61


class _FakeConfigManagerWithSpeaker(_FakeConfigManager):
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
                speaker_device_id="plughw:CARD=wm8960soundcard,DEV=0",
                capture_device_id="plughw:CARD=wm8960soundcard,DEV=0",
                sample_rate_hz=22050,
                record_seconds=6,
                tts_rate_wpm=180,
                tts_voice="en-us",
            )
        )

    def get_ring_output_device(self) -> str:
        return "wm8960-soundcard"


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

    def transcribe(self, audio_path, *, cancel_event=None) -> VoiceTranscript:
        return VoiceTranscript(text=self.transcript, confidence=0.92)

    def match_command(self, transcript: str):
        from yoyopod.integrations.voice.commands import match_voice_command

        return match_voice_command(transcript)

    def speak(self, text: str) -> bool:
        self.speak_calls.append(text)
        return True


class _NoAudioVoiceService(_FakeVoiceService):
    def __init__(self) -> None:
        super().__init__("")

    def capture_audio(self, request) -> VoiceCaptureResult:
        self.capture_calls += 1
        return VoiceCaptureResult(audio_path=None, recorded=False)


def test_ask_screen_applies_local_device_actions() -> None:
    """Voice commands should update mic and volume state through local hooks."""

    context = AppContext()
    context.settings["max_volume"] = 55
    volume_up_calls: list[int] = []
    voip_manager = _FakeVoipManager()
    screen = AskScreen(
        display=object(),
        context=context,
        voip_manager=voip_manager,
        volume_up_action=lambda step: volume_up_calls.append(step) or 55,
        mute_action=voip_manager.mute,
        unmute_action=voip_manager.unmute,
    )

    screen.on_voice_command({"transcript": "volume up"})
    assert volume_up_calls == [1]
    assert context.voice.last_spoken_text == "Volume is 10 out of 10."

    screen.on_voice_command({"transcript": "mute mic"})
    assert context.voice.mic_muted is True
    assert voip_manager.mute_calls == 1
    assert context.voice.last_spoken_text == "Voice commands mic is muted."

    screen.on_voice_command({"transcript": "unmute mic"})
    assert context.voice.mic_muted is False
    assert voip_manager.unmute_calls == 1
    assert context.voice.last_spoken_text == "Voice commands mic is live."


def test_ask_screen_can_resolve_dependencies_from_app() -> None:
    """AskScreen should resolve call, music, and volume hooks from the owning app seam."""

    context = AppContext()
    context.settings["max_volume"] = 55
    volume_up_calls: list[int] = []
    voip_manager = _FakeVoipManager()
    app = SimpleNamespace(
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        people_directory=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
        audio_volume_controller=SimpleNamespace(
            volume_up=lambda step: volume_up_calls.append(step) or 55,
            volume_down=lambda _step: 45,
        ),
        local_music_service=SimpleNamespace(shuffle_all=lambda: True),
    )
    screen = AskScreen(
        display=object(),
        context=context,
        app=app,
    )

    screen.on_voice_command({"transcript": "call mom"})
    assert context.talk.selected_contact_name == "Mama"
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]

    screen.on_voice_command({"transcript": "play music"})
    assert screen.consume_navigation_request() == NavigationRequest.route("shuffle_started")

    screen.on_voice_command({"transcript": "volume up"})
    assert volume_up_calls == [1]
    assert context.voice.last_spoken_text == "Volume is 10 out of 10."


def test_ask_screen_can_start_music_from_local_hook() -> None:
    """Basic play-music commands should route into the local music flow."""

    screen = AskScreen(
        display=object(),
        context=AppContext(),
        play_music_action=lambda: True,
    )

    screen.on_voice_command({"transcript": "play music"})

    assert screen.consume_navigation_request() == NavigationRequest.route("shuffle_started")


def test_ask_screen_can_place_call_for_named_contact() -> None:
    """Call commands should resolve labels and let call-state events own navigation."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = AskScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        people_directory=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    screen.on_voice_command({"transcript": "call mama"})

    assert context.talk.selected_contact_name == "Mama"
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]
    assert screen.consume_navigation_request() is None
    assert screen._auto_return_timer is None


def test_ask_screen_can_place_call_for_parent_aliases() -> None:
    """Parent aliases should not force a local navigation request for call start."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = AskScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [
                _FakeContact("Hagar", "sip:mama@example.com", notes="Mama"),
                _FakeContact("Moustafa", "sip:dad@example.com", notes="Dad"),
            ]
        ),
        people_directory=_FakeConfigManager(
            [
                _FakeContact("Hagar", "sip:mama@example.com", notes="Mama"),
                _FakeContact("Moustafa", "sip:dad@example.com", notes="Dad"),
            ]
        ),
        voip_manager=voip_manager,
    )

    screen.on_voice_command({"transcript": "call mom"})
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]
    assert screen.consume_navigation_request() is None
    assert screen._auto_return_timer is None

    screen.on_voice_command({"transcript": "call dad"})
    assert voip_manager.make_calls[-1] == ("sip:dad@example.com", "Dad")
    assert screen.consume_navigation_request() is None
    assert screen._auto_return_timer is None


def test_ask_screen_default_voice_settings_keep_saved_speaker_device() -> None:
    """Fallback voice settings should preserve the saved speaker route for TTS playback."""

    screen = AskScreen(
        display=object(),
        context=AppContext(),
        config_manager=_FakeConfigManagerWithSpeaker([]),
    )

    settings = screen._default_voice_settings()

    assert settings.speaker_device_id == "plughw:CARD=wm8960soundcard,DEV=0"
    assert settings.capture_device_id == "plughw:CARD=wm8960soundcard,DEV=0"


def test_ask_screen_select_can_capture_and_execute_command() -> None:
    """Selecting command mode should capture speech and execute the transcript."""

    context = AppContext()
    service = _FakeVoiceService("mute mic")
    screen = AskScreen(
        display=object(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _settings: service,
    )
    screen.set_quick_command(True)

    screen.on_select()

    assert service.capture_calls == 1
    assert context.voice.mic_muted is True
    assert context.voice.last_transcript == "mute mic"
    assert context.voice.tts_available is True
    assert service.last_audio_path is not None
    assert not service.last_audio_path.exists()


def test_ask_screen_select_in_simulation_still_uses_local_capture() -> None:
    """Simulation mode should mirror the screen only and still use Pi-side capture."""

    class _FakeDisplay:
        simulate = True

    context = AppContext()
    service = _FakeVoiceService("call mom")
    screen = AskScreen(
        display=_FakeDisplay(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _settings: service,
    )
    screen.set_quick_command(True)

    screen.on_select()

    assert service.capture_calls == 1
    assert context.voice.last_transcript == "call mom"
    assert service.last_audio_path is not None
    assert not service.last_audio_path.exists()


def test_ask_screen_fallback_settings_keep_configured_voice_defaults() -> None:
    """Missing providers should still inherit configured backend/model voice settings."""

    context = AppContext()
    context.configure_voice(
        commands_enabled=True, ai_requests_enabled=True, screen_read_enabled=True
    )
    context.set_mic_muted(True)
    context.set_volume(77)
    screen = AskScreen(
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
    assert settings.capture_device_id is None
    assert settings.sample_rate_hz == 22050
    assert settings.record_seconds == 6
    assert settings.tts_rate_wpm == 180
    assert settings.tts_voice == "en-us"
    assert settings.output_volume == 77
    assert settings.mic_muted is True


def test_ask_screen_ignores_stale_results_after_back() -> None:
    """Leaving the screen should invalidate late transcripts from the old listen cycle."""

    context = AppContext()
    voip_manager = _FakeVoipManager()
    screen = AskScreen(
        display=object(),
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        people_directory=_FakeConfigManager(
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


def test_ask_screen_quick_command_skips_idle() -> None:
    """Quick-command mode should skip idle and go straight to listening."""
    context = AppContext()
    service = _FakeVoiceService("volume up")
    ask = AskScreen(
        display=object(),
        context=context,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _s: service,
    )
    ask.set_quick_command(True)
    ask.enter()
    assert ask._state == "listening"
    assert ask._ptt_active is True
    assert ask._quick_command is True


def test_ask_screen_ptt_release_stops_capture() -> None:
    """PTT_RELEASE should stop the capture."""
    context = AppContext()
    service = _FakeVoiceService("volume up")
    ask = AskScreen(
        display=object(),
        context=context,
        volume_up_action=lambda step: 55,
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _s: service,
    )
    ask.set_quick_command(True)
    ask.enter()
    ask.on_ptt_release({"after_hold": True})
    assert ask._ptt_active is False
    assert ask._state == "thinking"
    assert ask._headline == "Thinking"
    assert ask._body == "Just a moment..."


def test_ask_screen_listening_view_model_keeps_ask_icon() -> None:
    """Listening should keep the Ask icon so LVGL matches the Figma shell."""

    ask = AskScreen(display=object(), context=AppContext())
    ask._set_state("listening", "Listening", "Speak now...")

    title, subtitle, footer, icon_key = ask.current_view_model()

    assert title == "Listening"
    assert subtitle == "Speak now..."
    assert footer == "Listening..."
    assert icon_key == "ask"


def test_ask_screen_ptt_release_without_audio_resolves_to_no_speech() -> None:
    """A released PTT capture with no WAV should not leave Ask stuck in thinking."""

    service = _NoAudioVoiceService()
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _s: service,
    )
    ask.set_quick_command(True)
    ask._capture_in_flight = True
    ask._ptt_active = False
    ask._listen_generation = 7

    ask._run_ptt_listening_cycle(service, 7, threading.Event())

    assert ask._capture_in_flight is False
    assert ask._state == "reply"
    assert ask._headline == "No Speech"
    assert ask._auto_return_timer is not None
    ask._cancel_auto_return()


def test_ask_screen_auto_return_only_in_quick_command() -> None:
    """Auto-return should only schedule in quick-command mode."""
    ask = AskScreen(display=object(), context=AppContext())
    ask._quick_command = False
    ask._schedule_auto_return()
    assert ask._auto_return_timer is None

    ask._quick_command = True
    ask._schedule_auto_return()
    assert ask._auto_return_timer is not None
    ask._cancel_auto_return()


def test_ask_screen_quick_command_errors_schedule_auto_return() -> None:
    """Quick-command failures should still auto-return after showing the reply."""

    context = AppContext()
    context.configure_voice(
        commands_enabled=False, ai_requests_enabled=True, screen_read_enabled=True
    )
    ask = AskScreen(display=object(), context=context)

    ask.set_quick_command(True)
    ask.enter()

    assert ask._state == "reply"
    assert ask._headline == "Voice Off"
    assert ask._auto_return_timer is not None
    ask._cancel_auto_return()


def test_ask_screen_quick_command_distinguishes_missing_stt_model() -> None:
    """Hold-to-ask should report Speech Offline when STT is unavailable."""

    class _NoSttVoiceService(_FakeVoiceService):
        def stt_available(self) -> bool:
            return False

    service = _NoSttVoiceService("volume up")
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        voice_settings_provider=lambda: VoiceSettings(),
        voice_service_factory=lambda _settings: service,
    )

    ask.set_quick_command(True)
    ask.enter()

    assert ask._state == "reply"
    assert ask._headline == "Speech Offline"
    assert ask._auto_return_timer is not None
    ask._cancel_auto_return()


def test_ask_screen_applies_route_requests_immediately_off_input_path() -> None:
    """Quick-command results should apply their routes without waiting for another tap."""

    applied_requests: list[tuple[NavigationRequest, AskScreen | None]] = []
    manager = SimpleNamespace(
        action_scheduler=None,
        apply_navigation_request=lambda request, source_screen=None: applied_requests.append(
            (request, source_screen)
        )
        or True,
        get_current_screen=lambda: ask,
        refresh_current_screen=lambda: None,
    )
    ask = AskScreen(
        display=object(),
        context=AppContext(),
        play_music_action=lambda: True,
    )
    ask.set_screen_manager(manager)
    ask.set_route_name("ask")
    ask._listen_generation = 3

    ask._dispatch_listen_result("play music", capture_failed=False, generation=3)

    assert applied_requests == [(NavigationRequest.route("shuffle_started"), ask)]
    assert ask.consume_navigation_request() is None
    assert ask._auto_return_timer is None


def test_ask_screen_auto_pop_applies_back_route_immediately() -> None:
    """Auto-pop should apply the back route instead of leaving it pending."""

    applied_requests: list[tuple[NavigationRequest, AskScreen | None]] = []
    ask = AskScreen(display=object(), context=AppContext())
    ask.set_quick_command(True)
    manager = SimpleNamespace(
        action_scheduler=None,
        get_current_screen=lambda: ask,
        apply_navigation_request=lambda request, source_screen=None: applied_requests.append(
            (request, source_screen)
        )
        or True,
    )
    ask.set_screen_manager(manager)
    ask.set_route_name("ask")

    ask._auto_pop()

    assert applied_requests == [(NavigationRequest.route("back"), ask)]
    assert ask.consume_navigation_request() is None


def test_ask_screen_auto_pop_ignores_stale_timer_tokens() -> None:
    """A stale timer callback should not pop a newer Ask session."""

    applied_requests: list[tuple[NavigationRequest, AskScreen | None]] = []
    ask = AskScreen(display=object(), context=AppContext())
    ask.set_quick_command(True)
    manager = SimpleNamespace(
        action_scheduler=None,
        get_current_screen=lambda: ask,
        apply_navigation_request=lambda request, source_screen=None: applied_requests.append(
            (request, source_screen)
        )
        or True,
    )
    ask.set_screen_manager(manager)
    ask.set_route_name("ask")

    ask._schedule_auto_return()
    stale_token = ask._auto_return_token
    ask._cancel_auto_return()
    ask.set_quick_command(True)

    ask._auto_pop(stale_token)

    assert applied_requests == []
    assert ask.consume_navigation_request() is None


def test_ask_screen_exit_clears_quick_command() -> None:
    """Exiting the screen should reset the quick-command flag."""
    ask = AskScreen(display=object(), context=AppContext())
    ask._quick_command = True
    ask.exit()
    assert ask._quick_command is False


def test_hub_back_triggers_full_ask_route(display: Display) -> None:
    """Holding on Hub should open the same command-plus-Ask flow as Ask itself."""
    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)
    runtime = _StubVoiceRuntime()

    hub = HubScreen(display, context)
    ask = AskScreen(display=display, context=context, voice_runtime=runtime)
    hub.render = lambda: None
    ask.render = lambda: None

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("ask", ask)
    screen_manager.replace_screen("hub")

    input_manager.simulate_action(InputAction.BACK)

    assert screen_manager.current_screen is ask
    assert ask._quick_command is False
    assert runtime.begin_entry_cycle_calls == [(False, True)]


def test_hub_select_clears_stale_quick_command_for_normal_ask(display: Display) -> None:
    """Selecting Ask from the hub should open the normal Ask flow, not stale hold-to-ask mode."""

    context = AppContext()
    input_manager = InputManager()
    screen_manager = ScreenManager(display, input_manager)

    hub = HubScreen(display, context)
    ask = AskScreen(display=display, context=context)
    hub.render = lambda: None
    ask.render = lambda: None

    screen_manager.register_screen("hub", hub)
    screen_manager.register_screen("ask", ask)
    screen_manager.replace_screen("hub")

    ask.set_quick_command(True)
    hub.selected_index = 2
    input_manager.simulate_action(InputAction.SELECT)

    assert screen_manager.current_screen is ask
    assert ask._quick_command is False
