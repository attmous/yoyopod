"""Navigation soak pump helpers: environment management, app driving, route/track waiting."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from yoyopod_cli.music_fixtures import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    ProvisionedTestMusicLibrary,
    provision_test_music_library,
)
from yoyopod_cli.pi.support.events import UserActivityEvent
from yoyopod_cli.pi.support.input import InputAction

from .handle import _NavigationSoakAppHandle
from .guard import _reject_real_python_runtime_object
from .plan import NavigationSoakError


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
        _reject_real_python_runtime_object(app.input_manager, "runtime input manager")
        app.input_manager.simulate_action(action)
        return

    previous_screen = app.screen_manager.current_screen
    _reject_real_python_runtime_object(previous_screen, "runtime screen")
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

    _reject_real_python_runtime_object(app.bus, "runtime bus")
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
