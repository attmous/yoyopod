"""Coordinator tests for the event bus and split FSM orchestration path."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Protocol

import pytest
from loguru import logger

from yoyopod.app import YoyoPodApp
from yoyopod.backends.music import MockMusicBackend
from yoyopod.core import AppContext
from yoyopod.core.audio_volume import AudioVolumeController
from yoyopod.integrations.call.events import (
    CallEndedEvent,
    RegistrationChangedEvent,
    VoIPAvailabilityChangedEvent,
)
from yoyopod.integrations.call.models import (
    CallState,
    RegistrationState,
    VoIPCallSessionSnapshot,
    VoIPConfig,
    VoIPLifecycleSnapshot,
    VoIPRuntimeSnapshot,
)
from yoyopod.integrations.music.events import (
    MusicAvailabilityChangedEvent,
    PlaybackStateChangedEvent,
    TrackChangedEvent,
)
from yoyopod.core.app_state import AppRuntimeState, AppStateRuntime
from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.call import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
)
from yoyopod.integrations.music import MusicFSM, MusicState
from yoyopod.integrations.power.models import BatteryState, PowerSnapshot
from yoyopod.core.loop import RuntimeLoopService
from yoyopod.core import UserActivityEvent
from yoyopod.integrations.power import PowerAlert
from yoyopod.ui.input import InputManager, InteractionProfile
from yoyopod.ui.rust_host.facade import RustUiFacade
from yoyopod.ui.screens.manager import VisibleTickRefreshResult


class RenderableScreen(Protocol):
    """Small screen surface used by orchestration test doubles."""

    render_calls: int
    refresh_for_visible_tick_calls: int
    route_name: str | None

    def render(self) -> None: ...

    def refresh_for_visible_tick(self) -> None: ...

    def clear_dirty(self) -> None: ...

    def should_render_for_visible_tick(self) -> bool: ...


class IncomingCallScreenLike(RenderableScreen, Protocol):
    """Extra incoming-call fields used by the screen coordinator."""

    caller_address: str
    caller_name: str
    ring_animation_frame: int


class FakeScreen:
    """Minimal screen double for coordinator tests."""

    def __init__(self) -> None:
        self.render_calls = 0
        self.refresh_for_visible_tick_calls = 0
        self.route_name: str | None = None
        self.visible_tick_refresh_enabled = False
        self.keep_visible_tick_dirty = False
        self._dirty = True

    def render(self) -> None:
        self.render_calls += 1

    def refresh_for_visible_tick(self) -> None:
        self.refresh_for_visible_tick_calls += 1
        if self.keep_visible_tick_dirty:
            self._dirty = True

    def wants_visible_tick_refresh(self) -> bool:
        return self.visible_tick_refresh_enabled

    def clear_dirty(self) -> None:
        self._dirty = False

    def should_render_for_visible_tick(self) -> bool:
        return self.keep_visible_tick_dirty or self._dirty


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


class FakeRustUiHost:
    """Minimal Rust UI host double for screen-power ownership tests."""

    def __init__(self) -> None:
        self.backlight_calls: list[float] = []

    def send_backlight(self, *, brightness: float) -> bool:
        self.backlight_calls.append(brightness)
        return True


class FakeLvglBackend:
    """Minimal LVGL backend double for wake-path tests."""

    def __init__(self) -> None:
        self.initialized = True
        self.force_refresh_calls = 0
        self.pump_calls: list[int] = []

    def force_refresh(self) -> None:
        self.force_refresh_calls += 1

    def pump(self, delta_ms: int) -> None:
        self.pump_calls.append(delta_ms)


class FakeScreenManager:
    """Simple stack-based screen manager double."""

    def __init__(self, screen_lookup: dict[str, RenderableScreen]) -> None:
        self.screen_lookup = screen_lookup
        self.screen_stack: list[RenderableScreen] = []
        self.current_screen: RenderableScreen | None = None
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

    def get_current_screen(self) -> RenderableScreen | None:
        return self.current_screen

    def refresh_current_screen(self) -> None:
        if self.current_screen is None:
            return
        self.current_screen.refresh_for_visible_tick()
        self.current_screen.render()
        self.current_screen.clear_dirty()

    def refresh_current_screen_for_visible_tick(self) -> VisibleTickRefreshResult:
        if self.current_screen is None:
            return VisibleTickRefreshResult.NOT_ELIGIBLE
        wants_visible_tick_refresh = getattr(
            self.current_screen,
            "wants_visible_tick_refresh",
            None,
        )
        refresh_for_visible_tick = getattr(
            self.current_screen,
            "refresh_for_visible_tick",
            None,
        )
        refresh_for_visible_tick_callback = (
            refresh_for_visible_tick if callable(refresh_for_visible_tick) else None
        )
        if callable(wants_visible_tick_refresh):
            if not wants_visible_tick_refresh():
                return VisibleTickRefreshResult.NOT_ELIGIBLE
        elif refresh_for_visible_tick_callback is None:
            return VisibleTickRefreshResult.NOT_ELIGIBLE
        if refresh_for_visible_tick_callback is not None:
            refresh_for_visible_tick_callback()
        should_render_for_visible_tick = getattr(
            self.current_screen,
            "should_render_for_visible_tick",
            None,
        )
        if callable(should_render_for_visible_tick) and not should_render_for_visible_tick():
            return VisibleTickRefreshResult.CLEAN
        self.current_screen.render()
        self.current_screen.clear_dirty()
        return VisibleTickRefreshResult.RENDERED

    def pop_call_screens(self) -> None:
        call_route_names = {"in_call", "incoming_call", "outgoing_call"}
        while self.current_screen is not None and self.current_screen.route_name in call_route_names:
            self.pop_screen()
            if not self.screen_stack:
                break

    def refresh_now_playing_screen(self) -> None:
        if self.current_screen is None or self.current_screen.route_name != "now_playing":
            return
        self.current_screen.render()
        self.current_screen.clear_dirty()

    def refresh_call_screen_if_visible(self) -> None:
        if self.current_screen is None or self.current_screen.route_name != "call":
            return
        self.current_screen.render()
        self.current_screen.clear_dirty()

    def show_incoming_call(self, caller_address: str, caller_name: str) -> None:
        screen = self.screen_lookup["incoming_call"]
        setattr(screen, "caller_address", caller_address)
        setattr(screen, "caller_name", caller_name)
        setattr(screen, "ring_animation_frame", 0)
        if self.current_screen is not screen:
            self.push_screen("incoming_call")

    def show_in_call(self) -> None:
        screen = self.screen_lookup["in_call"]
        if self.current_screen is not screen:
            self.push_screen("in_call")

    def show_outgoing_call(self, callee_address: str, callee_name: str) -> None:
        screen = self.screen_lookup["outgoing_call"]
        setattr(screen, "callee_address", callee_address)
        setattr(screen, "callee_name", callee_name or "Unknown")
        setattr(screen, "ring_animation_frame", 0)
        if self.current_screen is not screen:
            self.push_screen("outgoing_call")

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
        self.pause_result = True
        self.play_result = True

    def pause(self) -> bool:
        self.pause_calls += 1
        if not self.pause_result:
            return False
        return super().pause()

    def play(self) -> bool:
        self.play_calls += 1
        if not self.play_result:
            return False
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
        self.startup_in_progress = False

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


class FakeRuntimeLoopVoIPManager:
    """Minimal running VoIP manager double for loop timing diagnostics."""

    def __init__(
        self,
        *,
        native_events: int = 0,
        native_iterate_seconds: float = 0.0,
        event_drain_seconds: float = 0.0,
        background_iterate_enabled: bool = False,
        sample_id: int = 0,
        schedule_delay_seconds: float = 0.0,
        total_duration_seconds: float | None = None,
        last_started_at: float = 0.0,
        last_completed_at: float = 0.0,
    ) -> None:
        self.running = True
        self.background_iterate_enabled = background_iterate_enabled
        self.iterate_calls = 0
        self.ensure_background_iterate_running_calls = 0
        self.housekeeping_calls = 0
        self.interval_updates: list[float] = []
        self.native_events = native_events
        self.native_iterate_seconds = native_iterate_seconds
        self.event_drain_seconds = event_drain_seconds
        self._iterate_timing_snapshot = SimpleNamespace(
            sample_id=sample_id,
            last_started_at=last_started_at,
            last_completed_at=last_completed_at,
            schedule_delay_seconds=schedule_delay_seconds,
            total_duration_seconds=(
                native_iterate_seconds + event_drain_seconds
                if total_duration_seconds is None
                else total_duration_seconds
            ),
            native_duration_seconds=native_iterate_seconds,
            event_drain_duration_seconds=event_drain_seconds,
            drained_events=native_events,
            interval_seconds=0.0,
            in_flight=False,
        )

    def iterate(self) -> int:
        self.iterate_calls += 1
        return self.native_events

    def ensure_background_iterate_running(self) -> None:
        self.ensure_background_iterate_running_calls += 1

    def set_iterate_interval_seconds(self, interval_seconds: float) -> None:
        self.interval_updates.append(interval_seconds)
        self._iterate_timing_snapshot.interval_seconds = interval_seconds

    def poll_housekeeping(self) -> None:
        self.housekeeping_calls += 1

    def get_iterate_metrics(self) -> object:
        return SimpleNamespace(
            native_duration_seconds=self.native_iterate_seconds,
            event_drain_duration_seconds=self.event_drain_seconds,
            total_duration_seconds=self.native_iterate_seconds + self.event_drain_seconds,
            drained_events=self.native_events,
        )

    def get_iterate_timing_snapshot(self) -> object | None:
        if not self.background_iterate_enabled:
            return None
        return self._iterate_timing_snapshot


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
    worker = threading.Thread(
        target=lambda: app.scheduler.run_on_main(
            lambda: app.bus.publish(event)
        )
    )
    worker.start()
    worker.join()


def _wait_for(predicate, *, timeout_seconds: float = 1.0) -> None:
    """Wait for one async test predicate to become true."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for async condition")


def _complete_power_refresh(app: YoyoPodApp) -> None:
    """Drain one queued async power-refresh completion for the test app."""

    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)
    app.runtime_loop.process_pending_main_thread_actions()
    assert app.get_status()["power_refresh_in_flight"] is False


def _force_power_refresh(app: YoyoPodApp, *, now: float) -> None:
    """Run one forced power refresh and drain its async completion."""

    app.power_runtime.poll_status(now=now, force=True)
    _complete_power_refresh(app)


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


@dataclass(slots=True)
class OrchestrationScreens:
    """Grouped screen doubles used by the orchestration test harness."""

    menu: RenderableScreen
    power: RenderableScreen
    now_playing: RenderableScreen
    playlist: RenderableScreen
    call: RenderableScreen
    contacts: RenderableScreen
    incoming_call: IncomingCallScreenLike
    outgoing_call: RenderableScreen
    in_call: RenderableScreen

    def screen_lookup(self) -> dict[str, RenderableScreen]:
        return {
            "menu": self.menu,
            "power": self.power,
            "now_playing": self.now_playing,
            "playlists": self.playlist,
            "call": self.call,
            "contacts": self.contacts,
            "incoming_call": self.incoming_call,
            "outgoing_call": self.outgoing_call,
            "in_call": self.in_call,
        }


def _call_runtime_snapshot(
    state: CallState,
    *,
    peer: str = "sip:alice@example.com",
) -> VoIPRuntimeSnapshot:
    terminal = state in {CallState.IDLE, CallState.RELEASED, CallState.END, CallState.ERROR}
    session_active = not terminal
    session_id = "call-1" if peer else ""
    return VoIPRuntimeSnapshot(
        configured=True,
        registered=True,
        registration_state=RegistrationState.OK,
        call_state=state,
        active_call_id=session_id if session_active else "",
        active_call_peer=peer if session_active else "",
        lifecycle=VoIPLifecycleSnapshot(
            state="registered",
            reason="registered",
            backend_available=True,
        ),
        call_session=VoIPCallSessionSnapshot(
            active=session_active,
            session_id=session_id,
            direction="incoming",
            peer_sip_address=peer,
            terminal_state="" if session_active else state.value,
            history_outcome="missed" if terminal else "",
        ),
    )


@dataclass(slots=True)
class OrchestrationHarness:
    """Small test-only app harness for coordinator-heavy orchestration cases."""

    app: YoyoPodApp
    music_backend: FakeMusicBackend
    screen_manager: FakeScreenManager
    screens: OrchestrationScreens
    pending_semantic_events: int = 0

    @classmethod
    def build(
        cls,
        *,
        playback_state: str = "stopped",
        auto_resume: bool = True,
        power_manager: FakePowerManager | None = None,
    ) -> OrchestrationHarness:
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

        screens = OrchestrationScreens(
            menu=FakeScreen(),
            power=FakeScreen(),
            now_playing=FakeScreen(),
            playlist=FakeScreen(),
            call=FakeScreen(),
            contacts=FakeScreen(),
            incoming_call=FakeIncomingCallScreen(),
            outgoing_call=FakeScreen(),
            in_call=FakeScreen(),
        )
        screens.power.visible_tick_refresh_enabled = True
        screens.now_playing.visible_tick_refresh_enabled = True
        screens.in_call.visible_tick_refresh_enabled = True
        screens.now_playing.keep_visible_tick_dirty = True
        screens.in_call.keep_visible_tick_dirty = True
        app.menu_screen = screens.menu
        app.power_screen = screens.power
        app.now_playing_screen = screens.now_playing
        app.playlist_screen = screens.playlist
        app.call_screen = screens.call
        app.contact_list_screen = screens.contacts
        app.incoming_call_screen = screens.incoming_call
        app.outgoing_call_screen = screens.outgoing_call
        app.in_call_screen = screens.in_call

        screen_manager = FakeScreenManager(screens.screen_lookup())
        app.screen_manager = screen_manager
        app.screen_manager.push_screen("menu")

        app.boot_service.setup_event_subscriptions()
        app.runtime_loop.process_pending_main_thread_actions()
        assert app.call_runtime is not None
        app.call_runtime.start_ringing = lambda: None
        app.call_runtime.stop_ringing = lambda: None
        return cls(
            app=app,
            music_backend=music_backend,
            screen_manager=screen_manager,
            screens=screens,
            pending_semantic_events=0,
        )

    @property
    def runtime(self) -> AppStateRuntime:
        assert self.app.app_state_runtime is not None
        return self.app.app_state_runtime

    @property
    def music_fsm(self) -> MusicFSM:
        assert self.app.music_fsm is not None
        return self.app.music_fsm

    @property
    def call_fsm(self) -> CallFSM:
        assert self.app.call_fsm is not None
        return self.app.call_fsm

    @property
    def call_interruption_policy(self) -> CallInterruptionPolicy:
        assert self.app.call_interruption_policy is not None
        return self.app.call_interruption_policy

    def sync_runtime(
        self,
        *,
        music_state: MusicState | None = None,
        call_state: CallSessionState | None = None,
        music_interrupted_by_call: bool | None = None,
        trigger: str = "test_setup",
    ) -> None:
        if music_state is not None:
            self.music_fsm.sync(music_state)
        if call_state is not None:
            self.call_fsm.sync(call_state)
        if music_interrupted_by_call is not None:
            self.call_interruption_policy.music_interrupted_by_call = music_interrupted_by_call
        self.runtime.sync_app_state(trigger)

    def push_screens(self, *screen_names: str) -> None:
        for screen_name in screen_names:
            self.screen_manager.push_screen(screen_name)

    def show_now_playing(self) -> None:
        self.screen_manager.push_screen("now_playing")

    def publish(self, event: object) -> None:
        self.pending_semantic_events += 1
        if isinstance(event, CallEndedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.call_runtime.handle_call_ended(reason=event.reason)
                )
            )
            worker.start()
            worker.join()
            return
        if isinstance(event, RegistrationChangedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.call_runtime.handle_registration_change(event.state)
                )
            )
            worker.start()
            worker.join()
            return
        if isinstance(event, VoIPAvailabilityChangedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.call_runtime.handle_availability_change(
                        event.available,
                        event.reason,
                        event.registration_state,
                    )
                )
            )
            worker.start()
            worker.join()
            return
        if isinstance(event, TrackChangedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.music_runtime.handle_track_change(event.track)
                )
            )
            worker.start()
            worker.join()
            return
        if isinstance(event, PlaybackStateChangedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.music_runtime.handle_playback_state_change(
                        event.state
                    )
                )
            )
            worker.start()
            worker.join()
            return
        if isinstance(event, MusicAvailabilityChangedEvent):
            worker = threading.Thread(
                target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.music_runtime.handle_availability_change(
                        event.available,
                        event.reason,
                    )
                )
            )
            worker.start()
            worker.join()
            return
        _publish_from_worker(self.app, event)

    def publish_call_snapshot(
        self,
        state: CallState,
        *,
        peer: str = "sip:alice@example.com",
        display_name: str = "Alice",
    ) -> None:
        self.pending_semantic_events += 1
        self._queue_call_snapshot(state, peer=peer, display_name=display_name)

    def _queue_call_snapshot(
        self,
        state: CallState,
        *,
        peer: str = "sip:alice@example.com",
        display_name: str = "Alice",
    ) -> None:
        self.app.voip_manager = SimpleNamespace(
            get_caller_info=lambda: {
                "address": peer,
                "name": display_name,
                "display_name": display_name,
            }
        )
        snapshot = _call_runtime_snapshot(state, peer=peer)
        worker = threading.Thread(
            target=lambda: self.app.runtime_loop.queue_main_thread_callback(
                lambda: self.app.call_runtime.handle_runtime_snapshot_change(snapshot)
            )
        )
        worker.start()
        worker.join()

    def drain_events(self) -> int:
        self.app.runtime_loop.process_pending_main_thread_actions()
        drained = self.pending_semantic_events
        self.pending_semantic_events = 0
        return drained


def _build_app(playback_state: str = "stopped", auto_resume: bool = True) -> tuple[
    YoyoPodApp,
    FakeMusicBackend,
    FakeScreenManager,
]:
    harness = OrchestrationHarness.build(
        playback_state=playback_state,
        auto_resume=auto_resume,
    )
    return harness.app, harness.music_backend, harness.screen_manager


def _build_app_with_power(
    power_manager: FakePowerManager,
    *,
    playback_state: str = "stopped",
    auto_resume: bool = True,
) -> tuple[YoyoPodApp, FakeMusicBackend, FakeScreenManager]:
    harness = OrchestrationHarness.build(
        playback_state=playback_state,
        auto_resume=auto_resume,
        power_manager=power_manager,
    )
    return harness.app, harness.music_backend, harness.screen_manager


def test_apply_default_music_volume_updates_backend_and_context() -> None:
    """Startup should push the configured music volume into mpv and app context."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.media_settings = SimpleNamespace(music=SimpleNamespace(default_volume=100))
    app.music_backend = MockMusicBackend()
    app.music_backend.start()
    app.audio_volume_controller = AudioVolumeController(
        context=app.context,
        default_music_volume_provider=lambda: app.media_settings.music.default_volume,
        music_backend=app.music_backend,
    )
    app.context.audio_volume_controller = app.audio_volume_controller

    app.audio_volume_controller.apply_default_music_volume()

    assert app.context.media.playback.volume == 100
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
    app.audio_volume_controller = AudioVolumeController(
        context=app.context,
        default_music_volume_provider=lambda: 100,
        output_volume=app.output_volume,
    )
    app.context.audio_volume_controller = app.audio_volume_controller

    app.audio_volume_controller.sync_output_volume_on_music_connect(True, "connected")

    assert app.output_volume.synced == [82]
    assert app.context.media.playback.volume == 82


def test_incoming_call_pauses_playing_music_once() -> None:
    """Incoming call events should pause active playback exactly once."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.INCOMING)
    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.music_backend.pause_calls == 0
    assert harness.drain_events() == 2
    assert harness.music_backend.pause_calls == 1
    assert harness.music_fsm.state == MusicState.PAUSED
    assert harness.call_fsm.state == CallSessionState.INCOMING
    assert harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.incoming_call
    assert harness.screens.incoming_call.caller_name == "Alice"

    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 1
    assert len(harness.screen_manager.screen_stack) == 2


def test_incoming_call_keeps_music_playing_when_pause_command_fails() -> None:
    """Incoming-call setup should preserve playback truth when the pause command fails."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.music_backend.pause_result = False
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 1
    assert harness.music_fsm.state == MusicState.PLAYING
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.call_fsm.state == CallSessionState.INCOMING


def test_incoming_call_does_not_mark_interrupted_when_music_backend_is_unavailable() -> None:
    """Call setup should not claim a successful pause without a connected music backend."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.music_backend.stop()
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 0
    assert harness.music_fsm.state == MusicState.PLAYING
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.call_fsm.state == CallSessionState.INCOMING


def test_incoming_call_snapshot_drives_runtime_state() -> None:
    """Incoming-call snapshots should exercise the Rust snapshot path."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 1
    assert harness.call_fsm.state == CallSessionState.INCOMING
    assert harness.screen_manager.current_screen is harness.screens.incoming_call

    harness.publish_call_snapshot(CallState.INCOMING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 1
    assert harness.call_fsm.state == CallSessionState.INCOMING
    assert harness.screen_manager.current_screen is harness.screens.incoming_call


def test_call_end_auto_resumes_only_when_enabled() -> None:
    """Call end should auto-resume only when playback was interrupted and enabled."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=True)
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("incoming_call", "in_call")

    harness.publish(CallEndedEvent())

    assert harness.music_backend.play_calls == 0
    assert harness.drain_events() == 1
    assert harness.music_backend.play_calls == 1
    assert harness.music_fsm.state == MusicState.PLAYING
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_call_end_keeps_music_paused_when_auto_resume_disabled() -> None:
    """Call end should leave playback paused when auto-resume is off."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=False)
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("incoming_call", "in_call")

    harness.publish(CallEndedEvent())

    assert harness.drain_events() == 1
    assert harness.music_backend.play_calls == 0
    assert harness.music_fsm.state == MusicState.PAUSED
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_call_end_keeps_music_paused_when_resume_command_fails() -> None:
    """Call teardown should not claim playback resumed when the backend rejects resume."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=True)
    harness.music_backend.play_result = False
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("incoming_call", "in_call")

    harness.publish(CallEndedEvent())

    assert harness.drain_events() == 1
    assert harness.music_backend.play_calls == 1
    assert harness.music_fsm.state == MusicState.PAUSED
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_call_end_keeps_music_paused_when_music_backend_is_unavailable() -> None:
    """Call teardown should not claim playback resumed without a connected backend."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=True)
    harness.music_backend.stop()
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("incoming_call", "in_call")

    harness.publish(CallEndedEvent())

    assert harness.drain_events() == 1
    assert harness.music_backend.play_calls == 0
    assert harness.music_fsm.state == MusicState.PAUSED
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.menu


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
    app, _, screen_manager = _build_app(playback_state=playback_state)
    app.music_fsm.sync(music_state)
    app.app_state_runtime.sync_app_state("test_setup")

    worker = threading.Thread(
        target=lambda: app.runtime_loop.queue_main_thread_callback(
            lambda: app.call_runtime.handle_runtime_snapshot_change(
                _call_runtime_snapshot(CallState.OUTGOING)
            )
        )
    )
    worker.start()
    worker.join()

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.call_fsm.state == CallSessionState.OUTGOING
    assert app.music_fsm.state == music_state
    assert screen_manager.current_screen is app.outgoing_call_screen


def test_outgoing_call_pauses_playing_music_and_resumes_on_terminal_end() -> None:
    """Outgoing-call setup should follow the same pause/resume contract as incoming calls."""
    harness = OrchestrationHarness.build(playback_state="playing", auto_resume=True)
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.OUTGOING)

    assert harness.drain_events() == 1
    assert harness.music_backend.pause_calls == 1
    assert harness.music_fsm.state == MusicState.PAUSED
    assert harness.call_fsm.state == CallSessionState.OUTGOING
    assert harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.outgoing_call

    harness.publish_call_snapshot(CallState.END)

    assert harness.drain_events() == 1
    assert harness.music_backend.play_calls == 1
    assert harness.music_fsm.state == MusicState.PLAYING
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert not harness.call_interruption_policy.music_interrupted_by_call
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_terminal_error_state_ends_incoming_call_without_waiting_for_released() -> None:
    """Terminal backend errors should unwind the incoming-call flow immediately."""

    harness = OrchestrationHarness.build(playback_state="playing", auto_resume=True)
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish_call_snapshot(CallState.INCOMING)
    assert harness.drain_events() == 1

    harness.publish_call_snapshot(CallState.INCOMING)
    assert harness.drain_events() == 1

    harness.publish_call_snapshot(CallState.ERROR)

    assert harness.drain_events() == 1
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert harness.music_fsm.state == MusicState.PLAYING
    assert harness.music_backend.play_calls == 1
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_terminal_end_state_clears_outgoing_call_without_waiting_for_released() -> None:
    """Cancelled or rejected call terminals should clear the outgoing phase directly."""

    harness = OrchestrationHarness.build(playback_state="stopped")

    harness.publish_call_snapshot(CallState.OUTGOING)
    assert harness.drain_events() == 1
    assert harness.screen_manager.current_screen is harness.screens.outgoing_call

    harness.publish_call_snapshot(CallState.END)

    assert harness.drain_events() == 1
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_background_events_wait_for_drain_before_mutating_state() -> None:
    """Registration and playback events should not mutate coordinator state until drained."""
    app, _, _ = _build_app(playback_state="stopped")

    worker = threading.Thread(
        target=lambda: app.runtime_loop.queue_main_thread_callback(
        lambda: app.call_runtime.handle_registration_change(RegistrationState.OK)
        )
    )
    worker.start()
    worker.join()
    worker = threading.Thread(
        target=lambda: app.runtime_loop.queue_main_thread_callback(
        lambda: app.music_runtime.handle_playback_state_change("playing")
        )
    )
    worker.start()
    worker.join()

    assert not app.voip_registered
    assert app.music_fsm.state == MusicState.IDLE

    assert app.runtime_loop.process_pending_main_thread_actions() == 2
    assert app.voip_registered
    assert app.music_fsm.state == MusicState.PLAYING
    assert app.app_state_runtime.current_app_state == AppRuntimeState.PLAYING_WITH_VOIP


def test_track_event_refreshes_now_playing_screen_when_visible() -> None:
    """Track events should refresh the current now playing screen through the bus."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.show_now_playing()
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish(TrackChangedEvent(track=None))

    assert harness.screens.now_playing.render_calls == 0
    assert harness.drain_events() == 1
    assert harness.screens.now_playing.render_calls == 1
    assert harness.music_fsm.state == MusicState.IDLE


def test_periodic_in_call_refresh_only_renders_visible_call_screen() -> None:
    """Live in-call refreshes should come from the main loop, not a screen-owned thread."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    assert app.screen_manager is not None
    assert (
        app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.NOT_ELIGIBLE
    )
    assert app.in_call_screen.render_calls == 0

    screen_manager.push_screen("in_call")
    assert (
        app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.RENDERED
    )
    assert app.in_call_screen.render_calls == 1

    screen_manager.pop_screen()
    assert (
        app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.NOT_ELIGIBLE
    )
    assert app.in_call_screen.render_calls == 1


def test_periodic_visible_tick_refreshes_visible_now_playing_screen() -> None:
    """Visible-tick refreshes should reuse the generic screen opt-in path."""
    harness = OrchestrationHarness.build(playback_state="playing")

    assert harness.app.screen_manager is not None
    assert (
        harness.app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.NOT_ELIGIBLE
    )
    assert harness.screens.now_playing.render_calls == 0

    harness.show_now_playing()
    assert (
        harness.app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.RENDERED
    )
    assert harness.screens.now_playing.render_calls == 1
    assert harness.screens.now_playing.refresh_for_visible_tick_calls == 1


def test_voip_unavailable_event_ends_call_and_restores_music() -> None:
    """VoIP backend loss should tear down the call flow and restore interrupted playback."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=True)
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("in_call")

    harness.publish(
        VoIPAvailabilityChangedEvent(available=False, reason="backend_stopped"),
    )

    assert harness.drain_events() == 1
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert harness.music_fsm.state == MusicState.PLAYING
    assert harness.music_backend.play_calls == 1
    assert harness.screen_manager.current_screen is harness.screens.menu


@pytest.mark.parametrize(
    "terminal_state",
    [CallState.RELEASED, CallState.END, CallState.ERROR],
)
def test_terminal_call_states_end_call_and_restore_music(terminal_state: CallState) -> None:
    """Every terminal backend call state should follow the same teardown path."""
    harness = OrchestrationHarness.build(playback_state="paused", auto_resume=True)
    harness.sync_runtime(
        music_state=MusicState.PAUSED,
        call_state=CallSessionState.ACTIVE,
        music_interrupted_by_call=True,
    )
    harness.push_screens("in_call")

    harness.publish_call_snapshot(terminal_state)

    assert harness.drain_events() == 1
    assert harness.call_fsm.state == CallSessionState.IDLE
    assert harness.music_fsm.state == MusicState.PLAYING
    assert harness.music_backend.play_calls == 1
    assert harness.screen_manager.current_screen is harness.screens.menu


def test_music_unavailable_event_stops_music_and_refreshes_now_playing() -> None:
    """Music backend loss should stop music state and refresh the visible now-playing screen."""
    harness = OrchestrationHarness.build(playback_state="playing")
    harness.show_now_playing()
    harness.sync_runtime(music_state=MusicState.PLAYING, trigger="playback_playing")

    harness.publish(
        MusicAvailabilityChangedEvent(available=False, reason="connection_lost"),
    )

    assert harness.drain_events() == 1
    assert harness.music_fsm.state == MusicState.IDLE
    assert harness.screens.now_playing.render_calls == 1


def test_navigation_updates_runtime_base_state() -> None:
    """Idle navigation should keep the derived runtime state aligned with the active screen."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    screen_manager.push_screen("contacts")
    assert app.bus.drain() == 1
    assert app.app_state_runtime.current_app_state == AppRuntimeState.CALL_IDLE

    screen_manager.pop_screen()
    assert app.bus.drain() == 1
    assert app.app_state_runtime.current_app_state == AppRuntimeState.MENU

    screen_manager.push_screen("playlists")
    assert app.bus.drain() == 1
    assert app.app_state_runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER

    screen_manager.push_screen("power")
    assert app.bus.drain() == 1
    assert app.app_state_runtime.current_app_state == AppRuntimeState.POWER


def test_worker_navigation_waits_for_coordinator_drain_before_syncing_state() -> None:
    """Screen-change callbacks from worker threads should queue runtime sync onto the event bus."""
    app, _, screen_manager = _build_app(playback_state="stopped")

    _navigate_from_worker(screen_manager, "contacts")

    assert screen_manager.current_screen is app.contact_list_screen
    assert app.app_state_runtime.current_app_state == AppRuntimeState.MENU
    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.app_state_runtime.current_app_state == AppRuntimeState.CALL_IDLE


def test_rust_ui_screen_changed_event_wakes_screen_power_and_syncs_state() -> None:
    """Rust screen changes should enter the Python screen-power/state event path."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )
    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    RustUiFacade(app, worker_domain="ui").handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.screen_changed",
            request_id=None,
            payload={"screen": "contacts"},
        )
    )

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen.awake is True
    assert app.app_state_runtime.current_app_state == AppRuntimeState.CALL_IDLE


def test_rust_ui_call_screen_changed_event_wakes_without_overriding_call_state() -> None:
    """Call-owned Rust screens should wake display without becoming base UI state."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )
    app.call_fsm.sync(CallSessionState.INCOMING)
    app.app_state_runtime.sync_app_state("incoming_call")
    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    RustUiFacade(app, worker_domain="ui").handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.screen_changed",
            request_id=None,
            payload={"screen": "incoming_call"},
        )
    )

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen.awake is True
    assert app.app_state_runtime.current_app_state == AppRuntimeState.CALL_INCOMING


def test_main_thread_callback_errors_are_contained_and_drain_continues() -> None:
    """Scheduled UI callbacks should not abort later callbacks or queued app events."""

    app, _, _ = _build_app(playback_state="stopped")
    callback_order: list[str] = []

    def bad_callback() -> None:
        callback_order.append("bad")
        raise RuntimeError("boom")

    def good_callback() -> None:
        callback_order.append("good")

    app.runtime_loop.queue_main_thread_callback(bad_callback)
    app.runtime_loop.queue_main_thread_callback(good_callback)
    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    assert app.runtime_loop.process_pending_main_thread_actions() >= 3
    assert callback_order == ["bad", "good"]


def test_call_end_restores_previous_screen_base_state() -> None:
    """Ending a call should restore the derived state for the screen the user returns to."""
    app, _, screen_manager = _build_app(playback_state="stopped")
    screen_manager.push_screen("playlists")
    assert app.bus.drain() == 1

    app.call_fsm.sync(CallSessionState.ACTIVE)
    app.app_state_runtime.sync_app_state("call_connected")
    screen_manager.push_screen("incoming_call")
    assert app.bus.drain() == 1
    screen_manager.push_screen("in_call")
    assert app.bus.drain() == 1

    worker = threading.Thread(
        target=lambda: app.runtime_loop.queue_main_thread_callback(
        lambda: app.call_runtime.handle_call_ended()
        )
    )
    worker.start()
    worker.join()

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert screen_manager.current_screen is app.playlist_screen
    assert app.app_state_runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER


def test_manager_recovery_schedules_music_reconnect_off_main_thread() -> None:
    """Music recovery should schedule work instead of blocking the coordinator loop."""
    app = YoyoPodApp(simulate=True)
    app.voip_manager = FakeRecoveringVoIPManager([False, True])
    app.music_backend = FakeRecoveringMusicBackend([False, True])
    scheduled_attempts: list[float] = []

    app.recovery_service.start_music_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_manager_recovery(now=0.0)

    assert app.voip_manager.start_calls == 1
    assert app.music_backend.start_calls == 0
    assert scheduled_attempts == [0.0]
    assert app._music_recovery.in_flight
    assert app._voip_recovery.next_attempt_at == 1.0


def test_recovery_service_schedules_music_reconnect_off_main_thread() -> None:
    """The extracted recovery service should keep music reconnects off the loop thread."""
    app = YoyoPodApp(simulate=True)
    app.voip_manager = FakeRecoveringVoIPManager([False, True])
    app.music_backend = FakeRecoveringMusicBackend([False, True])
    scheduled_attempts: list[float] = []

    app.recovery_service.start_music_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_manager_recovery(now=0.0)

    assert app.voip_manager.start_calls == 1
    assert app.music_backend.start_calls == 0
    assert scheduled_attempts == [0.0]
    assert app._music_recovery.in_flight
    assert app._voip_recovery.next_attempt_at == 1.0


def test_recovery_service_skips_music_recovery_while_warm_start_is_in_progress() -> None:
    """Music recovery should not race a background warm-start already in flight."""

    app = YoyoPodApp(simulate=True)
    app.music_backend = FakeRecoveringMusicBackend([True])
    app.music_backend.startup_in_progress = True
    scheduled_attempts: list[float] = []

    app.recovery_service.start_music_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_manager_recovery(now=0.0)

    assert app.music_backend.start_calls == 0
    assert scheduled_attempts == []
    assert app._music_recovery.in_flight is False


def test_recovery_service_skips_unconfigured_voip_recovery() -> None:
    """Unprovisioned SIP config should not trigger a blocking backend restart attempt."""

    app = YoyoPodApp(simulate=True)
    app.voip_manager = FakeRecoveringVoIPManager([True])
    app.voip_manager.config = VoIPConfig(
        sip_server="sip.example.com",
        sip_identity="",
    )

    app.recovery_service.attempt_voip_recovery(0.0)

    assert app.voip_manager.start_calls == 0
    assert app._voip_recovery.next_attempt_at == app._RECOVERY_MAX_DELAY_SECONDS
    assert app._voip_recovery.delay_seconds == app._RECOVERY_MAX_DELAY_SECONDS


def test_recovery_service_no_longer_owns_power_runtime_helpers() -> None:
    """Power polling/watchdog ownership should stay on the dedicated power runtime service."""

    app = YoyoPodApp(simulate=True)

    assert hasattr(app, "power_runtime")
    assert not hasattr(app.recovery_service, "poll_power_status")
    assert not hasattr(app.recovery_service, "start_watchdog")
    assert not hasattr(app.recovery_service, "feed_watchdog_if_due")


def test_recovery_service_schedules_network_reconnect_off_main_thread() -> None:
    """Python should no longer schedule network recovery once Rust owns the domain."""

    app = YoyoPodApp(simulate=False)
    app.network_runtime = SimpleNamespace(snapshot=lambda: None)
    scheduled_attempts: list[float] = []

    app.recovery_service.start_network_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_network_recovery(0.0)

    assert scheduled_attempts == []
    assert app._network_recovery.in_flight is False


def test_recovery_service_skips_network_recovery_in_simulation_mode() -> None:
    """Simulation mode should not launch modem recovery attempts."""

    app = YoyoPodApp(simulate=True)
    app.network_runtime = SimpleNamespace(snapshot=lambda: None)
    scheduled_attempts: list[float] = []

    app.recovery_service.start_network_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_network_recovery(0.0)

    assert scheduled_attempts == []
    assert app._network_recovery.in_flight is False


def test_recovery_service_skips_online_probe_while_network_recovery_is_in_flight() -> None:
    """Coordinator ticks should not launch extra Python recovery work while Rust owns the worker."""

    app = YoyoPodApp(simulate=False)
    app.network_runtime = SimpleNamespace(snapshot=lambda: None)
    app._network_recovery.in_flight = True
    scheduled_attempts: list[float] = []
    app.recovery_service.start_network_recovery_worker = (
        lambda recovery_now: scheduled_attempts.append(recovery_now)
    )

    app.recovery_service.attempt_network_recovery(0.0)

    assert scheduled_attempts == []
    assert app._network_recovery.in_flight is True


def test_music_recovery_backoff_doubles_after_success() -> None:
    """Background music recovery results should update backoff on success and failure."""
    app = YoyoPodApp(simulate=True)
    app.music_backend = FakeRecoveringMusicBackend([False, True])

    app._music_recovery.in_flight = True
    app.recovery_service.handle_recovery_attempt_completed(
        manager="music",
        recovered=False,
        recovery_now=0.0,
    )

    assert app._music_recovery.next_attempt_at == 1.0
    assert app._music_recovery.delay_seconds == 2.0

    app._music_recovery.in_flight = True
    app.recovery_service.handle_recovery_attempt_completed(
        manager="music",
        recovered=False,
        recovery_now=1.0,
    )

    assert app._music_recovery.next_attempt_at == 3.0
    assert app._music_recovery.delay_seconds == 4.0

    app.music_backend._connected = True
    app._music_recovery.in_flight = True
    app.recovery_service.handle_recovery_attempt_completed(
        manager="music",
        recovered=True,
        recovery_now=3.0,
    )

    assert app._music_recovery.next_attempt_at == 0.0
    assert app._music_recovery.delay_seconds == 1.0


def test_network_recovery_backoff_updates_context_after_completion() -> None:
    """Network completion hooks should only clear the in-flight flag after the Rust cutover."""

    app = YoyoPodApp(simulate=True)
    app.context = AppContext()
    app.context.update_network_status(
        network_enabled=True,
        signal_bars=2,
        connection_type="4g",
        connected=True,
        gps_has_fix=True,
    )

    app._network_recovery.in_flight = True
    app.recovery_service.handle_recovery_attempt_completed(
        manager="network",
        recovered=False,
        recovery_now=0.0,
    )

    assert app._network_recovery.next_attempt_at == 0.0
    assert app._network_recovery.delay_seconds == 1.0
    assert app.context.network.enabled is True
    assert app.context.network.signal_strength == 2
    assert app.context.network.connection_type == "4g"
    assert app.context.network.connected is True
    assert app.context.network.gps_has_fix is True
    assert app._network_recovery.in_flight is False


def test_music_recovery_worker_queues_direct_main_thread_completion() -> None:
    """Music recovery workers should queue direct coordinator callbacks instead of typed events."""

    app = YoyoPodApp(simulate=True)
    app.music_backend = FakeRecoveringMusicBackend([True])
    app._music_recovery.in_flight = True

    app.recovery_service.run_music_recovery_attempt(0.0)

    assert app.bus.pending_count() == 0
    assert app.runtime_loop.process_pending_main_thread_actions() == 1
    assert app._music_recovery.in_flight is False
    assert app._music_recovery.next_attempt_at == 0.0


def test_music_recovery_worker_starts_backend_on_main_thread() -> None:
    """Music recovery should marshal backend startup back onto the coordinator thread."""

    class _ThreadAwareMusicBackend(FakeRecoveringMusicBackend):
        def __init__(self) -> None:
            super().__init__([True])
            self.start_thread_ids: list[int] = []

        def start(self) -> bool:
            self.start_thread_ids.append(threading.get_ident())
            return super().start()

    app = YoyoPodApp(simulate=True)
    app.music_backend = _ThreadAwareMusicBackend()
    app._music_recovery.in_flight = True

    worker = threading.Thread(target=lambda: app.recovery_service.run_music_recovery_attempt(0.0))
    worker.start()

    _wait_for(lambda: app.scheduler.pending_count() > 0)

    assert app.music_backend.start_thread_ids == []
    assert app.runtime_loop.process_pending_main_thread_actions() == 1
    _wait_for(lambda: app.scheduler.pending_count() > 0)
    assert app.runtime_loop.process_pending_main_thread_actions() == 1

    worker.join(timeout=1.0)

    assert app.music_backend.start_thread_ids == [app.main_thread_id]
    assert app._music_recovery.in_flight is False
    assert app._music_recovery.next_attempt_at == 0.0


def test_network_recovery_worker_queues_direct_main_thread_completion() -> None:
    """Python network recovery workers should be a no-op after the Rust cutover."""

    app = YoyoPodApp(simulate=False)
    app.context = AppContext()
    app._network_recovery.in_flight = True

    app.recovery_service.run_network_recovery_attempt(0.0)

    assert app.bus.pending_count() == 0
    assert app.runtime_loop.process_pending_main_thread_actions() == 0
    assert app._network_recovery.in_flight is True
    assert app.context.network.connected is False


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

    assert app.boot_service.get_initial_screen_name() == "menu"
    assert AppRuntimeState.ui_state_for_screen_name("menu") == AppRuntimeState.MENU


def test_one_button_profile_starts_on_hub() -> None:
    """Whisplay one-button devices should use the new hub root."""
    app = YoyoPodApp(simulate=True)
    app.context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    app.input_manager = InputManager(interaction_profile=InteractionProfile.ONE_BUTTON)

    assert app.boot_service.get_initial_screen_name() == "hub"
    assert AppRuntimeState.ui_state_for_screen_name("hub") == AppRuntimeState.HUB


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

    _force_power_refresh(app, now=0.0)

    assert app.power_manager.refresh_calls == 1
    assert app.context.power.battery_percent == 55
    assert app.context.power.battery_charging is True
    assert app.context.power.external_power is True
    assert app.context.power.available is True
    assert app.app_state_runtime.power_available is True
    assert app.app_state_runtime.power_snapshot is not None
    assert app.app_state_runtime.power_snapshot.battery.level_percent == 55.4
    assert app.menu_screen.render_calls == 1


def test_periodic_power_refresh_only_renders_visible_power_screen() -> None:
    """The main loop should only re-render the power screen while it is visible."""
    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )

    assert app.screen_manager is not None
    assert (
        app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.NOT_ELIGIBLE
    )
    assert app.power_screen.render_calls == 0
    assert app.power_screen.refresh_for_visible_tick_calls == 0

    screen_manager.push_screen("power")
    assert (
        app.screen_manager.refresh_current_screen_for_visible_tick()
        is VisibleTickRefreshResult.RENDERED
    )
    assert app.power_screen.render_calls == 1
    assert app.power_screen.refresh_for_visible_tick_calls == 1


def test_power_poll_refreshes_visible_power_screen_through_shared_refresh_hook() -> None:
    """Power snapshot refreshes should reuse the generic visible-screen refresh hook."""
    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    screen_manager.push_screen("power")

    _force_power_refresh(app, now=0.0)

    assert app.power_screen.render_calls == 1
    assert app.power_screen.refresh_for_visible_tick_calls == 1


def test_power_poll_honors_interval_and_tracks_unavailable_backend() -> None:
    """Power polling should respect the configured interval and retain availability state."""
    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = FakePowerManager(
        [
            _power_snapshot(
                available=True, battery_percent=61.0, charging=False, power_plugged=False
            ),
            _power_snapshot(available=False, error="I2C not connected"),
        ],
        poll_interval_seconds=30.0,
    )

    _force_power_refresh(app, now=0.0)
    app.power_runtime.poll_status(now=10.0)
    app.power_runtime.poll_status(now=30.0)
    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)
    app.runtime_loop.process_pending_main_thread_actions()

    assert app.power_manager.refresh_calls == 2
    assert app.context.power.battery_percent == 61
    assert app.context.power.available is False
    assert app.context.power.error == "I2C not connected"
    assert app.app_state_runtime.power_available is False
    assert app.menu_screen.render_calls == 2


def test_periodic_power_poll_runs_off_the_coordinator_thread() -> None:
    """Loop-driven power refresh should return immediately and publish results later."""

    refresh_started = threading.Event()
    refresh_release = threading.Event()

    class BlockingPowerManager(FakePowerManager):
        def refresh(self) -> PowerSnapshot:
            refresh_started.set()
            refresh_release.wait(timeout=1.0)
            return super().refresh()

    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = BlockingPowerManager(
        [_power_snapshot(available=True, battery_percent=48.0, charging=False, power_plugged=False)]
    )

    started_at = time.monotonic()
    app.power_runtime.poll_status(now=0.0)
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 0.1
    assert refresh_started.wait(timeout=1.0) is True
    assert app.get_status()["power_refresh_in_flight"] is True
    assert app.menu_screen.render_calls == 0

    refresh_release.set()
    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)
    app.runtime_loop.process_pending_main_thread_actions()

    assert app.power_manager.refresh_calls == 1
    assert app.context.power.battery_percent == 48
    assert app.menu_screen.render_calls == 1
    assert app.get_status()["power_refresh_in_flight"] is False


def test_forced_power_poll_skips_placeholder_snapshot_before_first_refresh() -> None:
    """The initial forced poll should not publish the uninitialized power placeholder."""

    refresh_started = threading.Event()
    refresh_release = threading.Event()
    refreshed_snapshot = _power_snapshot(
        available=True,
        battery_percent=52.0,
        charging=True,
        power_plugged=True,
    )

    class BlockingForcePollPowerManager(FakePowerManager):
        def __init__(self) -> None:
            super().__init__([refreshed_snapshot])

        def refresh(self) -> PowerSnapshot:
            refresh_started.set()
            refresh_release.wait(timeout=1.0)
            return super().refresh()

    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = BlockingForcePollPowerManager()

    started_at = time.monotonic()
    app.power_runtime.poll_status(now=0.0, force=True)
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 0.1
    assert app._power_available is None
    assert app.app_state_runtime.power_snapshot is None
    assert app.menu_screen.render_calls == 0
    assert refresh_started.wait(timeout=1.0) is True
    assert app.get_status()["power_refresh_in_flight"] is True

    refresh_release.set()
    _complete_power_refresh(app)

    assert app.power_manager.refresh_calls == 1
    assert app.context.power.battery_percent == 52
    assert app.context.power.battery_charging is True
    assert app.context.power.external_power is True
    assert app.app_state_runtime.power_snapshot is refreshed_snapshot
    assert app.menu_screen.render_calls == 1


def test_forced_power_poll_uses_new_cached_snapshot_while_refresh_callback_is_pending() -> None:
    """A forced poll should fast-forward a completed worker snapshot without duplicating it later."""

    first_snapshot = _power_snapshot(
        available=True,
        battery_percent=41.0,
        charging=False,
        power_plugged=False,
    )
    second_snapshot = _power_snapshot(
        available=True,
        battery_percent=52.0,
        charging=True,
        power_plugged=True,
    )

    class TwoStepPowerManager(FakePowerManager):
        def __init__(self) -> None:
            super().__init__([first_snapshot, second_snapshot])
            self.second_refresh_started = threading.Event()
            self.second_refresh_release = threading.Event()

        def refresh(self) -> PowerSnapshot:
            if self.refresh_calls == 0:
                return super().refresh()

            self.second_refresh_started.set()
            self.second_refresh_release.wait(timeout=1.0)
            return super().refresh()

    app, _, _ = _build_app(playback_state="stopped")
    app.power_manager = TwoStepPowerManager()

    _force_power_refresh(app, now=0.0)
    assert app.context.power.battery_percent == 41
    assert app.menu_screen.render_calls == 1

    app.power_runtime.poll_status(now=30.0)
    assert app.power_manager.second_refresh_started.wait(timeout=1.0) is True
    assert app.get_status()["power_refresh_in_flight"] is True

    app.power_manager.second_refresh_release.set()
    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)

    started_at = time.monotonic()
    app.power_runtime.poll_status(now=31.0, force=True)
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 0.1
    assert app.context.power.battery_percent == 52
    assert app.context.power.battery_charging is True
    assert app.context.power.external_power is True
    assert app.app_state_runtime.power_snapshot is second_snapshot
    assert app.menu_screen.render_calls == 2

    app.runtime_loop.process_pending_main_thread_actions()
    assert app.get_status()["power_refresh_in_flight"] is False
    assert app.menu_screen.render_calls == 2


def test_screen_timeout_turns_backlight_off_after_inactivity() -> None:
    """Inactivity beyond the configured timeout should sleep the screen."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.update_screen_power(31.0)

    assert app.display.set_backlight_calls == [0.8, 0.0]
    assert app.context.screen.awake is False
    assert app.context.screen.on_seconds == 31
    assert app.context.screen.idle_seconds == 31


def test_screen_power_service_turns_backlight_off_after_inactivity() -> None:
    """The extracted screen-power service should enforce the inactivity timeout."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.update_screen_power(31.0)

    assert app.display.set_backlight_calls == [0.8, 0.0]
    assert app.context.screen.awake is False
    assert app.context.screen.on_seconds == 31
    assert app.context.screen.idle_seconds == 31


def test_screen_power_service_forwards_backlight_to_rust_ui_host() -> None:
    """Rust-host mode should preserve physical backlight sleep/wake commands."""

    app, _, _ = _build_app(playback_state="stopped")
    rust_ui_host = FakeRustUiHost()
    app.display = None
    app.rust_ui_host = rust_ui_host
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.update_screen_power(31.0)
    app.screen_power_service.wake_screen(40.0, render_current=False)

    assert rust_ui_host.backlight_calls == [0.8, 0.0, 0.8]
    assert app.context.screen.awake is True


def test_user_activity_event_wakes_screen_and_refreshes_current_screen() -> None:
    """Queued user activity should wake a sleeping screen and re-render the visible route."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    assert app.context.screen.awake is False
    render_calls_before = app.menu_screen.render_calls

    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen.awake is True
    assert app.menu_screen.render_calls == render_calls_before + 1


def test_rust_ui_input_event_wakes_screen_power_service() -> None:
    """Rust worker input events should use the same activity path as Python input."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    render_calls_before = app.menu_screen.render_calls
    RustUiFacade(app, worker_domain="ui").handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.input",
            request_id=None,
            payload={
                "action": "select",
                "method": "short",
                "timestamp_ms": 1234,
                "duration_ms": 30,
            },
        )
    )

    assert app.runtime_metrics.last_input_activity_action_name == "select"
    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen.awake is True
    assert app.menu_screen.render_calls == render_calls_before + 1


def test_user_activity_event_wakes_screen_and_refreshes_visible_power_screen_hook() -> None:
    """Wake renders should route visible Setup screens through the shared refresh hook."""

    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    screen_manager.push_screen("power")
    assert app.bus.drain() == 1
    app.screen_power_service.sleep_screen(31.0)

    render_calls_before = app.power_screen.render_calls
    refresh_calls_before = app.power_screen.refresh_for_visible_tick_calls

    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.context.screen.awake is True
    assert app.power_screen.render_calls == render_calls_before + 1
    assert app.power_screen.refresh_for_visible_tick_calls == refresh_calls_before + 1


def test_status_exposes_input_and_responsiveness_markers() -> None:
    """Diagnostics status should distinguish raw input liveness from handled input."""

    app, _, _ = _build_app(playback_state="stopped")

    captured_at = time.monotonic() - 0.02
    app.note_input_activity(SimpleNamespace(value="select"), captured_at=captured_at)
    app.note_handled_input(action_name="select", handled_at=time.monotonic())

    app.record_responsiveness_capture(
        captured_at=time.monotonic(),
        reason="coordinator_stall_after_input",
        suspected_scope="input_to_runtime_handoff",
        summary="test capture",
        artifacts={"snapshot": "/tmp/test.json"},
    )

    status = app.get_status()

    assert status["input_activity_age_seconds"] is not None
    assert status["last_input_action"] == "select"
    assert status["handled_input_activity_age_seconds"] is not None
    assert status["last_handled_input_action"] == "select"
    assert status["responsiveness_input_to_action_count"] == 1
    assert status["responsiveness_last_capture_reason"] == "coordinator_stall_after_input"
    assert status["responsiveness_last_capture_scope"] == "input_to_runtime_handoff"
    assert status["responsiveness_last_capture_artifacts"] == {"snapshot": "/tmp/test.json"}


def test_status_uses_cached_output_volume_without_touching_system_mixer() -> None:
    """Runtime status snapshots should not block on live ALSA reads."""

    app, _, _ = _build_app(playback_state="stopped")
    app.context.set_volume(61)

    class FakeOutputVolume:
        def peek_cached_volume(self) -> int:
            return 61

        def get_volume(self) -> int:
            raise AssertionError("status should not call get_volume()")

    app.output_volume = FakeOutputVolume()

    status = app.get_status()

    assert status["volume"] == 61


def test_raw_user_activity_wakes_screen_without_rerendering_current_screen() -> None:
    """Raw button activity should wake the screen without flashing the current view."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    assert app.context.screen.awake is False
    render_calls_before = app.menu_screen.render_calls

    _publish_from_worker(app, UserActivityEvent(action_name=None))

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app.display.set_backlight_calls[-1] == 0.75
    assert app.context.screen.awake is True
    assert app.menu_screen.render_calls == render_calls_before


def test_user_activity_event_wakes_sleeping_lvgl_screen_with_forced_refresh() -> None:
    """LVGL wake should explicitly refresh the active scene after backlight sleep."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app._lvgl_backend = FakeLvglBackend()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=75, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(31.0)

    _publish_from_worker(app, UserActivityEvent(action_name=None))

    assert app.runtime_loop.process_pending_main_thread_actions() >= 1
    assert app._lvgl_backend.force_refresh_calls == 1


def test_screen_on_time_accumulates_across_sleep_and_wake_cycles() -> None:
    """Screen-on metrics should accumulate only while the backlight is awake."""

    app, _, _ = _build_app(playback_state="stopped")
    app.display = FakeDisplay()
    app.app_settings = SimpleNamespace(
        ui=SimpleNamespace(screen_timeout_seconds=300),
        display=SimpleNamespace(brightness=80, backlight_timeout_seconds=30),
    )

    app._screen_timeout_seconds = app.screen_power_service.resolve_screen_timeout_seconds()
    app._active_brightness = app.screen_power_service.resolve_active_brightness()
    app.screen_power_service.configure_screen_power(initial_now=0.0)
    app.screen_power_service.sleep_screen(10.0)
    app.screen_power_service.wake_screen(20.0, render_current=False)
    app.screen_power_service.sleep_screen(25.0)

    assert app.display.set_backlight_calls == [0.8, 0.0, 0.8, 0.0]
    assert app.context.screen.on_seconds == 15
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

    _force_power_refresh(app, now=0.0)

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

    _force_power_refresh(app, now=0.0)

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

    _force_power_refresh(app, now=0.0)
    assert app._pending_shutdown is not None

    _force_power_refresh(app, now=30.0)

    assert app._pending_shutdown is None
    assert app._power_alert is not None
    assert app._power_alert.title == "Power Restored"


def test_expired_power_alert_refreshes_visible_power_screen_through_shared_hook() -> None:
    """Overlay dismissal should reuse the shared refresh path for the Setup screen."""

    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    screen_manager.push_screen("power")
    app._power_alert = PowerAlert(
        title="Low Battery",
        subtitle="15% remaining",
        color=(255, 255, 0),
        expires_at=0.0,
    )

    render_calls_before = app.power_screen.render_calls
    refresh_calls_before = app.power_screen.refresh_for_visible_tick_calls

    handled = app.screen_power_service.update_power_overlays(now=1.0)

    assert handled is False
    assert app._power_alert is None
    assert app.power_screen.render_calls == render_calls_before + 1
    assert app.power_screen.refresh_for_visible_tick_calls == refresh_calls_before + 1


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
    app.shutdown_service.register_power_shutdown_hooks()
    _force_power_refresh(app, now=0.0)

    assert [name for name, _ in power_manager.registered_shutdown_hooks] == ["save_shutdown_state"]
    assert app._pending_shutdown is not None

    app.shutdown_service.process_pending_shutdown(app._pending_shutdown.execute_at)

    assert stop_calls == ["stop"]
    assert power_manager.run_shutdown_hooks_calls == 1
    assert power_manager.shutdown_requested is True
    assert app._shutdown_completed is True

    payload = json.loads(shutdown_state_file.read_text(encoding="utf-8"))
    assert payload["state"] == "menu"
    assert payload["current_screen"] == "menu"
    assert payload["battery_percent"] == 8
    assert payload["external_power"] is False


def test_shutdown_service_runs_hooks_and_requests_system_poweroff(tmp_path) -> None:
    """The extracted shutdown service should own poweroff execution."""

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
    app.shutdown_service.register_power_shutdown_hooks()
    _force_power_refresh(app, now=0.0)

    assert app._pending_shutdown is not None

    app.shutdown_service.process_pending_shutdown(app._pending_shutdown.execute_at)

    assert stop_calls == ["stop"]
    assert power_manager.run_shutdown_hooks_calls == 1
    assert power_manager.shutdown_requested is True
    assert app._shutdown_completed is True

    payload = json.loads(shutdown_state_file.read_text(encoding="utf-8"))
    assert payload["state"] == "menu"
    assert payload["current_screen"] == "menu"


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

    app.power_runtime.start_watchdog(now=0.0)
    app.power_runtime.feed_watchdog_if_due(9.0)
    app.power_runtime.feed_watchdog_if_due(10.0)
    _wait_for(lambda: power_manager.feed_watchdog_calls == 1)
    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)
    app.runtime_loop.process_pending_main_thread_actions()

    assert power_manager.enable_watchdog_calls == 1
    assert power_manager.feed_watchdog_calls == 1
    assert app.get_status()["watchdog_active"] is True
    assert app.get_status()["watchdog_feed_in_flight"] is False


def test_watchdog_feed_runs_off_the_coordinator_thread() -> None:
    """Periodic watchdog feeds should not block the interactive runtime loop."""

    feed_started = threading.Event()
    feed_release = threading.Event()

    class BlockingWatchdogPowerManager(FakePowerManager):
        def feed_watchdog(self) -> bool:
            self.feed_watchdog_calls += 1
            feed_started.set()
            feed_release.wait(timeout=1.0)
            return True

    power_manager = BlockingWatchdogPowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
        watchdog_timeout_seconds=60,
        watchdog_feed_interval_seconds=10.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False

    app.power_runtime.start_watchdog(now=0.0)
    started_at = time.monotonic()
    app.power_runtime.feed_watchdog_if_due(10.0)
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 0.1
    assert feed_started.wait(timeout=1.0) is True
    assert app.get_status()["watchdog_feed_in_flight"] is True

    feed_release.set()
    _wait_for(lambda: (app.get_status()["pending_scheduler_tasks"] or 0) > 0)
    app.runtime_loop.process_pending_main_thread_actions()

    assert power_manager.feed_watchdog_calls == 1
    assert app.get_status()["watchdog_active"] is True
    assert app.get_status()["watchdog_feed_in_flight"] is False


def test_watchdog_start_does_not_wait_for_in_flight_power_refresh() -> None:
    """Enabling the watchdog should not block behind the PiSugar refresh worker."""

    refresh_started = threading.Event()
    refresh_release = threading.Event()

    class BlockingRefreshPowerManager(FakePowerManager):
        def refresh(self) -> PowerSnapshot:
            refresh_started.set()
            refresh_release.wait(timeout=1.0)
            return super().refresh()

    power_manager = BlockingRefreshPowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
        watchdog_timeout_seconds=60,
        watchdog_feed_interval_seconds=10.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False

    app.power_runtime.poll_status(now=0.0)
    assert refresh_started.wait(timeout=1.0) is True
    assert app.get_status()["power_refresh_in_flight"] is True

    started_at = time.monotonic()
    app.power_runtime.start_watchdog(now=0.0)
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 0.1
    assert power_manager.enable_watchdog_calls == 1
    assert app.get_status()["watchdog_active"] is True

    refresh_release.set()
    _complete_power_refresh(app)


def test_intentional_stop_disables_watchdog() -> None:
    """Ordinary app stops should disable the watchdog to avoid reboot loops."""

    power_manager = FakePowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False

    app.power_runtime.start_watchdog(now=0.0)
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
    app.power_runtime.start_watchdog(now=0.0)
    app.shutdown_service.register_power_shutdown_hooks()
    _force_power_refresh(app, now=0.0)
    app.shutdown_service.process_pending_shutdown(app._pending_shutdown.execute_at)

    assert stop_disable_watchdog == [False]
    assert power_manager.disable_watchdog_calls == 0
    assert app.get_status()["watchdog_feed_suppressed"] is True


def test_runtime_loop_service_refreshes_visible_power_screen() -> None:
    """The extracted runtime loop should schedule visible-screen refresh work."""

    app, _, screen_manager = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    screen_manager.push_screen("power")
    render_calls_before = app.power_screen.render_calls

    updated_at = app.runtime_loop.run_iteration(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=0.0,
        screen_update_interval=1.0,
    )

    assert updated_at == 1.0
    assert app.power_screen.render_calls > render_calls_before
    assert app.power_screen.refresh_for_visible_tick_calls > 0


def test_runtime_loop_relaxes_idle_cadence_and_exposes_snapshot() -> None:
    """Idle coordinator state should publish the relaxed cadence instead of the fast loop."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02

    sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = app.get_status()
    assert sleep_seconds == pytest.approx(0.05)
    assert status["runtime_cadence_mode"] == "idle_awake"
    assert status["runtime_cadence_reason"] == "screen_awake_idle"
    assert status["runtime_target_sleep_seconds"] == pytest.approx(0.05)
    assert status["runtime_requested_sleep_seconds"] == pytest.approx(0.05)
    assert status["voip_iterate_interval_seconds"] == pytest.approx(0.02)
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.05)
    assert status["runtime_cadence_age_seconds"] is not None


def test_runtime_loop_uses_slower_screen_off_idle_cadence() -> None:
    """Screen-off idle should stretch loop sleep without Python VoIP deadlines."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02
    app._screen_awake = False
    app._next_voip_iterate_at = 1.05

    sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = app.get_status()
    assert sleep_seconds == pytest.approx(0.1)
    assert app._next_voip_iterate_at == pytest.approx(0.0)
    assert status["runtime_cadence_mode"] == "idle_sleeping"
    assert status["runtime_cadence_reason"] == "screen_sleeping"
    assert status["runtime_target_sleep_seconds"] == pytest.approx(0.1)
    assert status["runtime_requested_sleep_seconds"] == pytest.approx(0.1)
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.1)


def test_runtime_loop_restores_fast_cadence_for_recent_input() -> None:
    """Fresh input should immediately pull the runtime loop back to the fast cadence."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02

    idle_sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )
    assert idle_sleep_seconds == pytest.approx(0.05)

    app._next_voip_iterate_at = 1.05
    app.runtime_metrics.last_input_activity_at = 0.9
    fast_sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = app.get_status()
    assert fast_sleep_seconds == pytest.approx(0.02)
    assert app._next_voip_iterate_at == pytest.approx(0.0)
    assert status["runtime_cadence_mode"] == "latency_sensitive"
    assert status["runtime_cadence_reason"] == "recent_input"
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.02)


def test_runtime_loop_keeps_fast_cadence_during_call_states() -> None:
    """Call-active coordinator states should not relax the runtime cadence."""

    harness = OrchestrationHarness.build(
        power_manager=FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    harness.app.voip_manager = FakeRuntimeLoopVoIPManager()
    harness.app._voip_iterate_interval_seconds = 0.02
    harness.sync_runtime(call_state=CallSessionState.ACTIVE, trigger="call_active")

    sleep_seconds = harness.app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = harness.app.get_status()
    assert sleep_seconds == pytest.approx(0.02)
    assert status["state"] == AppRuntimeState.CALL_ACTIVE.value
    assert status["runtime_cadence_mode"] == "latency_sensitive"
    assert status["runtime_cadence_reason"] == "call_or_connecting_state"
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.02)


def test_runtime_loop_pending_work_uses_nonzero_backlog_cadence() -> None:
    """Queued work should no longer collapse the coordinator into a zero-sleep spin."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02
    app.runtime_loop.queue_main_thread_callback(lambda: None)
    _publish_from_worker(app, UserActivityEvent(action_name="select"))

    sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = app.get_status()
    assert sleep_seconds == pytest.approx(RuntimeLoopService._PENDING_WORK_LOOP_INTERVAL_SECONDS)
    assert status["runtime_cadence_mode"] == "latency_sensitive"
    assert status["runtime_cadence_reason"] == "pending_work"
    assert status["runtime_target_sleep_seconds"] == pytest.approx(
        RuntimeLoopService._PENDING_WORK_LOOP_INTERVAL_SECONDS
    )
    assert status["runtime_requested_sleep_seconds"] == pytest.approx(
        RuntimeLoopService._PENDING_WORK_LOOP_INTERVAL_SECONDS
    )
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.02)


def test_runtime_loop_pending_work_keeps_minimum_nonzero_backlog_cadence() -> None:
    """Backlog cadence should still yield even when the configured VoIP cadence is tiny."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.001
    app.runtime_loop.queue_main_thread_callback(lambda: None)

    sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )

    status = app.get_status()
    assert sleep_seconds == pytest.approx(0.01)
    assert status["runtime_cadence_reason"] == "pending_work"
    assert status["runtime_target_sleep_seconds"] == pytest.approx(0.01)
    assert status["runtime_requested_sleep_seconds"] == pytest.approx(0.01)
    assert status["voip_effective_iterate_interval_seconds"] == pytest.approx(0.01)


def test_runtime_loop_budgets_backlog_and_keeps_protected_work_running() -> None:
    """Queue pressure should defer generic work while LVGL/watchdog keep running."""

    feed_started = threading.Event()
    feed_release = threading.Event()

    class BlockingWatchdogPowerManager(FakePowerManager):
        def feed_watchdog(self) -> bool:
            self.feed_watchdog_calls += 1
            feed_started.set()
            feed_release.wait(timeout=1.0)
            return True

    power_manager = BlockingWatchdogPowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
        watchdog_timeout_seconds=60,
        watchdog_feed_interval_seconds=10.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02
    app._lvgl_backend = FakeLvglBackend()
    app.power_runtime.start_watchdog(now=0.0)

    callback_budget = RuntimeLoopService._SCHEDULER_DRAIN_BUDGET
    event_budget = RuntimeLoopService._BUS_DRAIN_BUDGET
    queued_callbacks = callback_budget + 2
    queued_events = event_budget + 3
    callback_calls: list[int] = []

    for index in range(queued_callbacks):
        app.runtime_loop.queue_main_thread_callback(lambda index=index: callback_calls.append(index))
    for _ in range(queued_events):
        app.bus.publish(UserActivityEvent(action_name="select"))

    app.runtime_loop.run_iteration(
        monotonic_now=10.0,
        current_time=10.0,
        last_screen_update=10.0,
        screen_update_interval=10.0,
    )

    try:
        assert feed_started.wait(timeout=1.0) is True

        status = app.get_status()
        assert app.voip_manager.iterate_calls == 0
        assert app._lvgl_backend.pump_calls == [0]
        assert power_manager.feed_watchdog_calls == 1
        assert status["watchdog_feed_in_flight"] is True
        assert callback_calls == list(range(callback_budget))
        assert status["runtime_scheduler_tasks_drained"] == callback_budget
        assert status["runtime_bus_events_drained"] == event_budget
        assert status["runtime_scheduler_tasks_deferred"] == (
            queued_callbacks - callback_budget
        )
        assert status["runtime_bus_events_deferred"] == queued_events - event_budget
        assert status["runtime_scheduler_drain_budget"] == callback_budget
        assert status["runtime_bus_drain_budget"] == event_budget
        assert status["runtime_scheduler_budget_hit"] is True
        assert status["runtime_bus_event_budget_hit"] is True
        assert status["pending_scheduler_tasks"] >= queued_callbacks - callback_budget
        assert status["pending_bus_events"] == queued_events - event_budget
    finally:
        feed_release.set()
        _wait_for(
            lambda: (app.get_status()["pending_scheduler_tasks"] or 0)
            > (queued_callbacks - callback_budget)
        )
        app.runtime_loop.process_pending_main_thread_actions()


def test_runtime_loop_prioritizes_watchdog_completion_over_scheduler_backlog() -> None:
    """Watchdog completion should bypass generic scheduler backlog and clear in-flight state."""

    power_manager = FakePowerManager(
        [_power_snapshot(available=True, battery_percent=60.0)],
        watchdog_enabled=True,
        watchdog_timeout_seconds=60,
        watchdog_feed_interval_seconds=10.0,
    )
    app, _, _ = _build_app_with_power(power_manager)
    app.simulate = False
    app._watchdog_active = True
    app._watchdog_feed_in_flight = True

    callback_budget = RuntimeLoopService._SCHEDULER_DRAIN_BUDGET
    queued_callbacks = callback_budget + 2
    callback_calls: list[int] = []

    for index in range(queued_callbacks):
        app.runtime_loop.queue_main_thread_callback(lambda index=index: callback_calls.append(index))

    app.power_runtime.run_watchdog_feed_attempt()

    processed = app.runtime_loop._process_pending_main_thread_actions_for_iteration()
    status = app.get_status()

    assert power_manager.feed_watchdog_calls == 1
    assert processed == callback_budget + 1
    assert callback_calls == list(range(callback_budget))
    assert status["watchdog_feed_in_flight"] is False
    assert status["runtime_scheduler_tasks_drained"] == callback_budget
    assert status["runtime_scheduler_tasks_deferred"] == queued_callbacks - callback_budget
    assert status["runtime_scheduler_budget_hit"] is True
    assert status["pending_scheduler_tasks"] == queued_callbacks - callback_budget


def test_runtime_loop_logs_main_thread_drain_budget_hits() -> None:
    """Budget-pressure logs should report both the cap and the deferred backlog."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02

    callback_budget = RuntimeLoopService._SCHEDULER_DRAIN_BUDGET
    event_budget = RuntimeLoopService._BUS_DRAIN_BUDGET
    for _ in range(callback_budget + 1):
        app.runtime_loop.queue_main_thread_callback(lambda: None)
    for _ in range(event_budget + 2):
        app.bus.publish(UserActivityEvent(action_name="select"))

    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(
            f"{message.record['extra'].get('subsystem', '')}|{message.record['message']}"
        ),
        format="{message}",
        level="INFO",
    )
    try:
        app.runtime_loop.run_iteration(
            monotonic_now=1.0,
            current_time=1.0,
            last_screen_update=1.0,
            screen_update_interval=10.0,
        )
    finally:
        logger.remove(sink_id)

    log_text = "\n".join(messages)
    assert "coord|Main-thread drain budget hit:" in log_text
    assert f"scheduler_budget={callback_budget}" in log_text
    assert "scheduler_tasks_deferred=1" in log_text
    assert f"bus_budget={event_budget}" in log_text
    assert "events_deferred=2" in log_text


def test_runtime_loop_leaves_voip_iteration_to_rust_worker() -> None:
    """The coordinator should not start Python VoIP iterate lanes."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    voip_manager = FakeRuntimeLoopVoIPManager(
        background_iterate_enabled=True,
        native_events=2,
        native_iterate_seconds=0.003,
        event_drain_seconds=0.001,
        sample_id=1,
        schedule_delay_seconds=0.004,
        last_started_at=0.96,
        last_completed_at=0.964,
    )
    app.voip_manager = voip_manager
    app._voip_iterate_interval_seconds = 0.02

    sleep_seconds = app.runtime_loop.next_sleep_interval_seconds(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=1.0,
        screen_update_interval=1.0,
    )
    updated_at = app.runtime_loop.run_iteration(
        monotonic_now=1.0,
        current_time=1.0,
        last_screen_update=0.0,
        screen_update_interval=10.0,
    )

    status = app.get_status()
    assert sleep_seconds == pytest.approx(0.05)
    assert updated_at == 0.0
    assert voip_manager.iterate_calls == 0
    assert voip_manager.ensure_background_iterate_running_calls == 0
    assert voip_manager.housekeeping_calls == 1
    assert voip_manager.interval_updates == []
    assert status["voip_schedule_delay_seconds"] is None
    assert status["voip_iterate_duration_seconds"] is None
    assert status["voip_native_iterate_duration_seconds"] is None
    assert status["voip_event_drain_duration_seconds"] is None
    assert status["voip_iterate_native_events"] is None
    assert status["voip_iterate_age_seconds"] is None


def test_runtime_loop_does_not_log_python_voip_iterate_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust-owned VoIP should not produce Python iterate timing diagnostics."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    voip_manager = FakeRuntimeLoopVoIPManager(
        native_events=3,
        native_iterate_seconds=0.08,
        event_drain_seconds=0.03,
    )
    app.voip_manager = voip_manager
    app._voip_iterate_interval_seconds = 0.02

    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(
            f"{message.record['extra'].get('subsystem', '')}|{message.record['message']}"
        ),
        format="{message}",
        level="INFO",
    )
    monkeypatch.setattr(RuntimeLoopService, "_VOIP_TIMING_SUMMARY_INTERVAL_SECONDS", 0.0)
    try:
        app.runtime_loop.run_iteration(
            monotonic_now=1.0,
            current_time=1.0,
            last_screen_update=0.0,
            screen_update_interval=10.0,
        )
        app.runtime_loop.run_iteration(
            monotonic_now=1.25,
            current_time=1.25,
            last_screen_update=1.0,
            screen_update_interval=10.0,
        )
    finally:
        logger.remove(sink_id)

    log_text = "\n".join(messages)
    assert "coord|Runtime loop blocked:" in log_text
    assert "voip|VoIP iterate timing drift:" not in log_text
    assert "native_iterate_ms=80.0" not in log_text
    assert voip_manager.iterate_calls == 0

    status = app.get_status()
    assert status["runtime_loop_gap_seconds"] == pytest.approx(0.25)
    assert status["voip_schedule_delay_seconds"] is None
    assert status["voip_iterate_duration_seconds"] is None
    assert status["voip_native_iterate_duration_seconds"] is None
    assert status["voip_event_drain_duration_seconds"] is None
    assert status["voip_iterate_native_events"] is None
    assert status["voip_iterate_interval_seconds"] == pytest.approx(0.02)


def test_runtime_loop_logs_named_blocking_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long coordinator steps should identify the blocking span in the logs and status."""

    app, _, _ = _build_app_with_power(
        FakePowerManager([_power_snapshot(available=True, battery_percent=55.0)])
    )
    app.voip_manager = FakeRuntimeLoopVoIPManager()
    app._voip_iterate_interval_seconds = 0.02
    app.runtime_loop.process_pending_main_thread_actions()

    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(
            f"{message.record['extra'].get('subsystem', '')}|{message.record['message']}"
        ),
        format="{message}",
        level="INFO",
    )
    monkeypatch.setattr(
        RuntimeLoopService,
        "_runtime_blocking_span_warning_seconds",
        lambda self: 0.01,
    )
    monkeypatch.setattr(RuntimeLoopService, "_VOIP_TIMING_SUMMARY_INTERVAL_SECONDS", 0.0)
    original_poll_power_status = app.power_runtime.poll_status

    def slow_poll_power_status(*, now: float | None = None, force: bool = False) -> None:
        time.sleep(0.02)
        original_poll_power_status(now=now, force=force)

    app.power_runtime.poll_status = slow_poll_power_status
    try:
        app.runtime_loop.run_iteration(
            monotonic_now=1.0,
            current_time=1.0,
            last_screen_update=0.0,
            screen_update_interval=10.0,
        )
    finally:
        logger.remove(sink_id)

    log_text = "\n".join(messages)
    assert "coord|Coordinator blocking span: span=power_poll" in log_text

    status = app.get_status()
    assert status["runtime_blocking_span_name"] == "power_poll"
    assert status["runtime_blocking_span_seconds"] is not None
    assert status["runtime_blocking_span_age_seconds"] is not None
