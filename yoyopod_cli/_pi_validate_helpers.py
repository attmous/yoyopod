"""yoyopod_cli/_pi_validate_helpers.py — inlined soak helpers for pi_validate.

Shared helper functions for target stability and navigation validation.
This module is the canonical home for validation soak helpers.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol, cast

from loguru import logger

from yoyopod_cli.music_fixtures import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    ProvisionedTestMusicLibrary,
    provision_test_music_library,
)
from yoyopod.core.events import UserActivityEvent
from yoyopod.ui.input import InputAction, InteractionProfile


class _NavigationSoakAppHandle(Protocol):
    """Minimal runtime surface used by soak helpers."""

    @property
    def config_dir(self) -> str:
        """Return the config directory used for the soak app."""

    @property
    def simulate(self) -> bool:
        """Return whether the soak app is running in simulation mode."""

    @property
    def display(self) -> Any:
        """Return the active display facade."""

    @property
    def screen_manager(self) -> Any:
        """Return the active screen manager."""

    @property
    def input_manager(self) -> Any:
        """Return the active input manager."""

    @property
    def local_music_service(self) -> Any:
        """Return the local music service used by the soak."""

    @property
    def music_backend(self) -> Any:
        """Return the music backend used by the soak."""

    @property
    def runtime_loop(self) -> Any:
        """Return the runtime loop service."""

    @property
    def worker_supervisor(self) -> Any:
        """Return the managed worker supervisor."""

    @property
    def recovery_service(self) -> Any:
        """Return the recovery service."""

    @property
    def power_runtime(self) -> Any:
        """Return the power runtime facade."""

    @property
    def screen_power_service(self) -> Any:
        """Return the screen power service."""

    @property
    def scheduler(self) -> Any:
        """Return the main-thread scheduler used by the soak app."""

    @property
    def bus(self) -> Any:
        """Return the typed event bus."""

    @property
    def event_bus(self) -> Any:
        """Return the typed event bus."""

    @property
    def context(self) -> Any:
        """Return the shared runtime context."""

    def setup(self) -> bool:
        """Initialize app resources."""

    def stop(self) -> None:
        """Shut down app resources."""

    @property
    def voip_iterate_interval_seconds(self) -> float:
        """Return the configured runtime-loop VoIP iterate cadence."""

    @property
    def screen_timeout_seconds(self) -> float:
        """Return the configured inactivity timeout used for screen sleep."""

    @property
    def shutdown_completed(self) -> bool:
        """Return whether the app completed shutdown during the soak."""

    def simulate_inactivity(self, *, idle_for_seconds: float) -> None:
        """Pretend the app has been idle long enough to trigger sleep."""


@dataclass(slots=True)
class _YoyoPodAppNavigationSoakHandle:
    """Adapter that exposes a stable soak surface for ``YoyoPodApp``."""

    _app: Any

    @property
    def config_dir(self) -> str:
        return str(self._app.config_dir)

    @property
    def simulate(self) -> bool:
        return bool(self._app.simulate)

    @property
    def display(self) -> Any:
        return self._app.display

    @property
    def screen_manager(self) -> Any:
        return self._app.screen_manager

    @property
    def input_manager(self) -> Any:
        return self._app.input_manager

    @property
    def local_music_service(self) -> Any:
        return self._app.local_music_service

    @property
    def music_backend(self) -> Any:
        return self._app.music_backend

    @property
    def runtime_loop(self) -> Any:
        return self._app.runtime_loop

    @property
    def worker_supervisor(self) -> Any:
        return self._app.worker_supervisor

    @property
    def recovery_service(self) -> Any:
        return self._app.recovery_service

    @property
    def power_runtime(self) -> Any:
        return self._app.power_runtime

    @property
    def screen_power_service(self) -> Any:
        return self._app.screen_power_service

    @property
    def scheduler(self) -> Any:
        return self._app.scheduler

    @property
    def bus(self) -> Any:
        return self._app.bus

    @property
    def event_bus(self) -> Any:
        return self._app.bus

    @property
    def context(self) -> Any:
        return self._app.context

    def setup(self) -> bool:
        return bool(self._app.setup())

    def stop(self) -> None:
        self._app.stop()

    @property
    def voip_iterate_interval_seconds(self) -> float:
        runtime_loop = self.runtime_loop
        if runtime_loop is None:
            raise NavigationSoakError("runtime loop is unavailable for navigation soak")
        return float(runtime_loop.configured_voip_iterate_interval_seconds)

    @property
    def screen_timeout_seconds(self) -> float:
        return float(getattr(self._app, "_screen_timeout_seconds", 0.0))

    @property
    def shutdown_completed(self) -> bool:
        return bool(getattr(self._app, "_shutdown_completed", False))

    def simulate_inactivity(self, *, idle_for_seconds: float) -> None:
        setattr(
            self._app,
            "_last_user_activity_at",
            time.monotonic() - max(0.0, idle_for_seconds),
        )


class _NavigationSoakAppFactory(Protocol):
    """Factory for constructing a narrow app handle for soak execution."""

    def __call__(self, *, config_dir: str, simulate: bool) -> _NavigationSoakAppHandle:
        """Create a new app handle for a soak run."""


def _default_app_factory(*, config_dir: str, simulate: bool) -> _NavigationSoakAppHandle:
    """Default app factory used when callers do not provide one."""

    from yoyopod.app import YoyoPodApp

    return _YoyoPodAppNavigationSoakHandle(YoyoPodApp(config_dir=config_dir, simulate=simulate))


# ---------------------------------------------------------------------------
# Stability soak helpers
# Used by: `yoyopod_cli pi_validate stability` and `yoyopod_cli pi_validate lvgl`
# ---------------------------------------------------------------------------


class NavigationSoakError(RuntimeError):
    """Raised when the target navigation soak cannot complete successfully."""


@dataclass(frozen=True, slots=True)
class NavigationSoakStep:
    """One deterministic transition or simulated click in the soak plan."""

    kind: str
    description: str
    target: str | None = None
    action: InputAction | None = None
    wait_for_route: str | None = None
    expect_track_loaded: bool = False
    reset_selection_after_wait: bool = False


@dataclass(frozen=True, slots=True)
class NavigationSoakReport:
    """Compact result summary for one navigation and idle stability pass."""

    cycles: int
    actions: int
    transitions: int
    final_route: str
    sleep_details: str
    music_enabled: bool
    music_state: str
    track_name: str | None
    music_dir: Path | None

    def summary(self) -> str:
        """Return a stable human-readable summary string."""

        details = [
            "backend=lvgl",
            f"cycles={self.cycles}",
            f"actions={self.actions}",
            f"transitions={self.transitions}",
            f"final_screen={self.final_route}",
            self.sleep_details,
        ]
        if self.music_enabled:
            details.append(f"music_state={self.music_state}")
            if self.track_name:
                details.append(f"track={self.track_name}")
            if self.music_dir is not None:
                details.append(f"music_dir={self.music_dir}")
        return ", ".join(details)


def build_navigation_soak_plan(*, with_music: bool) -> tuple[NavigationSoakStep, ...]:
    """Build the deterministic screen-and-click soak plan for the target app."""

    steps: list[NavigationSoakStep] = [
        NavigationSoakStep("replace", "Reset to the root hub", target="hub"),
        NavigationSoakStep(
            "action",
            "Open Listen from the hub",
            action=InputAction.SELECT,
            wait_for_route="listen",
            reset_selection_after_wait=True,
        ),
        NavigationSoakStep(
            "action",
            "Open Playlists from Listen",
            action=InputAction.SELECT,
            wait_for_route="playlists",
            reset_selection_after_wait=True,
        ),
    ]

    if with_music:
        steps.extend(
            [
                NavigationSoakStep(
                    "action",
                    "Load the first playlist into Now Playing",
                    action=InputAction.SELECT,
                    wait_for_route="now_playing",
                    expect_track_loaded=True,
                ),
                NavigationSoakStep(
                    "action",
                    "Pause playback from Now Playing",
                    action=InputAction.PLAY_PAUSE,
                ),
                NavigationSoakStep(
                    "action",
                    "Resume playback from Now Playing",
                    action=InputAction.PLAY_PAUSE,
                ),
                NavigationSoakStep(
                    "action",
                    "Skip to the next track",
                    action=InputAction.NEXT_TRACK,
                    expect_track_loaded=True,
                ),
                NavigationSoakStep(
                    "action",
                    "Return to Playlists",
                    action=InputAction.BACK,
                    wait_for_route="playlists",
                    reset_selection_after_wait=True,
                ),
            ]
        )

    steps.extend(
        [
            NavigationSoakStep(
                "action",
                "Return to Listen",
                action=InputAction.BACK,
                wait_for_route="listen",
                reset_selection_after_wait=True,
            ),
            NavigationSoakStep(
                "action",
                "Move to the Recent row",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Recent tracks",
                action=InputAction.SELECT,
                wait_for_route="recent_tracks",
            ),
            NavigationSoakStep(
                "action",
                "Return to Listen from Recent",
                action=InputAction.BACK,
                wait_for_route="listen",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub",
                action=InputAction.BACK,
                wait_for_route="hub",
                reset_selection_after_wait=True,
            ),
            NavigationSoakStep(
                "action",
                "Advance to Talk",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Talk",
                action=InputAction.SELECT,
                wait_for_route="call",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Talk",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
            NavigationSoakStep(
                "action",
                "Advance to Ask",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Ask",
                action=InputAction.SELECT,
                wait_for_route="ask",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Ask",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
            NavigationSoakStep(
                "action",
                "Advance to Setup",
                action=InputAction.ADVANCE,
            ),
            NavigationSoakStep(
                "action",
                "Open Setup",
                action=InputAction.SELECT,
                wait_for_route="power",
            ),
            NavigationSoakStep(
                "action",
                "Return to the hub from Setup",
                action=InputAction.BACK,
                wait_for_route="hub",
            ),
        ]
    )
    return tuple(steps)


@contextmanager
def _temporary_env(updates: dict[str, str]) -> Iterator[None]:
    """Apply environment overrides for the lifetime of one soak run."""

    original_values = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for name, previous in original_values.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


def _pump_app(app: _NavigationSoakAppHandle, duration_seconds: float) -> None:
    """Pump the coordinator-thread services without entering the full app loop."""

    deadline = time.monotonic() + max(0.0, duration_seconds)
    while time.monotonic() < deadline:
        app.runtime_loop.process_pending_main_thread_actions()
        worker_supervisor = getattr(app, "worker_supervisor", None)
        if worker_supervisor is not None:
            worker_supervisor.poll()
        now = time.monotonic()
        app.recovery_service.attempt_manager_recovery()
        app.power_runtime.poll_status(now=now)
        app.runtime_loop.pump_lvgl_backend(now)
        app.power_runtime.feed_watchdog_if_due(now)
        app.screen_power_service.update_screen_power(now)
        time.sleep(0.05)


def _current_route(app: _NavigationSoakAppHandle) -> str:
    """Return the current route name or a stable placeholder."""

    if app.screen_manager is None or app.screen_manager.current_screen is None:
        return "none"
    route_name = app.screen_manager.current_screen.route_name
    if route_name:
        return str(route_name)
    return str(app.screen_manager.current_screen.name)


def _dispatch_action(app: _NavigationSoakAppHandle, action: InputAction) -> None:
    """Drive one semantic action through the same screen handler path as live input."""

    if app.screen_manager is None or app.screen_manager.current_screen is None:
        raise NavigationSoakError("screen manager is not initialized")

    if app.input_manager is not None:
        app.input_manager.simulate_action(action)
        return

    previous_screen = app.screen_manager.current_screen
    previous_screen.handle_action(action)
    navigation_request = previous_screen.consume_navigation_request()
    if navigation_request is not None:
        app.screen_manager.apply_navigation_request(
            navigation_request,
            source_screen=previous_screen,
        )
    if app.screen_manager.current_screen is previous_screen:
        app.screen_manager.refresh_current_screen()


def _reset_selection(screen: object) -> None:
    """Reset retained carousel/list selection when the screen supports it."""

    if hasattr(screen, "selected_index"):
        screen.selected_index = 0


def _wait_for_route(
    app: _NavigationSoakAppHandle,
    route_name: str,
    *,
    timeout_seconds: float,
) -> None:
    """Pump the app until the requested route becomes active."""

    deadline = time.monotonic() + max(0.1, timeout_seconds)
    last_route = _current_route(app)
    while time.monotonic() < deadline:
        if last_route == route_name:
            return
        _pump_app(app, 0.05)
        last_route = _current_route(app)
    if last_route == route_name:
        return
    raise NavigationSoakError(f"navigation soak expected route '{route_name}', got '{last_route}'")


def _wait_for_track(
    app: _NavigationSoakAppHandle,
    *,
    timeout_seconds: float,
    expected_library: ProvisionedTestMusicLibrary | None,
) -> str:
    """Wait for one playback track to appear after playlist navigation."""

    if app.music_backend is None:
        raise NavigationSoakError("music backend is unavailable for playback soak")

    expected_uris = (
        {str(path) for path in expected_library.track_paths}
        if expected_library is not None
        else None
    )
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while time.monotonic() < deadline:
        current_track = app.music_backend.get_current_track()
        if current_track is not None:
            if expected_uris is None or current_track.uri in expected_uris:
                return str(current_track.name)
        _pump_app(app, 0.05)

    current_track = app.music_backend.get_current_track() if app.music_backend is not None else None
    current_uri = current_track.uri if current_track is not None else "none"
    raise NavigationSoakError(
        "navigation soak did not load a validation track; " f"current_track={current_uri}"
    )


def _exercise_sleep_wake(app: _NavigationSoakAppHandle) -> str:
    """Force one idle sleep/wake cycle against the current app instance."""

    timeout_seconds = max(1.0, app.screen_timeout_seconds)
    app.simulate_inactivity(idle_for_seconds=timeout_seconds + 1.0)
    _pump_app(app, 0.35)
    if app.context is None or app.context.screen.awake:
        raise NavigationSoakError("screen did not enter sleep during soak")

    app.scheduler.run_on_main(
        lambda: app.bus.publish(UserActivityEvent(action_name="navigation_soak"))
    )
    _pump_app(app, 0.35)
    if app.context is None or not app.context.screen.awake:
        raise NavigationSoakError("screen did not wake after simulated activity")

    return "sleep/wake ok"


def _prepare_validation_music_dir(
    *,
    with_music: bool,
    provision_test_music: bool,
    test_music_dir: str,
) -> tuple[Path | None, ProvisionedTestMusicLibrary | None]:
    """Resolve and optionally provision the dedicated music directory for the soak."""

    if not with_music:
        return None, None

    resolved_dir = Path(test_music_dir or DEFAULT_TEST_MUSIC_TARGET_DIR).expanduser().resolve()
    if provision_test_music:
        library = provision_test_music_library(resolved_dir)
        return library.target_dir, library

    return resolved_dir, None


def run_navigation_idle_soak(
    *,
    config_dir: str = "config",
    simulate: bool = False,
    cycles: int = 2,
    hold_seconds: float = 0.2,
    idle_seconds: float = 1.0,
    skip_sleep: bool = False,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR,
    app_factory: _NavigationSoakAppFactory | None = None,
) -> NavigationSoakReport:
    """Run the deterministic target-side navigation and idle stability soak."""

    if app_factory is None:
        # Test seam so helper unit tests do not need to import the full runtime.
        app_factory = _default_app_factory

    music_dir, expected_library = _prepare_validation_music_dir(
        with_music=with_music,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
    )
    env_updates = {}
    if music_dir is not None:
        env_updates["YOYOPOD_MUSIC_DIR"] = str(music_dir)

    with _temporary_env(env_updates):
        app = app_factory(config_dir=config_dir, simulate=simulate)
        if not app.setup():
            raise NavigationSoakError("app setup failed")

        try:
            if app.display is None or app.screen_manager is None:
                raise NavigationSoakError("display or screen manager not initialized")
            if app.display.backend_kind != "lvgl":
                raise NavigationSoakError(f"backend is {app.display.backend_kind}, expected lvgl")
            if with_music and (app.local_music_service is None or app.music_backend is None):
                raise NavigationSoakError("music services are unavailable for playback soak")

            actions = 0
            transitions = 0
            plan = build_navigation_soak_plan(with_music=with_music)
            wait_timeout_seconds = max(1.0, hold_seconds + 0.8)
            for cycle_index in range(max(1, cycles)):
                logger.info(
                    "Running target navigation soak cycle {}/{} (with_music={})",
                    cycle_index + 1,
                    max(1, cycles),
                    with_music,
                )
                for step in plan:
                    previous_route = _current_route(app)
                    logger.debug("Navigation soak step: {}", step.description)
                    if step.kind == "replace":
                        assert step.target is not None
                        app.screen_manager.replace_screen(step.target)
                        _reset_selection(app.screen_manager.current_screen)
                    elif step.kind == "action":
                        assert step.action is not None
                        _dispatch_action(app, step.action)
                        actions += 1
                    else:
                        raise NavigationSoakError(f"unsupported soak step kind: {step.kind}")

                    if step.wait_for_route is not None:
                        _wait_for_route(
                            app,
                            step.wait_for_route,
                            timeout_seconds=wait_timeout_seconds,
                        )
                        if step.reset_selection_after_wait:
                            _reset_selection(app.screen_manager.current_screen)
                    _pump_app(app, hold_seconds)

                    if step.expect_track_loaded:
                        _wait_for_track(
                            app,
                            timeout_seconds=wait_timeout_seconds,
                            expected_library=expected_library,
                        )

                    if _current_route(app) != previous_route:
                        transitions += 1

                if idle_seconds > 0:
                    logger.debug("Navigation soak idling for {:.2f}s", idle_seconds)
                    _pump_app(app, idle_seconds)

            sleep_details = "sleep/wake skipped"
            if not skip_sleep:
                sleep_details = _exercise_sleep_wake(app)

            current_track = app.music_backend.get_current_track() if app.music_backend else None
            music_state = (
                app.music_backend.get_playback_state()
                if with_music and app.music_backend is not None
                else "disabled"
            )
            return NavigationSoakReport(
                cycles=max(1, cycles),
                actions=actions,
                transitions=transitions,
                final_route=_current_route(app),
                sleep_details=sleep_details,
                music_enabled=with_music,
                music_state=music_state,
                track_name=current_track.name if current_track is not None else None,
                music_dir=music_dir,
            )
        finally:
            app.stop()


# ---------------------------------------------------------------------------
# Navigation soak helpers
# Used by: `yoyopod_cli pi_validate navigation`
# ---------------------------------------------------------------------------


class NavigationSoakFailure(RuntimeError):
    """Raised when the navigation soak cannot complete its expected path."""


@dataclass(slots=True)
class NavigationSoakStats:
    """Accumulate compact soak diagnostics for the final summary."""

    actions: int = 0
    visited_screens: set[str] = field(default_factory=set)
    explicit_idle_seconds: float = 0.0
    max_runtime_iteration_ms: float = 0.0
    max_runtime_loop_gap_ms: float = 0.0
    max_voip_schedule_delay_ms: float = 0.0
    heaviest_blocking_span_name: str | None = None
    heaviest_blocking_span_ms: float = 0.0
    last_track_name: str | None = None
    playback_verified: bool = False
    sleep_wake_status: str = "skipped"

    def observe_snapshot(self, snapshot: dict[str, float | int | str | bool | None]) -> None:
        """Record high-level loop timing from one runtime snapshot."""

        runtime_iteration = snapshot.get("runtime_iteration_seconds")
        if runtime_iteration is not None:
            self.max_runtime_iteration_ms = max(
                self.max_runtime_iteration_ms,
                float(runtime_iteration) * 1000.0,
            )

        loop_gap = snapshot.get("runtime_loop_gap_seconds")
        if loop_gap is not None:
            self.max_runtime_loop_gap_ms = max(
                self.max_runtime_loop_gap_ms,
                float(loop_gap) * 1000.0,
            )

        voip_schedule_delay = snapshot.get("voip_schedule_delay_seconds")
        if voip_schedule_delay is not None:
            self.max_voip_schedule_delay_ms = max(
                self.max_voip_schedule_delay_ms,
                float(voip_schedule_delay) * 1000.0,
            )

        blocking_name = snapshot.get("runtime_blocking_span_name")
        blocking_seconds = snapshot.get("runtime_blocking_span_seconds")
        if blocking_name and blocking_seconds is not None:
            blocking_ms = float(blocking_seconds) * 1000.0
            if blocking_ms >= self.heaviest_blocking_span_ms:
                self.heaviest_blocking_span_ms = blocking_ms
                self.heaviest_blocking_span_name = str(blocking_name)


@contextmanager
def _temporary_env_var(name: str, value: str | None) -> Iterator[None]:
    """Temporarily override one environment variable."""

    previous = os.environ.get(name)
    if value is None:
        yield
        return

    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


class _RuntimePump:
    """Drive the app loop without entering the long-running production loop."""

    def __init__(self, app: _NavigationSoakAppHandle, stats: NavigationSoakStats) -> None:
        self._app = app
        self._stats = stats
        self._last_screen_update = time.time()
        self._screen_update_interval = 1.0

    def run_for(self, duration_seconds: float) -> None:
        """Pump the app for the requested duration."""

        deadline = time.monotonic() + max(0.0, duration_seconds)
        while time.monotonic() < deadline:
            time.sleep(min(0.05, max(0.01, self._app.voip_iterate_interval_seconds)))
            monotonic_now = time.monotonic()
            current_time = time.time()
            iteration_started_at = time.monotonic()
            self._last_screen_update = self._app.runtime_loop.run_iteration(
                monotonic_now=monotonic_now,
                current_time=current_time,
                last_screen_update=self._last_screen_update,
                screen_update_interval=self._screen_update_interval,
            )
            iteration_duration_ms = (time.monotonic() - iteration_started_at) * 1000.0
            self._stats.max_runtime_iteration_ms = max(
                self._stats.max_runtime_iteration_ms,
                iteration_duration_ms,
            )

            current_screen = self._app.screen_manager.get_current_screen()  # type: ignore[union-attr]
            if current_screen is not None and current_screen.route_name is not None:
                self._stats.visited_screens.add(current_screen.route_name)

            snapshot = self._app.runtime_loop.timing_snapshot(now=monotonic_now)
            self._stats.observe_snapshot(snapshot)

            if self._app.shutdown_completed:
                raise NavigationSoakFailure(
                    "app completed shutdown unexpectedly during navigation soak"
                )


class NavigationSoakRunner:
    """Exercise the target one-button UI with repeatable action-driven flows."""

    _PLAYBACK_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        *,
        config_dir: str,
        cycles: int,
        hold_seconds: float,
        idle_seconds: float,
        tail_idle_seconds: float,
        with_playback: bool,
        provision_test_music: bool,
        test_music_dir: str,
        skip_sleep: bool,
        app_factory: _NavigationSoakAppFactory | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.cycles = max(1, cycles)
        self.hold_seconds = max(0.05, hold_seconds)
        self.idle_seconds = max(0.0, idle_seconds)
        self.tail_idle_seconds = max(0.0, tail_idle_seconds)
        self.with_playback = with_playback
        self.provision_test_music = provision_test_music
        self.test_music_dir = test_music_dir
        self.skip_sleep = skip_sleep

        self.stats = NavigationSoakStats()
        self._app: _NavigationSoakAppHandle | None = None
        self._pump: _RuntimePump | None = None
        # Test seam so unit tests can drive the runner without importing YoyoPodApp.
        self._app_factory = _default_app_factory if app_factory is None else app_factory

    def run(self) -> tuple[bool, str]:
        """Run the full soak and return success plus one-line details."""

        music_dir_override = None
        if self.with_playback and self.provision_test_music:
            library = provision_test_music_library(Path(self.test_music_dir))
            music_dir_override = str(library.target_dir)
            logger.info(
                "Navigation soak provisioned validation music at {}",
                music_dir_override,
            )

        with _temporary_env_var("YOYOPOD_MUSIC_DIR", music_dir_override):
            app = self._app_factory(config_dir=self.config_dir, simulate=False)
            self._app = app
            if not app.setup():
                try:
                    app.stop()
                except Exception:
                    logger.exception("Navigation soak cleanup failed after unsuccessful app setup")
                return False, "app setup failed"

            try:
                if app.display is None or app.screen_manager is None or app.input_manager is None:
                    return False, "display, screen manager, or input manager not initialized"
                if app.display.backend_kind != "lvgl":
                    return False, f"backend is {app.display.backend_kind}, expected lvgl"
                if app.input_manager.interaction_profile != InteractionProfile.ONE_BUTTON:
                    profile_name = app.input_manager.interaction_profile.value
                    return False, f"profile is {profile_name}, expected one_button"

                app.power_runtime.start_watchdog(now=time.monotonic())
                self._pump = _RuntimePump(app, self.stats)
                self._pump.run_for(self.hold_seconds)

                self._require_screen("hub")
                for cycle_number in range(1, self.cycles + 1):
                    logger.info(
                        "Navigation soak cycle {}/{}",
                        cycle_number,
                        self.cycles,
                    )
                    self._exercise_cycle()

                self._idle_phase("hub_tail_idle", self.tail_idle_seconds)
                self._exercise_sleep_wake()
            except NavigationSoakFailure as exc:
                return False, str(exc)
            finally:
                app.stop()

        return True, self._summary_details()

    @property
    def app(self) -> _NavigationSoakAppHandle:
        """Return the active app or raise when the runner is uninitialized."""

        if self._app is None:
            raise NavigationSoakFailure("navigation soak app is not initialized")
        return self._app

    @property
    def pump(self) -> _RuntimePump:
        """Return the runtime pump or raise when the runner is uninitialized."""

        if self._pump is None:
            raise NavigationSoakFailure("navigation soak runtime pump is not initialized")
        return self._pump

    def _summary_details(self) -> str:
        """Return a compact summary string for CLI output."""

        blocking_span = "none"
        if self.stats.heaviest_blocking_span_name is not None:
            blocking_span = (
                f"{self.stats.heaviest_blocking_span_name}:"
                f"{self.stats.heaviest_blocking_span_ms:.1f}ms"
            )

        screen_list = ",".join(sorted(self.stats.visited_screens)) or "none"
        playback_state = "verified" if self.stats.playback_verified else "not_requested"
        if self.with_playback and not self.stats.playback_verified:
            playback_state = "requested_not_verified"

        track_name = self.stats.last_track_name or "none"
        return (
            f"profile=one_button, cycles={self.cycles}, actions={self.stats.actions}, "
            f"screens={screen_list}, explicit_idle_s={self.stats.explicit_idle_seconds:.1f}, "
            f"playback={playback_state}, last_track={track_name}, "
            f"max_iteration_ms={self.stats.max_runtime_iteration_ms:.1f}, "
            f"max_loop_gap_ms={self.stats.max_runtime_loop_gap_ms:.1f}, "
            f"max_voip_delay_ms={self.stats.max_voip_schedule_delay_ms:.1f}, "
            f"heaviest_span={blocking_span}, sleep_wake={self.stats.sleep_wake_status}"
        )

    def _current_screen_name(self) -> str:
        """Return the active route name."""

        current_screen = self.app.screen_manager.get_current_screen()  # type: ignore[union-attr]
        route_name = None if current_screen is None else current_screen.route_name
        return route_name or "unknown"

    def _require_screen(self, expected_screen: str) -> None:
        """Assert the active route name matches the expected screen."""

        actual_screen = self._current_screen_name()
        if actual_screen != expected_screen:
            raise NavigationSoakFailure(f"expected screen {expected_screen}, got {actual_screen}")

    def _simulate_action(
        self,
        action: InputAction,
        *,
        expected_screen: str | None = None,
        label: str,
        settle_seconds: float | None = None,
    ) -> None:
        """Send one semantic action through the real input dispatcher."""

        logger.info(
            "Navigation soak action: {} on {}",
            label,
            self._current_screen_name(),
        )
        self.app.input_manager.simulate_action(action)  # type: ignore[union-attr]
        self.stats.actions += 1
        self.pump.run_for(self.hold_seconds if settle_seconds is None else settle_seconds)

        if expected_screen is not None:
            actual_screen = self._current_screen_name()
            if actual_screen != expected_screen:
                raise NavigationSoakFailure(
                    f"{label} expected {expected_screen}, got {actual_screen}"
                )

    def _idle_phase(self, label: str, duration_seconds: float) -> None:
        """Leave the app idle for one explicit dwell period."""

        if duration_seconds <= 0:
            return

        logger.info(
            "Navigation soak idle: {} for {:.1f}s on {}",
            label,
            duration_seconds,
            self._current_screen_name(),
        )
        self.stats.explicit_idle_seconds += duration_seconds
        self.pump.run_for(duration_seconds)

    def _advance_until(
        self,
        *,
        expected_screen: str,
        target_value: str,
        current_value: Callable[[], str],
        label: str,
        max_steps: int,
    ) -> None:
        """Advance through one carousel or list until the requested item is selected."""

        for _ in range(max_steps):
            if current_value() == target_value:
                return
            self._simulate_action(
                InputAction.ADVANCE,
                expected_screen=expected_screen,
                label=label,
            )

        raise NavigationSoakFailure(f"could not reach {target_value} on {expected_screen}")

    def _hub_mode(self) -> str:
        """Return the selected hub card mode."""

        self._require_screen("hub")
        hub_screen = cast(Any, self.app.screen_manager.get_current_screen())  # type: ignore[union-attr]
        cards_getter = None if hub_screen is None else getattr(hub_screen, "cards", None)
        if callable(cards_getter):
            cards = list(cards_getter())
        else:
            legacy_cards_getter = (
                None if hub_screen is None else getattr(hub_screen, "_cards", None)
            )
            cards = [] if legacy_cards_getter is None else list(legacy_cards_getter())
        if not cards:
            raise NavigationSoakFailure("hub has no cards to navigate")
        selected_index = int(getattr(hub_screen, "selected_index", 0))
        return str(cards[selected_index % len(cards)].mode)

    def _listen_item_key(self) -> str:
        """Return the selected Listen landing item key."""

        self._require_screen("listen")
        listen_screen = cast(Any, self.app.screen_manager.get_current_screen())  # type: ignore[union-attr]
        items = [] if listen_screen is None else getattr(listen_screen, "items", [])
        if not items:
            raise NavigationSoakFailure("listen screen has no items to navigate")
        return str(items[listen_screen.selected_index % len(items)].key)

    def _move_hub_to(self, mode: str) -> None:
        """Advance the hub carousel until one mode is selected."""

        self._advance_until(
            expected_screen="hub",
            target_value=mode,
            current_value=self._hub_mode,
            label=f"hub advance to {mode}",
            max_steps=8,
        )

    def _move_listen_to(self, key: str) -> None:
        """Advance the Listen landing screen until one item is selected."""

        self._advance_until(
            expected_screen="listen",
            target_value=key,
            current_value=self._listen_item_key,
            label=f"listen advance to {key}",
            max_steps=8,
        )

    def _current_track_name(self) -> str | None:
        """Return the current track name when playback is active."""

        music_backend = self.app.music_backend
        if music_backend is None or not music_backend.is_connected:
            return None
        current_track = music_backend.get_current_track()
        if current_track is None:
            return None
        name = current_track.name
        return str(name) if name is not None else None

    def _wait_for_playback_started(self, context_label: str) -> None:
        """Wait until playback produces one current track snapshot."""

        if not self.with_playback:
            return

        deadline = time.monotonic() + self._PLAYBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current_track_name = self._current_track_name()
            if current_track_name is not None:
                self.stats.playback_verified = True
                self.stats.last_track_name = current_track_name
                return
            self.pump.run_for(0.2)

        raise NavigationSoakFailure(
            f"{context_label} did not produce a playable track within "
            f"{self._PLAYBACK_TIMEOUT_SECONDS:.1f}s"
        )

    def _wait_for_track_change(
        self,
        *,
        previous_track_name: str | None,
        context_label: str,
    ) -> None:
        """Wait until the current track changes after a skip action."""

        deadline = time.monotonic() + self._PLAYBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current_track_name = self._current_track_name()
            if current_track_name is not None and current_track_name != previous_track_name:
                self.stats.last_track_name = current_track_name
                self.stats.playback_verified = True
                return
            self.pump.run_for(0.2)

        raise NavigationSoakFailure(
            f"{context_label} did not change the current track within "
            f"{self._PLAYBACK_TIMEOUT_SECONDS:.1f}s"
        )

    def _exercise_now_playing(self, *, phase_label: str, back_target: str) -> None:
        """Exercise idle, play/pause, and next-track on Now Playing."""

        self._require_screen("now_playing")
        self._wait_for_playback_started(phase_label)
        playback_idle_seconds = min(self.idle_seconds, 1.0)
        self._idle_phase(f"{phase_label}_idle", playback_idle_seconds)

        self._simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} pause",
        )
        self.pump.run_for(self.hold_seconds)
        self._simulate_action(
            InputAction.PLAY_PAUSE,
            expected_screen="now_playing",
            label=f"{phase_label} resume",
        )

        previous_track_name = self._current_track_name()
        self._simulate_action(
            InputAction.NEXT_TRACK,
            expected_screen="now_playing",
            label=f"{phase_label} next track",
        )
        self._wait_for_track_change(
            previous_track_name=previous_track_name,
            context_label=phase_label,
        )
        self._idle_phase(f"{phase_label}_post_next_idle", playback_idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen=back_target,
            label=f"{phase_label} back",
        )

    def _exercise_listen_branch(self) -> None:
        """Exercise Listen, playlists, recent, and playback-related navigation."""

        self._move_hub_to("listen")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="listen",
            label="open Listen",
        )
        self._idle_phase("listen_landing", self.idle_seconds)

        self._move_listen_to("playlists")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="playlists",
            label="open Playlists",
        )
        self._idle_phase("playlists_idle", self.idle_seconds)

        if self.with_playback:
            playlist_screen = self.app.screen_manager.get_current_screen()  # type: ignore[union-attr]
            playlists = [] if playlist_screen is None else getattr(playlist_screen, "playlists", [])
            if not playlists:
                raise NavigationSoakFailure(
                    "playlists screen is empty; disable playback or provision test music"
                )
            self._simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="load validation playlist",
            )
            self._exercise_now_playing(
                phase_label="playlist_playback",
                back_target="playlists",
            )

        self._simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Playlists",
        )

        self._move_listen_to("recent")
        self._simulate_action(
            InputAction.SELECT,
            expected_screen="recent_tracks",
            label="open Recent",
        )
        self._idle_phase("recent_tracks_idle", self.idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen="listen",
            label="back to Listen from Recent",
        )

        if self.with_playback:
            self._move_listen_to("shuffle")
            self._simulate_action(
                InputAction.SELECT,
                expected_screen="now_playing",
                label="shuffle local music",
            )
            self._exercise_now_playing(
                phase_label="shuffle_playback",
                back_target="listen",
            )

        self._simulate_action(
            InputAction.BACK,
            expected_screen="hub",
            label="back to Hub from Listen",
        )

    def _exercise_simple_hub_branch(
        self,
        *,
        mode: str,
        target_screen: str,
        idle_label: str,
    ) -> None:
        """Open one hub card, idle briefly, and return."""

        self._move_hub_to(mode)
        self._simulate_action(
            InputAction.SELECT,
            expected_screen=target_screen,
            label=f"open {mode}",
        )
        self._idle_phase(idle_label, self.idle_seconds)
        self._simulate_action(
            InputAction.BACK,
            expected_screen="hub",
            label=f"back from {target_screen}",
        )

    def _exercise_cycle(self) -> None:
        """Run one full navigation cycle."""

        self._exercise_listen_branch()
        self._exercise_simple_hub_branch(
            mode="talk",
            target_screen="call",
            idle_label="talk_idle",
        )
        self._exercise_simple_hub_branch(
            mode="ask",
            target_screen="ask",
            idle_label="ask_idle",
        )
        self._exercise_simple_hub_branch(
            mode="setup",
            target_screen="power",
            idle_label="power_idle",
        )
        self._move_hub_to("listen")

    def _exercise_sleep_wake(self) -> None:
        """Force one sleep/wake cycle when screen timeout is enabled."""

        if self.skip_sleep:
            self.stats.sleep_wake_status = "skipped"
            return

        timeout_seconds = self.app.screen_timeout_seconds
        if timeout_seconds <= 0.0:
            self.stats.sleep_wake_status = "timeout_disabled"
            return

        self.app.simulate_inactivity(idle_for_seconds=timeout_seconds + 1.0)
        self.pump.run_for(max(0.35, self.hold_seconds))
        if self.app.context is None or self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not enter sleep during navigation soak")

        self.app.scheduler.run_on_main(
            lambda: self.app.bus.publish(UserActivityEvent(action_name="navigation_soak"))
        )
        self.pump.run_for(max(0.35, self.hold_seconds))
        if self.app.context is None or not self.app.context.screen.awake:
            raise NavigationSoakFailure("screen did not wake after simulated navigation activity")

        self.stats.sleep_wake_status = "ok"


def run_navigation_soak(
    *,
    config_dir: str = "config",
    cycles: int = 2,
    hold_seconds: float = 0.35,
    idle_seconds: float = 3.0,
    tail_idle_seconds: float = 10.0,
    with_playback: bool = True,
    provision_test_music: bool = True,
    test_music_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR,
    skip_sleep: bool = False,
    app_factory: _NavigationSoakAppFactory | None = None,
) -> tuple[bool, str]:
    """Run the target-hardware navigation and idle stability soak."""

    runner = NavigationSoakRunner(
        config_dir=config_dir,
        cycles=cycles,
        hold_seconds=hold_seconds,
        idle_seconds=idle_seconds,
        tail_idle_seconds=tail_idle_seconds,
        with_playback=with_playback,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
        skip_sleep=skip_sleep,
        app_factory=app_factory,
    )
    return runner.run()
