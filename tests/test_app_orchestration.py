"""Coordinator tests for the event bus and split FSM orchestration path."""

from __future__ import annotations

import threading

import pytest

from yoyopy.app import YoyoPodApp
from yoyopy.app_context import AppContext
from yoyopy.voip import CallState, RegistrationState
from yoyopy.coordinators.runtime import AppRuntimeState
from yoyopy.events import (
    CallEndedEvent,
    CallStateChangedEvent,
    IncomingCallEvent,
    MusicAvailabilityChangedEvent,
    PlaybackStateChangedEvent,
    RecoveryAttemptCompletedEvent,
    RegistrationChangedEvent,
    TrackChangedEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopy.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)
from yoyopy.ui.input import InputManager, InteractionProfile


class FakeScreen:
    """Minimal screen double for coordinator tests."""

    def __init__(self) -> None:
        self.render_calls = 0
        self.route_name: str | None = None

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
        self.on_screen_changed = None

        for name, screen in screen_lookup.items():
            setattr(screen, "route_name", name)

    def push_screen(self, name: str) -> None:
        screen = self.screen_lookup[name]
        self.screen_stack.append(screen)
        self.current_screen = screen
        self._notify_screen_changed(name)

    def pop_screen(self) -> None:
        if self.screen_stack:
            self.screen_stack.pop()
        self.current_screen = self.screen_stack[-1] if self.screen_stack else None
        route_name = getattr(self.current_screen, "route_name", None)
        self._notify_screen_changed(route_name)

    def get_current_screen(self) -> object | None:
        return self.current_screen

    def _notify_screen_changed(self, route_name: str | None) -> None:
        if self.on_screen_changed is not None:
            self.on_screen_changed(route_name)


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


class FakeRecoveringVoIPManager:
    """Minimal VoIP manager double for app-level recovery tests."""

    def __init__(self, start_results: list[bool]) -> None:
        self._start_results = start_results
        self.start_calls = 0
        self.running = False

    def start(self) -> bool:
        self.start_calls += 1
        result_index = min(self.start_calls - 1, len(self._start_results) - 1)
        self.running = self._start_results[result_index]
        return self.running

    def stop(self, notify_events: bool = True) -> None:
        self.running = False


class FakeRecoveringMopidyClient:
    """Minimal Mopidy double for recovery backoff tests."""

    def __init__(self, connect_results: list[bool]) -> None:
        self._connect_results = connect_results
        self.connect_calls = 0
        self.start_polling_calls = 0
        self.is_connected = False
        self.polling = False

    def connect(self) -> bool:
        self.connect_calls += 1
        result_index = min(self.connect_calls - 1, len(self._connect_results) - 1)
        self.is_connected = self._connect_results[result_index]
        return self.is_connected

    def start_polling(self) -> None:
        self.polling = True
        self.start_polling_calls += 1


class FakeStoppingVoIPManager:
    """Minimal VoIP manager double for app shutdown tests."""

    def __init__(self) -> None:
        self.stop_notify_events: list[bool] = []

    def stop(self, notify_events: bool = True) -> None:
        self.stop_notify_events.append(notify_events)


def _publish_from_worker(app: YoyoPodApp, event: object) -> None:
    worker = threading.Thread(target=lambda: app.event_bus.publish(event))
    worker.start()
    worker.join()


def _navigate_from_worker(screen_manager: FakeScreenManager, screen_name: str) -> None:
    worker = threading.Thread(target=lambda: screen_manager.push_screen(screen_name))
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
    app.playlist_screen = FakeScreen()
    app.call_screen = FakeScreen()
    app.contact_list_screen = FakeScreen()
    app.incoming_call_screen = FakeIncomingCallScreen()
    app.outgoing_call_screen = FakeScreen()
    app.in_call_screen = FakeScreen()

    screen_manager = FakeScreenManager(
        {
            "menu": app.menu_screen,
            "playlists": app.playlist_screen,
            "contacts": app.contact_list_screen,
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


def test_periodic_in_call_refresh_only_renders_visible_call_screen() -> None:
    """Live in-call refreshes should come from the main loop, not a screen-owned thread."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    app._update_in_call_if_needed()
    assert app.in_call_screen.render_calls == 0

    screen_manager.push_screen("in_call")
    app._update_in_call_if_needed()
    assert app.in_call_screen.render_calls == 1

    screen_manager.pop_screen()
    app._update_in_call_if_needed()
    assert app.in_call_screen.render_calls == 1


def test_voip_unavailable_event_ends_call_and_restores_music() -> None:
    """VoIP backend loss should tear down the call flow and restore interrupted playback."""
    app, mopidy, screen_manager = _build_app(playback_state="paused", auto_resume=True)
    app.music_fsm.sync(MusicState.PAUSED)
    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.call_interruption_policy.music_interrupted_by_call = True
    app.coordinator_runtime.sync_app_state("test_setup")
    screen_manager.push_screen("in_call")

    _publish_from_worker(
        app,
        VoIPAvailabilityChangedEvent(available=False, reason="backend_stopped"),
    )

    assert app.event_bus.drain() == 1
    assert app.call_fsm.state == CallSessionState.IDLE
    assert app.music_fsm.state == MusicState.PLAYING
    assert mopidy.play_calls == 1
    assert screen_manager.current_screen is app.menu_screen


def test_music_unavailable_event_stops_music_and_refreshes_now_playing() -> None:
    """Mopidy loss should stop music state and refresh the visible now-playing screen."""
    app, _, screen_manager = _build_app(playback_state="playing")
    screen_manager.current_screen = app.now_playing_screen
    app.music_fsm.transition("play")
    app.coordinator_runtime.sync_app_state("playback_playing")

    _publish_from_worker(
        app,
        MusicAvailabilityChangedEvent(available=False, reason="connection_lost"),
    )

    assert app.event_bus.drain() == 1
    assert app.music_fsm.state == MusicState.IDLE
    assert app.now_playing_screen.render_calls == 1


def test_navigation_updates_runtime_base_state() -> None:
    """Idle navigation should keep the derived runtime state aligned with the active screen."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    screen_manager.push_screen("contacts")
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.CALL_IDLE

    screen_manager.pop_screen()
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.MENU

    screen_manager.push_screen("playlists")
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER


def test_worker_navigation_waits_for_coordinator_drain_before_syncing_state() -> None:
    """Screen-change callbacks from worker threads should queue runtime sync onto the event bus."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    _navigate_from_worker(screen_manager, "contacts")

    assert screen_manager.current_screen is app.contact_list_screen
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.MENU
    assert app.event_bus.drain() == 1
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.CALL_IDLE


def test_call_end_restores_previous_screen_base_state() -> None:
    """Ending a call should restore the derived state for the screen the user returns to."""
    app, _, screen_manager = _build_app(playback_state="stopped")
    screen_manager.push_screen("playlists")

    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.coordinator_runtime.sync_app_state("call_connected")
    screen_manager.push_screen("incoming_call")
    screen_manager.push_screen("in_call")

    _publish_from_worker(app, CallEndedEvent())

    assert app.event_bus.drain() == 1
    assert screen_manager.current_screen is app.playlist_screen
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER


def test_manager_recovery_schedules_mopidy_reconnect_off_main_thread() -> None:
    """Mopidy recovery should schedule work instead of blocking the coordinator loop."""
    app = YoyoPodApp(simulate=True)
    app.voip_manager = FakeRecoveringVoIPManager([False, True])
    app.mopidy_client = FakeRecoveringMopidyClient([False, True])
    scheduled_attempts: list[float] = []

    app._start_mopidy_recovery_worker = lambda recovery_now: scheduled_attempts.append(recovery_now)

    app._attempt_manager_recovery(now=0.0)

    assert app.voip_manager.start_calls == 1
    assert app.mopidy_client.connect_calls == 0
    assert scheduled_attempts == [0.0]
    assert app._mopidy_recovery.in_flight
    assert app._voip_recovery.next_attempt_at == 1.0


def test_mopidy_recovery_backoff_doubles_and_restarts_polling_after_success() -> None:
    """Background Mopidy recovery results should update backoff and restart polling."""
    app = YoyoPodApp(simulate=True)
    app.mopidy_client = FakeRecoveringMopidyClient([False, True])

    app._mopidy_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="mopidy", recovered=False, recovery_now=0.0)
    )

    assert app.mopidy_client.start_polling_calls == 0
    assert app._mopidy_recovery.next_attempt_at == 1.0
    assert app._mopidy_recovery.delay_seconds == 2.0

    app._mopidy_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="mopidy", recovered=False, recovery_now=1.0)
    )

    assert app._mopidy_recovery.next_attempt_at == 3.0
    assert app._mopidy_recovery.delay_seconds == 4.0

    app.mopidy_client.is_connected = True
    app._mopidy_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="mopidy", recovered=True, recovery_now=3.0)
    )

    assert app.mopidy_client.start_polling_calls == 1
    assert app._mopidy_recovery.next_attempt_at == 0.0
    assert app._mopidy_recovery.delay_seconds == 1.0


def test_app_stop_uses_silent_voip_teardown() -> None:
    """App shutdown should suppress VoIP teardown callbacks that could restart playback."""
    app, _, _ = _build_app(playback_state="paused", auto_resume=True)
    app.voip_manager = FakeStoppingVoIPManager()
    app.mopidy_client = None

    app.stop()

    assert app.voip_manager.stop_notify_events == [False]


def test_standard_profile_starts_on_menu() -> None:
    """Standard multi-button devices should keep the existing menu root."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.input_manager = InputManager(interaction_profile=InteractionProfile.STANDARD)

    assert app._get_initial_screen_name() == "menu"
    assert app._get_initial_ui_state() == AppRuntimeState.MENU


def test_one_button_profile_starts_on_hub() -> None:
    """Whisplay one-button devices should use the new hub root."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    app.input_manager = InputManager(interaction_profile=InteractionProfile.ONE_BUTTON)

    assert app._get_initial_screen_name() == "hub"
    assert app._get_initial_ui_state() == AppRuntimeState.HUB
