"""Target-side navigation and idle stability soak helpers."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from loguru import logger

from yoyopod.app import YoyoPodApp
from yoyopod.audio.test_music import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    ProvisionedTestMusicLibrary,
    provision_test_music_library,
)
from yoyopod.events import UserActivityEvent
from yoyopod.ui.input import InputAction


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
        ),
        NavigationSoakStep(
            "action",
            "Open Playlists from Listen",
            action=InputAction.SELECT,
            wait_for_route="playlists",
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


def _pump_app(app: YoyoPodApp, duration_seconds: float) -> None:
    """Pump the coordinator-thread services without entering the full app loop."""

    deadline = time.monotonic() + max(0.0, duration_seconds)
    while time.monotonic() < deadline:
        app.runtime_loop.process_pending_main_thread_actions()
        now = time.monotonic()
        app._attempt_manager_recovery()
        app._poll_power_status(now=now)
        app._pump_lvgl_backend(now)
        app._feed_watchdog_if_due(now)
        app._update_screen_power(now)
        time.sleep(0.05)


def _current_route(app: YoyoPodApp) -> str:
    """Return the current route name or a stable placeholder."""

    if app.screen_manager is None or app.screen_manager.current_screen is None:
        return "none"
    route_name = app.screen_manager.current_screen.route_name
    if route_name:
        return route_name
    return app.screen_manager.current_screen.name


def _dispatch_action(app: YoyoPodApp, action: InputAction) -> None:
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


def _wait_for_route(
    app: YoyoPodApp,
    route_name: str,
    *,
    timeout_seconds: float,
) -> None:
    """Pump the app until the requested route becomes active."""

    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while time.monotonic() < deadline:
        if _current_route(app) == route_name:
            return
        _pump_app(app, 0.05)
    raise NavigationSoakError(
        f"navigation soak expected route '{route_name}', got '{_current_route(app)}'"
    )


def _wait_for_track(
    app: YoyoPodApp,
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
                return current_track.name
        _pump_app(app, 0.05)

    current_track = app.music_backend.get_current_track() if app.music_backend is not None else None
    current_uri = current_track.uri if current_track is not None else "none"
    raise NavigationSoakError(
        "navigation soak did not load a validation track; " f"current_track={current_uri}"
    )


def _exercise_sleep_wake(app: YoyoPodApp) -> str:
    """Force one idle sleep/wake cycle against the current app instance."""

    timeout_seconds = max(1.0, float(app._screen_timeout_seconds or 0.0))
    app._last_user_activity_at = time.monotonic() - timeout_seconds - 1.0
    _pump_app(app, 0.35)
    if app.context is None or app.context.screen.awake:
        raise NavigationSoakError("screen did not enter sleep during soak")

    app.event_bus.publish(UserActivityEvent(action_name="navigation_soak"))
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
) -> NavigationSoakReport:
    """Run the deterministic target-side navigation and idle stability soak."""

    music_dir, expected_library = _prepare_validation_music_dir(
        with_music=with_music,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
    )
    env_updates = {}
    if music_dir is not None:
        env_updates["YOYOPOD_MUSIC_DIR"] = str(music_dir)

    with _temporary_env(env_updates):
        app = YoyoPodApp(config_dir=config_dir, simulate=simulate)
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
