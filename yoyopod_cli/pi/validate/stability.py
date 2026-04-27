"""Stability validation subcommand."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.defaults import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod_cli.pi.validate._navigation_soak import (
    NavigationSoakError,
    run_navigation_idle_soak,
)


def stability(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full transition cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option("--hold-seconds", help="How long to keep each screen active during the soak."),
    ] = 0.2,
    idle_seconds: Annotated[
        float,
        typer.Option("--idle-seconds", help="How long to idle after each full navigation cycle."),
    ] = 1.0,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music",
            help="Also exercise playlist loading and now-playing actions during the soak.",
        ),
    ] = False,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed deterministic validation music before playback soak steps.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = "",
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the sleep and wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a repeated navigation and idle stability pass on the target checkout."""
    configure_logging(verbose)
    resolved_music_dir = test_music_dir or DEFAULT_TEST_MUSIC_TARGET_DIR
    try:
        report = run_navigation_idle_soak(
            config_dir=config_dir,
            simulate=False,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            skip_sleep=skip_sleep,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=resolved_music_dir,
        )
    except NavigationSoakError as exc:
        from loguru import logger

        logger.error(f"Stability soak failed: {exc}")
        raise typer.Exit(code=1)

    from loguru import logger

    logger.info(f"Stability soak passed: {report.summary()}")
