"""yoyopy/cli/pi/lvgl.py — LVGL soak and probe commands."""

from __future__ import annotations

import time
from typing import Annotated, Optional

import typer

from yoyopy.cli.common import configure_logging

lvgl_app = typer.Typer(name="lvgl", help="LVGL display stress-test and probe commands.", no_args_is_help=True)


@lvgl_app.command()
def soak(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory to use.")] = "config",
    simulate: Annotated[bool, typer.Option("--simulate", help="Run against simulation instead of hardware.")] = False,
    cycles: Annotated[int, typer.Option("--cycles", help="How many full transition cycles to run.")] = 2,
    hold_seconds: Annotated[float, typer.Option("--hold-seconds", help="How long to keep each screen active during the soak.")] = 0.2,
    skip_sleep: Annotated[bool, typer.Option("--skip-sleep", help="Skip the sleep/wake exercise.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a deterministic LVGL screen-transition soak pass against YoyoPod."""
    from loguru import logger

    from yoyopy.app import YoyoPodApp
    from yoyopy.events import UserActivityEvent

    configure_logging(verbose)

    def _pump_app(app: YoyoPodApp, duration_seconds: float) -> None:
        """Pump the coordinator-thread services without entering the full app run loop."""
        deadline = time.monotonic() + max(0.0, duration_seconds)
        while time.monotonic() < deadline:
            app._process_pending_main_thread_actions()
            now = time.monotonic()
            app._attempt_manager_recovery()
            app._poll_power_status(now=now)
            app._pump_lvgl_backend(now)
            app._feed_watchdog_if_due(now)
            app._update_screen_power(now)
            time.sleep(0.05)

    def _exercise_sleep_wake(app: YoyoPodApp) -> tuple[bool, str]:
        """Force one sleep/wake cycle against the current app."""
        timeout_seconds = max(1.0, float(app._screen_timeout_seconds or 0.0))
        app._last_user_activity_at = time.monotonic() - timeout_seconds - 1.0
        _pump_app(app, 0.35)
        if app.context is None or app.context.screen_awake:
            return False, "screen did not enter sleep during soak"

        app.event_bus.publish(UserActivityEvent(action_name="lvgl_soak"))
        _pump_app(app, 0.35)
        if app.context is None or not app.context.screen_awake:
            return False, "screen did not wake after simulated activity"

        return True, "sleep/wake ok"

    def run_lvgl_soak(
        *,
        config_dir: str = "config",
        simulate: bool = False,
        cycles: int = 2,
        hold_seconds: float = 0.2,
        exercise_sleep: bool = True,
    ) -> tuple[bool, str]:
        """Run a deterministic screen-transition soak and return success/details."""
        app = YoyoPodApp(config_dir=config_dir, simulate=simulate)
        if not app.setup():
            return False, "app setup failed"

        try:
            if app.display is None or app.screen_manager is None:
                return False, "display or screen manager not initialized"

            if app.display.backend_kind != "lvgl":
                return False, f"backend is {app.display.backend_kind}, expected lvgl"

            screens = [
                "hub",
                "listen",
                "playlists",
                "now_playing",
                "call",
                "talk_contact",
                "call_history",
                "contacts",
                "voice_note",
                "ask",
                "power",
            ]

            transitions = 0
            for _cycle in range(max(1, cycles)):
                for screen_name in screens:
                    if screen_name not in app.screen_manager.screens:
                        continue
                    app.screen_manager.replace_screen(screen_name)
                    _pump_app(app, hold_seconds)
                    transitions += 1

            sleep_details = "sleep/wake skipped"
            if exercise_sleep:
                sleep_ok, sleep_details = _exercise_sleep_wake(app)
                if not sleep_ok:
                    return False, sleep_details

            return True, f"backend=lvgl, transitions={transitions}, {sleep_details}"
        finally:
            app.stop()

    ok, details = run_lvgl_soak(
        config_dir=config_dir,
        simulate=simulate,
        cycles=cycles,
        hold_seconds=hold_seconds,
        exercise_sleep=not skip_sleep,
    )
    if ok:
        logger.info(f"LVGL soak passed: {details}")
    else:
        logger.error(f"LVGL soak failed: {details}")
        raise typer.Exit(code=1)


@lvgl_app.command()
def probe(
    scene: Annotated[str, typer.Option("--scene", help="Probe scene to render (card, list, footer, carousel).")] = "carousel",
    duration_seconds: Annotated[float, typer.Option("--duration-seconds", help="How long to keep pumping the scene.")] = 10.0,
    simulate: Annotated[bool, typer.Option("--simulate", help="Use the Whisplay adapter in simulation mode.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a standalone LVGL proof scene against the Whisplay display adapter."""
    from loguru import logger

    from yoyopy.ui.display.adapters.whisplay import WhisplayDisplayAdapter
    from yoyopy.ui.lvgl_binding import LvglBinding, LvglBindingError, LvglDisplayBackend

    configure_logging(verbose)

    scene_map = {
        "card": LvglBinding.SCENE_CARD,
        "list": LvglBinding.SCENE_LIST,
        "footer": LvglBinding.SCENE_FOOTER,
        "carousel": LvglBinding.SCENE_CAROUSEL,
    }

    if scene not in scene_map:
        logger.error(f"Unknown scene '{scene}'. Valid choices: {sorted(scene_map)}")
        raise typer.Exit(code=1)

    adapter = WhisplayDisplayAdapter(simulate=simulate, renderer="pil")
    backend = LvglDisplayBackend(adapter)

    if not backend.available:
        logger.error(
            "LVGL shim unavailable. Build it first with `uv run yoyoctl build lvgl`."
        )
        raise typer.Exit(code=1)

    if not backend.initialize():
        logger.error("Failed to initialize the LVGL backend.")
        raise typer.Exit(code=1)

    try:
        backend.show_probe_scene(scene_map[scene])
        logger.info("Running LVGL probe scene '{}' for {:.1f}s", scene, duration_seconds)
        started_at = time.monotonic()
        last_tick = started_at
        while time.monotonic() - started_at < duration_seconds:
            now = time.monotonic()
            delta_ms = int(max(0.0, now - last_tick) * 1000.0)
            last_tick = now
            backend.pump(delta_ms)
            time.sleep(0.016)
    except LvglBindingError as exc:
        logger.error(f"LVGL probe failed: {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        backend.cleanup()
        adapter.cleanup()
