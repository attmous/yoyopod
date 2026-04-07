"""Coordinator tests for the event bus and split FSM orchestration path."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from yoyopy.app import YoyoPodApp
from yoyopy.app_context import AppContext
from yoyopy.audio import MockMusicBackend, Track
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
    UserActivityEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopy.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)
from yoyopy.power import BatteryState, PowerSnapshot
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


class FakeDisplay:
    """Minimal display double for screen-power tests."""

    COLOR_RED = (255, 0, 0)
    COLOR_YELLOW = (255, 255, 0)
    COLOR_GREEN = (0, 255, 0)
    COLOR_WHITE = (255, 255, 255)
    COLOR_BLACK = (0, 0, 0)
    COLOR_CYAN = (0, 255, 255)

    def __init__(self) -> None:
        self.set_backlight_calls: list[float] = []

    def set_backlight(self, brightness: float) -> None:
        self.set_backlight_calls.append(brightness)


class FakeLvglBackend:
    """Minimal LVGL backend double for wake-path tests."""

    def __init__(self) -> None:
        self.initialized = True
        self.force_refresh_calls = 0

    def force_refresh(self) -> None:
        self.force_refresh_calls += 1


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


class FakeMusicBackend(MockMusicBackend):
    """Minimal music backend double used by the coordinator tests."""

    def __init__(self, playback_state: str) -> None:
        super().__init__()
        self.start()
        self._playback_state = playback_state
        self.pause_calls = 0
        self.play_calls = 0

    def pause(self) -> bool:
        self.pause_calls += 1
        return super().pause()

    def play(self) -> bool:
        self.play_calls += 1
        return super().play()


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


class FakeRecoveringMusicBackend(MockMusicBackend):
    """Minimal music backend double for recovery backoff tests."""

    def __init__(self, start_results: list[bool]) -> None:
        super().__init__()
        self._start_results = start_results
        self.start_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        result_index = min(self.start_calls - 1, len(self._start_results) - 1)
        self._connected = self._start_results[result_index]
        return self._connected


class FakeStoppingVoIPManager:
    """Minimal VoIP manager double for app shutdown tests."""

    def __init__(self) -> None:
        self.stop_notify_events: list[bool] = []

    def stop(self, notify_events: bool = True) -> None:
        self.stop_notify_events.append(notify_events)


class FakePowerManager:
    """Minimal power manager double for app-level polling tests."""

    def __init__(
        self,
        snapshots: list[PowerSnapshot],
        poll_interval_seconds: float = 30.0,
        *,
        low_battery_warning_percent: float = 20.0,
        low_battery_warning_cooldown_seconds: float = 300.0,
        auto_shutdown_enabled: bool = True,
        critical_shutdown_percent: float = 10.0,
        shutdown_delay_seconds: float = 15.0,
        shutdown_state_file: str = "data/test_shutdown_state.json",
        watchdog_enabled: bool = False,
        watchdog_timeout_seconds: int = 60,
        watchdog_feed_interval_seconds: float = 15.0,
    ) -> None:
        self._snapshots = snapshots
        self.refresh_calls = 0
        self.enable_watchdog_calls = 0
        self.feed_watchdog_calls = 0
        self.disable_watchdog_calls = 0
        self.config = SimpleNamespace(
            enabled=True,
            poll_interval_seconds=poll_interval_seconds,
            low_battery_warning_percent=low_battery_warning_percent,
            low_battery_warning_cooldown_seconds=low_battery_warning_cooldown_seconds,
            auto_shutdown_enabled=auto_shutdown_enabled,
            critical_shutdown_percent=critical_shutdown_percent,
            shutdown_delay_seconds=shutdown_delay_seconds,
            shutdown_command="sudo -n shutdown -h now",
            shutdown_state_file=shutdown_state_file,
            watchdog_enabled=watchdog_enabled,
            watchdog_timeout_seconds=watchdog_timeout_seconds,
            watchdog_feed_interval_seconds=watchdog_feed_interval_seconds,
        )
        self.registered_shutdown_hooks: list[tuple[str, object]] = []
        self.run_shutdown_hooks_calls = 0
        self.shutdown_requested = False

    def refresh(self) -> PowerSnapshot:
        index = min(self.refresh_calls, len(self._snapshots) - 1)
        self.refresh_calls += 1
        return self._snapshots[index]

    def get_snapshot(self, refresh: bool = False) -> PowerSnapshot:
        index = max(0, min(self.refresh_calls - 1, len(self._snapshots) - 1))
        return self._snapshots[index]

    def register_shutdown_hook(self, name: str, hook) -> None:
        self.registered_shutdown_hooks.append((name, hook))

    def run_shutdown_hooks(self) -> list[str]:
        self.run_shutdown_hooks_calls += 1
        failed_hooks: list[str] = []
        for name, hook in self.registered_shutdown_hooks:
            try:
                hook()
            except Exception:
                failed_hooks.append(name)
        return failed_hooks

    def request_system_shutdown(self) -> bool:
        self.shutdown_requested = True
        return True

    def enable_watchdog(self) -> bool:
        self.enable_watchdog_calls += 1
        return True

    def feed_watchdog(self) -> bool:
        self.feed_watchdog_calls += 1
        return True

    def disable_watchdog(self) -> bool:
        self.disable_watchdog_calls += 1
        return True


def _publish_from_worker(app: YoyoPodApp, event: object) -> None:
    worker = threading.Thread(target=lambda: app.event_bus.publish(event))
    worker.start()
    worker.join()


def _navigate_from_worker(screen_manager: FakeScreenManager, screen_name: str) -> None:
    worker = threading.Thread(target=lambda: screen_manager.push_screen(screen_name))
    worker.start()
    worker.join()


def _power_snapshot(
    *,
    available: bool,
    battery_percent: float | None = None,
    charging: bool | None = None,
    power_plugged: bool | None = None,
    error: str = "",
) -> PowerSnapshot:
    return PowerSnapshot(
        available=available,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
        battery=BatteryState(
            level_percent=battery_percent,
            charging=charging,
            power_plugged=power_plugged,
        ),
        error=error,
    )


def _build_app(playback_state: str = "stopped", auto_resume: bool = True) -> tuple[
    YoyoPodApp,
    FakeMusicBackend,
    FakeScreenManager,
]:
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.music_fsm = MusicFSM()
    app.call_fsm = CallFSM()
    app.call_interruption_policy = CallInterruptionPolicy()
    app.auto_resume_after_call = auto_resume
    app.voip_registered = False
    app.power_manager = None

    music_backend = FakeMusicBackend(playback_state=playback_state)
    app.music_backend = music_backend

    app.menu_screen = FakeScreen()
    app.power_screen = FakeScreen()
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
            "power": app.power_screen,
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
    return app, music_backend, screen_manager


def _build_app_with_power(
    power_manager: FakePowerManager,
    *,
    playback_state: str = "stopped",
    auto_resume: bool = True,
) -> tuple[YoyoPodApp, FakeMusicBackend, FakeScreenManager]:
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.music_fsm = MusicFSM()
    app.call_fsm = CallFSM()
    app.call_interruption_policy = CallInterruptionPolicy()
    app.auto_resume_after_call = auto_resume
    app.voip_registered = False
    app.power_manager = power_manager

    music_backend = FakeMusicBackend(playback_state=playback_state)
    app.music_backend = music_backend

    app.menu_screen = FakeScreen()
    app.power_screen = FakeScreen()
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
            "power": app.power_screen,
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
    return app, music_backend, screen_manager


def test_apply_default_music_volume_updates_backend_and_context() -> None:
    """Startup should push the configured music volume into mpv and app context."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.app_settings = SimpleNamespace(audio=SimpleNamespace(default_volume=100))
    app.music_backend = MockMusicBackend()
    app.music_backend.start()

    app._apply_default_music_volume()

    assert app.context.playback.volume == 100
    assert app.music_backend.get_volume() == 100
    assert app.music_backend.commands[-1] == "volume:100"


def test_music_connect_reapplies_shared_output_volume() -> None:
    """mpv reconnects should inherit the current shared output volume."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()

    class FakeOutputVolume:
        def __init__(self) -> None:
            self.synced: list[int] = []

        def get_volume(self) -> int:
            return 82

        def sync_music_backend(self, volume: int) -> bool:
            self.synced.append(volume)
            return True

    app.output_volume = FakeOutputVolume()

    app._sync_output_volume_on_music_connect(True, "connected")

    assert app.output_volume.synced == [82]
    assert app.context.playback.volume == 82


def test_incoming_call_pauses_playing_music_once() -> None:
    """Incoming call events should pause active playback exactly once."""
    app, music_backend, screen_manager = _build_app(playback_state="playing")
    app.music_fsm.transition("play")
    app.coordinator_runtime.sync_app_state("playback_playing")

    _publish_from_worker(
        app,
        IncomingCallEvent(caller_address="sip:alice@example.com", caller_name="Alice"),
    )

    assert music_backend.pause_calls == 0
    assert app.event_bus.drain() == 1
    assert music_backend.pause_calls == 1
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
    assert music_backend.pause_calls == 1
    assert len(screen_manager.screen_stack) == 2


def test_call_end_auto_resumes_only_when_enabled() -> None:
    """Call end should auto-resume only when playback was interrupted and enabled."""
    app, music_backend, screen_manager = _build_app(playback_state="paused", auto_resume=True)
    app.music_fsm.sync(MusicState.PAUSED)
    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.call_interruption_policy.music_interrupted_by_call = True
    app.coordinator_runtime.sync_app_state("test_setup")
    screen_manager.push_screen("incoming_call")
    screen_manager.push_screen("in_call")

    _publish_from_worker(app, CallEndedEvent())

    assert music_backend.play_calls == 0
    assert app.event_bus.drain() == 1
    assert music_backend.play_calls == 1
    assert app.music_fsm.state == MusicState.PLAYING
    assert app.call_fsm.state == CallSessionState.IDLE
    assert not app.call_interruption_policy.music_interrupted_by_call
    assert screen_manager.current_screen is app.menu_screen


def test_call_end_keeps_music_paused_when_auto_resume_disabled() -> None:
    """Call end should leave playback paused when auto-resume is off."""
    app, music_backend, screen_manager = _build_app(playback_state="paused", auto_resume=False)
    app.music_fsm.sync(MusicState.PAUSED)
    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.call_interruption_policy.music_interrupted_by_call = True
    app.coordinator_runtime.sync_app_state("test_setup")
    screen_manager.push_screen("incoming_call")
    screen_manager.push_screen("in_call")

    _publish_from_worker(app, CallEndedEvent())

    assert app.event_bus.drain() == 1
    assert music_backend.play_calls == 0
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
    app, music_backend, screen_manager = _build_app(playback_state="paused", auto_resume=True)
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
    assert music_backend.play_calls == 1
    assert screen_manager.current_screen is app.menu_screen


def test_music_unavailable_event_stops_music_and_refreshes_now_playing() -> None:
    """Music backend loss should stop music state and refresh the visible now-playing screen."""
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

    screen_manager.push_screen("power")
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.POWER


def test_worker_navigation_waits_for_coordinator_drain_before_syncing_state() -> None:
    """Screen-change callbacks from worker threads should queue runtime sync onto the event bus."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    _navigate_from_worker(screen_manager, "contacts")

    assert screen_manager.current_screen is app.contact_list_screen
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.MENU
    assert app.event_bus.drain() == 1
    assert app.coordinator_runtime.current_app_state == AppRuntimeState.CALL_IDLE


def test_main_thread_callback_errors_are_contained_and_drain_continues() -> None:
    """Scheduled UI callbacks should not abort later callbacks or queued app events."""

    app, _, _ = _build_app(playback_state="stopped")
    callback_order: list[str] = []

    def bad_callback() -> None:
        callback_order.append("bad")
        raise RuntimeError("boom")

    def good_callback() -> None:
        callback_order.append("good")

    app._queue_main_thread_callback(bad_callback)
    app._queue_main_thread_callback(good_callback)
    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    assert app._process_pending_main_thread_actions() == 3
    assert callback_order == ["bad", "good"]


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


def test_manager_recovery_schedules_music_reconnect_off_main_thread() -> None:
    """Music recovery should schedule work instead of blocking the coordinator loop."""
    app = YoyoPodApp(simulate=True)
    app.voip_manager = FakeRecoveringVoIPManager([False, True])
    app.music_backend = FakeRecoveringMusicBackend([False, True])
    scheduled_attempts: list[float] = []

    app._start_music_recovery_worker = lambda recovery_now: scheduled_attempts.append(recovery_now)

    app._attempt_manager_recovery(now=0.0)

    assert app.voip_manager.start_calls == 1
    assert app.music_backend.start_calls == 0
    assert scheduled_attempts == [0.0]
    assert app._music_recovery.in_flight
    assert app._voip_recovery.next_attempt_at == 1.0


def test_music_recovery_backoff_doubles_after_success() -> None:
    """Background music recovery results should update backoff on success and failure."""
    app = YoyoPodApp(simulate=True)
    app.music_backend = FakeRecoveringMusicBackend([False, True])

    app._music_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="music", recovered=False, recovery_now=0.0)
    )

    assert app._music_recovery.next_attempt_at == 1.0
    assert app._music_recovery.delay_seconds == 2.0

    app._music_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="music", recovered=False, recovery_now=1.0)
    )

    assert app._music_recovery.next_attempt_at == 3.0
    assert app._music_recovery.delay_seconds == 4.0

    app.music_backend._connected = True
    app._music_recovery.in_flight = True
    app._handle_recovery_attempt_completed_event(
        RecoveryAttemptCompletedEvent(manager="music", recovered=True, recovery_now=3.0)
    )

    assert app._music_recovery.next_attempt_at == 0.0
    assert app._music_recovery.delay_seconds == 1.0


def test_app_stop_uses_silent_voip_teardown() -> None:
    """App shutdown should suppress VoIP teardown callbacks that could restart playback."""
    app, _, _ = _build_app(playback_state="paused", auto_resume=True)
    app.voip_manager = FakeStoppingVoIPManager()
    app.music_backend = None

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


def test_power_poll_updates_context_runtime_and_visible_screen() -> None:
    """A fresh power snapshot should update runtime/context and refresh the active screen."""
    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = FakePowerManager(
        [
            _power_snapshot(
                available=True,
                battery_percent=55.4,
                charging=True,
                power_plugged=True,
            )
        ]
    )

    app._poll_power_status(now=0.0, force=True)

    assert app.power_manager.refresh_calls == 1
    assert app.context.battery_percent == 55
    assert app.context.battery_charging is True
    assert app.context.external_power is True
    assert app.context.power_available is True
    assert app.coordinator_runtime.power_available is True
    assert app.coordinator_runtime.power_snapshot is not None
    assert app.coordinator_runtime.power_snapshot.battery.level_percent == 55.4
    assert app.menu_screen.render_calls == 1


def test_periodic_power_refresh_only_renders_visible_power_screen() -> None:
    """The main loop should only re-render the power screen while it is visible."""
    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )

    app._update_power_screen_if_needed()
    assert app.power_screen.render_calls == 0

    screen_manager.push_screen("power")
    app._update_power_screen_if_needed()
    assert app.power_screen.render_calls == 1


def test_power_poll_honors_interval_and_tracks_unavailable_backend() -> None:
    """Power polling should respect the configured interval and retain availability state."""
    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = FakePowerManager(
        [
            _power_snapshot(available=True, battery_percent=61.0, charging=False, power_plugged=False),
            _power_snapshot(available=False, error="I2C not connected"),
        ],
        poll_interval_seconds=30.0,
    )

    app._poll_power_status(now=0.0, force=True)
    app._poll_power_status(now=10.0)
    app._poll_power_status(now=30.0)

    assert app.power_manager.refresh_calls == 2
    assert app.context.battery_percent == 61
    assert app.context.power_available is False
    assert app.context.power_error == "I2C not connected"
    assert app.coordinator_runtime.power_available is False
    assert app.menu_screen.render_calls == 2


def test_screen_timeout_turns_backlight_off_after_inactivity() -> None:
    """Inactivity beyond the configured timeout should sleep the screen."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app._resolve_screen_timeout_seconds()
    app._active_brightness = app._resolve_active_brightness()
    app._configure_screen_power(initial_now=0.0)
    app._update_screen_power(31.0)

    assert app.display.set_backlight_calls == [0.8, 0.0]
    assert app.context.screen_awake is False
    assert app.context.screen_on_seconds == 31
    assert app.context.screen_idle_seconds == 31


def test_user_activity_event_wakes_screen_and_refreshes_current_screen() -> None:
    """Queued user activity should wake a sleeping screen and re-render the visible route."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app._resolve_screen_timeout_seconds()
    app._active_brightness = app._resolve_active_brightness()
    app._configure_screen_power(initial_now=0.0)
    app._sleep_screen(31.0)

    assert app.context.screen_awake is False
    render_calls_before = app.menu_screen.render_calls

    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    assert app.event_bus.drain() == 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen_awake is True
    assert app.menu_screen.render_calls == render_calls_before + 1


def test_user_activity_event_wakes_sleeping_lvgl_screen_with_forced_refresh() -> None:
    """LVGL wake should explicitly refresh the active scene after backlight sleep."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app._lvgl_backend = FakeLvglBackend()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app._resolve_screen_timeout_seconds()
    app._active_brightness = app._resolve_active_brightness()
    app._configure_screen_power(initial_now=0.0)
    app._sleep_screen(31.0)

    _publish_from_worker(app, UserActivityEvent(action_name=None))

    assert app.event_bus.drain() == 1
    assert app._lvgl_backend.force_refresh_calls == 1


def test_screen_on_time_accumulates_across_sleep_and_wake_cycles() -> None:
    """Screen-on metrics should accumulate only while the backlight is awake."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app._resolve_screen_timeout_seconds()
    app._active_brightness = app._resolve_active_brightness()
    app._configure_screen_power(initial_now=0.0)
    app._sleep_screen(10.0)
    app._wake_screen(20.0, render_current=False)
    app._sleep_screen(25.0)

    assert app.display.set_backlight_calls == [0.8, 0.0, 0.8, 0.0]
    assert app.context.screen_on_seconds == 15
    assert app.get_status()["screen_on_seconds"] == 15


def test_low_battery_snapshot_sets_temporary_alert() -> None:
    """A low battery snapshot should surface a temporary warning overlay."""

    app, _, _ = _build_app_with_power(
        FakePowerManager(
            [
                _power_snapshot(
                    available=True,
                    battery_percent=15.0,
                    charging=False,
                    power_plugged=False,
                )
            ],
            low_battery_warning_percent=20.0,
            critical_shutdown_percent=10.0,
        )
    )

    app._poll_power_status(now=0.0, force=True)

    assert app._pending_shutdown is None
    assert app._power_alert is not None
    assert app._power_alert.title == "Low Battery"
    assert app._power_alert.subtitle == "15% remaining"


def test_critical_battery_snapshot_creates_pending_shutdown() -> None:
    """Crossing the critical threshold should schedule a delayed shutdown."""

    app, _, _ = _build_app_with_power(
        FakePowerManager(
            [
                _power_snapshot(
                    available=True,
                    battery_percent=8.0,
                    charging=False,
                    power_plugged=False,
                )
            ],
            critical_shutdown_percent=10.0,
            shutdown_delay_seconds=12.0,
        )
    )

    app._poll_power_status(now=0.0, force=True)

    assert app._pending_shutdown is not None
    assert app._pending_shutdown.reason == "critical_battery"
    assert app._pending_shutdown.battery_percent == 8.0
    assert app.get_status()["shutdown_pending"] is True


def test_power_restore_cancels_pending_shutdown() -> None:
    """Restoring external power should cancel a pending graceful shutdown."""

    app, _, _ = _build_app_with_power(
        FakePowerManager(
            [
                _power_snapshot(
                    available=True,
                    battery_percent=8.0,
                    charging=False,
                    power_plugged=False,
                ),
                _power_snapshot(
                    available=True,
                    battery_percent=8.5,
                    charging=True,
                    power_plugged=True,
                ),
            ],
            critical_shutdown_percent=10.0,
        )
    )

    app._poll_power_status(now=0.0, force=True)
    assert app._pending_shutdown is not None

    app._poll_power_status(now=30.0, force=True)

    assert app._pending_shutdown is None
    assert app._power_alert is not None
    assert app._power_alert.title == "Power Restored"


def test_pending_shutdown_runs_hooks_and_requests_system_poweroff(tmp_path) -> None:
    """The delayed shutdown path should save state, stop the app, and request poweroff."""

    shutdown_state_file = tmp_path / "last_shutdown_state.json"
    power_manager = FakePowerManager(
        [
            _power_snapshot(
                available=True,
                battery_percent=8.0,
                charging=False,
                power_plugged=False,
            )
        ],
        critical_shutdown_percent=10.0,
        shutdown_delay_seconds=0.0,
        shutdown_state_file=str(shutdown_state_file),
    )
    app, _, _ = _build_app_with_power(power_manager)
    stop_calls: list[str] = []

    def fake_stop(disable_watchdog: bool = True) -> None:
        stop_calls.append("stop")
        app._stopping = True

    app.stop = fake_stop
    app._register_power_shutdown_hooks()
    app._poll_power_status(now=0.0, force=True)

    assert [name for name, _ in power_manager.registered_shutdown_hooks] == ["save_shutdown_state"]
    assert app._pending_shutdown is not None

    app._process_pending_shutdown(app._pending_shutdown.execute_at)

    assert stop_calls == ["stop"]
    assert power_manager.run_shutdown_hooks_calls == 1
    assert power_manager.shutdown_requested is True
    assert app._shutdown_completed is True

    payload = json.loads(shutdown_state_file.read_text(encoding="utf-8"))
    assert payload["state"] == "menu"
    assert payload["current_screen"] == "menu"
    assert payload["battery_percent"] == 8
    assert payload["external_power"] is False


def test_watchdog_starts_and_feeds_from_app_loop() -> None:
    """The app loop should enable and periodically feed the PiSugar watchdog."""

    power_manager = FakePowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
        watchdog_timeout_seconds=60,
        watchdog_feed_interval_seconds=10.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False

    app._start_watchdog(now=0.0)
    app._feed_watchdog_if_due(9.0)
    app._feed_watchdog_if_due(10.0)

    assert power_manager.enable_watchdog_calls == 1
    assert power_manager.feed_watchdog_calls == 1
    assert app.get_status()["watchdog_active"] is True


def test_intentional_stop_disables_watchdog() -> None:
    """Ordinary app stops should disable the watchdog to avoid reboot loops."""

    power_manager = FakePowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False

    app._start_watchdog(now=0.0)
    app.stop()

    assert power_manager.enable_watchdog_calls == 1
    assert power_manager.disable_watchdog_calls == 1


def test_poweroff_path_suppresses_watchdog_feed_without_disabling_it() -> None:
    """Battery-driven poweroff should preserve the watchdog as a recovery backstop."""

    power_manager = FakePowerManager(
        [_power_snapshot(available=True, battery_percent=8.0)],
        watchdog_enabled=True,
        critical_shutdown_percent=10.0,
        shutdown_delay_seconds=0.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False
    stop_disable_watchdog: list[bool] = []

    def fake_stop(disable_watchdog: bool = True) -> None:
        stop_disable_watchdog.append(disable_watchdog)
        app._stopping = True
        app._stopped = True

    app.stop = fake_stop
    app._start_watchdog(now=0.0)
    app._register_power_shutdown_hooks()
    app._poll_power_status(now=0.0, force=True)
    app._process_pending_shutdown(app._pending_shutdown.execute_at)

    assert stop_disable_watchdog == [False]
    assert power_manager.disable_watchdog_calls == 0
    assert app.get_status()["watchdog_feed_suppressed"] is True
