"""Navigation idle soak: run_navigation_idle_soak."""

from __future__ import annotations

from loguru import logger

from yoyopod_cli.music_fixtures import DEFAULT_TEST_MUSIC_TARGET_DIR

from .handle import _NavigationSoakAppFactory, _default_app_factory
from .plan import NavigationSoakError, NavigationSoakReport, build_navigation_soak_plan
from .pump import (
    _current_route,
    _dispatch_action,
    _exercise_sleep_wake,
    _prepare_validation_music_dir,
    _pump_app,
    _reset_selection,
    _temporary_env,
    _wait_for_route,
    _wait_for_track,
)


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
