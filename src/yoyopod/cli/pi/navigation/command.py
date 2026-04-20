"""Navigation soak command wiring."""

from __future__ import annotations

from typing import Annotated

import typer
from loguru import logger

from yoyopod.audio.test_music import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.common import configure_logging
from yoyopod.cli.pi.navigation.runner import NavigationSoakRunner


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
    )
    return runner.run()


def register_navigation_command(validate_app: typer.Typer) -> None:
    """Attach the navigation command to the validate app."""

    @validate_app.command()
    def navigation(
        config_dir: Annotated[
            str, typer.Option("--config-dir", help="Configuration directory to use.")
        ] = "config",
        cycles: Annotated[
            int, typer.Option("--cycles", help="How many full navigation cycles to run.")
        ] = 2,
        hold_seconds: Annotated[
            float,
            typer.Option(
                "--hold-seconds",
                help="How long to pump after each simulated click or route change.",
            ),
        ] = 0.35,
        idle_seconds: Annotated[
            float,
            typer.Option(
                "--idle-seconds",
                help="How long to leave each exercised screen idle before the next action.",
            ),
        ] = 3.0,
        tail_idle_seconds: Annotated[
            float,
            typer.Option(
                "--tail-idle-seconds",
                help="Final idle dwell on the hub after all navigation cycles complete.",
            ),
        ] = 10.0,
        with_playback: Annotated[
            bool,
            typer.Option(
                "--with-playback/--no-with-playback",
                help="Drive playlist and shuffle playback paths during the soak.",
            ),
        ] = True,
        provision_test_music: Annotated[
            bool,
            typer.Option(
                "--provision-test-music/--no-provision-test-music",
                help="Seed deterministic validation music before playback-driven navigation.",
            ),
        ] = True,
        test_music_dir: Annotated[
            str,
            typer.Option(
                "--test-music-dir",
                help="Dedicated target directory for validation-only test music assets.",
            ),
        ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
        skip_sleep: Annotated[
            bool, typer.Option("--skip-sleep", help="Skip the final sleep/wake exercise.")
        ] = False,
        verbose: Annotated[
            bool, typer.Option("--verbose", help="Enable DEBUG logging.")
        ] = False,
    ) -> None:
        """Run the one-button target navigation and idle stability soak on LVGL hardware."""

        configure_logging(verbose)

        ok, details = run_navigation_soak(
            config_dir=config_dir,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            tail_idle_seconds=tail_idle_seconds,
            with_playback=with_playback,
            provision_test_music=provision_test_music,
            test_music_dir=test_music_dir,
            skip_sleep=skip_sleep,
        )
        if ok:
            logger.info("Navigation soak passed: {}", details)
            return

        logger.error("Navigation soak failed: {}", details)
        raise typer.Exit(code=1)
