"""src/yoyopod/cli/pi/lvgl.py — LVGL soak and probe commands."""

from __future__ import annotations

import time
from typing import Annotated, Optional

import typer

from yoyopod.audio.test_music import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.common import configure_logging
from yoyopod.cli.pi.stability import NavigationSoakError, run_navigation_idle_soak

lvgl_app = typer.Typer(name="lvgl", help="LVGL display stress-test and probe commands.", no_args_is_help=True)


@lvgl_app.command()
def soak(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory to use.")] = "config",
    simulate: Annotated[bool, typer.Option("--simulate", help="Run against simulation instead of hardware.")] = False,
    cycles: Annotated[int, typer.Option("--cycles", help="How many full transition cycles to run.")] = 2,
    hold_seconds: Annotated[float, typer.Option("--hold-seconds", help="How long to keep each screen active during the soak.")] = 0.2,
    idle_seconds: Annotated[
        float,
        typer.Option(
            "--idle-seconds",
            help="How long to idle after each full navigation cycle.",
        ),
    ] = 1.0,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music",
            help="Exercise playlist loading and now-playing actions during the soak.",
        ),
    ] = False,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed the deterministic validation music library before playback soak steps.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
    skip_sleep: Annotated[bool, typer.Option("--skip-sleep", help="Skip the sleep/wake exercise.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a deterministic LVGL navigation and idle soak pass against YoyoPod."""
    from loguru import logger

    configure_logging(verbose)
    try:
        report = run_navigation_idle_soak(
            config_dir=config_dir,
            simulate=simulate,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            skip_sleep=skip_sleep,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=test_music_dir,
        )
    except NavigationSoakError as exc:
        logger.error(f"LVGL soak failed: {exc}")
        raise typer.Exit(code=1)
    logger.info(f"LVGL soak passed: {report.summary()}")


@lvgl_app.command()
def probe(
    scene: Annotated[str, typer.Option("--scene", help="Probe scene to render (card, list, footer, carousel).")] = "carousel",
    duration_seconds: Annotated[float, typer.Option("--duration-seconds", help="How long to keep pumping the scene.")] = 10.0,
    simulate: Annotated[bool, typer.Option("--simulate", help="Use the Whisplay adapter in simulation mode.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a standalone LVGL proof scene against the Whisplay display adapter."""
    from loguru import logger

    from yoyopod.ui.display.adapters.whisplay import WhisplayDisplayAdapter
    from yoyopod.ui.lvgl_binding import LvglBinding, LvglBindingError, LvglDisplayBackend

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

    adapter = WhisplayDisplayAdapter(
        simulate=simulate,
        renderer="pil",
        # The probe command owns its own throwaway LVGL backend below, so keep the
        # adapter on the lightweight PIL shadow-buffer path instead of the app's
        # production contract enforcement.
        enforce_production_contract=False,
    )
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
