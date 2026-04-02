"""Coordinator tests for the event bus and split FSM orchestration path."""

from __future__ import annotations

import threading

import pytest

from yoyopy.app import YoyoPodApp
from yoyopy.app_context import AppContext
from yoyopy.connectivity import CallState, RegistrationState
from yoyopy.coordinators.runtime import AppRuntimeState
from yoyopy.events import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    PlaybackStateChangedEvent,
    RegistrationChangedEvent,
    TrackChangedEvent,
)
from yoyopy.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)


class FakeScreen:
    """Minimal screen double for coordinator tests."""

    def __init__(self) -> None:
        self.render_calls = 0

    def render(self) -> None:
        self.render_calls += 1


class FakeIncomingCallScreen(FakeScreen):
    """Incoming call screen double with mutable caller fields."""

    def __init__(self) -> None:
        super().__init__()
        self.caller_address = ""
        self.caller_name = "Unknown"
        self.ring_animation_frame = 0


class FakeScreenManager:
    """Simple stack-based screen manager double."""

    def __init__(self, screen_lookup: dict[str, object]) -> None:
        self.screen_lookup = screen_lookup
        self.screen_stack: list[object] = []
        self.current_screen: object | None = None

    def push_screen(self, name: str) -> None:
        screen = self.screen_lookup[name]
        self.screen_stack.append(screen)
        self.current_screen = screen

    def pop_screen(self) -> None:
        if self.screen_stack:
            self.screen_stack.pop()
        self.current_screen = self.screen_stack[-1] if self.screen_stack else None


class FakeMopidyClient:
    """Minimal Mopidy double used by the coordinator tests."""

    def __init__(self, playback_state: str) -> None:
        self.playback_state = playback_state
        self.pause_calls = 0
        self.play_calls = 0
        self.is_connected = True

    def get_playback_state(self) -> str:
        return self.playback_state

    def pause(self) -> bool:
        self.pause_calls += 1
        self.playback_state = "paused"
        return True

    def play(self) -> bool:
        self.play_calls += 1
        self.playback_state = "playing"
        return True


def _publish_from_worker(app: YoyoPodApp, event: object) -> None:
    worker = threading.Thread(target=lambda: app.event_bus.publish(event))
    worker.start()
    worker.join()


def _build_app(playback_state: str = "stopped", auto_resume: bool = True) -> tuple[
    YoyoPodApp,
    FakeMopidyClient,
    FakeScreenManager,
]:
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.music_fsm = MusicFSM()
    app.call_fsm = CallFSM()
    app.call_interruption_policy = CallInterruptionPolicy()
    app.auto_resume_after_call = auto_resume
    app.voip_registered = False

    mopidy = FakeMopidyClient(playback_state=playback_state)
    app.mopidy_client = mopidy

    app.menu_screen = FakeScreen()
    app.now_playing_screen = FakeScreen()
    app.call_screen = FakeScreen()
    app.incoming_call_screen = FakeIncomingCallScreen()
    app.outgoing_call_screen = FakeScreen()
    app.in_call_screen = FakeScreen()

    screen_manager = FakeScreenManager(
        {
            "menu": app.menu_screen,
            "incoming_call": app.incoming_call_screen,
            "outgoing_call": app.outgoing_call_screen,
            "in_call": app.in_call_screen,
        }
    )
    app.screen_manager = screen_manager
    app.screen_manager.push_screen("menu")
    app._ui_state = AppRuntimeState.MENU

    app._setup_event_subscriptions()
    app.call_coordinator.start_ringing = lambda: None
    app.call_coordinator.stop_ringing = lambda: None
    return app, mopidy, screen_manager


def test_incoming_call_pauses_playing_music_once() -> None:
    """Incoming call events should pause active playback exactly once."""
    app, mopidy, screen_manager = _build_app(playback_state="playing")
    app.music_fsm.transition("play")
    app.coordinator_runtime.sync_app_state("playback_playing")

    _publish_from_worker(
        app,
        IncomingCallEvent(caller_address="sip:alice@example.com", caller_name="Alice"),
    )

    assert mopidy.pause_calls == 0
    assert app.event_bus.drain() == 1
    assert mopidy.pause_calls == 1
    assert app.music_fsm.state == MusicState.PAUSED
    assert app.call_fsm.state == CallSessionState.INCOMING
    assert app.call_interruption_policy.music_interrupted_by_call
    assert screen_manager.current_screen is app.incoming_call_screen
    assert app.incoming_call_screen.caller_name == "Alice"

    _publish_from_worker(
        app,
        IncomingCallEvent(caller_address="sip:alice@example.com", caller_name="Alice"),
    )

    assert app.event_bus.drain() == 1
    assert mopidy.pause_calls == 1
    assert len(screen_manager.screen_stack) == 2


def test_call_end_auto_resumes_only_when_enabled() -> None:
    """Call end should auto-resume only when playback was interrupted and enabled."""
    app, mopidy, screen_manager = _build_app(playback_state="paused", auto_resume=True)
    app.music_fsm.sync(MusicState.PAUSED)
    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.call_interruption_policy.music_interrupted_by_call = True
    app.coordinator_runtime.sync_app_state("test_setup")
    screen_manager.push_screen("incoming_call")
    screen_manager.push_screen("in_call")

    _publish_from_worker(app, CallEndedEvent())

    assert mopidy.play_calls == 0
    assert app.event_bus.drain() == 1
    assert mopidy.play_calls == 1
    assert app.music_fsm.state == MusicState.PLAYING
    assert app.call_fsm.state == CallSessionState.IDLE
    assert not app.call_interruption_policy.music_interrupted_by_call
    assert screen_manager.current_screen is app.menu_screen


def test_call_end_keeps_music_paused_when_auto_resume_disabled() -> None:
    """Call end should leave playback paused when auto-resume is off."""
    app, mopidy, screen_manager = _build_app(playback_state="paused", auto_resume=False)
    app.music_fsm.sync(MusicState.PAUSED)
    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.call_interruption_policy.music_interrupted_by_call = True
    app.coordinator_runtime.sync_app_state("test_setup")
    screen_manager.push_screen("incoming_call")
    screen_manager.push_screen("in_call")

    _publish_from_worker(app, CallEndedEvent())

    assert app.event_bus.drain() == 1
    assert mopidy.play_calls == 0
    assert app.music_fsm.state == MusicState.PAUSED
    assert app.call_fsm.state == CallSessionState.IDLE
    assert not app.call_interruption_policy.music_interrupted_by_call
    assert screen_manager.current_screen is app.menu_screen


@pytest.mark.parametrize(
    ("music_state", "playback_state"),
    [
        (MusicState.IDLE, "stopped"),
        (MusicState.PAUSED, "paused"),
    ],
)
def test_outgoing_call_does_not_change_idle_or_paused_music(
    music_state: MusicState,
    playback_state: str,
) -> None:
    """Outgoing call state changes should not mutate paused or idle music state."""
    app, _, _ = _build_app(playback_state=playback_state)
    app.music_fsm.sync(music_state)
    app.coordinator_runtime.sync_app_state("test_setup")

    _publish_from_worker(app, CallStateChangedEvent(state=CallState.OUTGOING))

    assert app.event_bus.drain() == 1
    assert app.call_fsm.state == CallSessionState.OUTGOING
    assert app.music_fsm.state == music_state


def test_background_events_wait_for_drain_before_mutating_state() -> None:
    """Registration and playback events should not mutate coordinator state until drained."""
    app, _, _ = _build_app(playback_state="stopped")

    _publish_from_worker(app, RegistrationChangedEvent(state=RegistrationState.OK))
    _publish_from_worker(app, PlaybackStateChangedEvent(state="playing"))

    assert not app.voip_registered
    assert app.music_fsm.state == MusicState.IDLE

    assert app.event_bus.drain() == 2
    assert app.voip_registered
    assert app.music_fsm.state == MusicState.PLAYING
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.PLAYING_WITH_VOIP


def test_track_event_refreshes_now_playing_screen_when_visible() -> None:
    """Track events should refresh the current now playing screen through the bus."""
    app, _, screen_manager = _build_app(playback_state="playing")
    screen_manager.current_screen = app.now_playing_screen
    app.music_fsm.transition("play")
    app.coordinator_runtime.sync_app_state("playback_playing")

    _publish_from_worker(app, TrackChangedEvent(track=None))

    assert app.now_playing_screen.render_calls == 0
    assert app.event_bus.drain() == 1
    assert app.now_playing_screen.render_calls == 1
    assert app.music_fsm.state == MusicState.IDLE
