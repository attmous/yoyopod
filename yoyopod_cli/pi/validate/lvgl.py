"""Lvgl validation subcommand."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir
from yoyopod_cli.pi.validate._common import _print_summary
from yoyopod_cli.pi.validate.rust_runtime import (
    rust_runtime_dry_run_check as _rust_runtime_dry_run_check,
    rust_ui_navigation_check as _rust_ui_navigation_check,
)


def lvgl(
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
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run Rust UI/LVGL navigation through the runtime worker protocol."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    results = [
        _rust_runtime_dry_run_check(config_path),
        _rust_ui_navigation_check(
            config_path,
            cycles=cycles,
            hold_seconds=hold_seconds,
            idle_seconds=idle_seconds,
            tail_idle_seconds=hold_seconds,
        ),
    ]
    _print_summary("lvgl", results)
    if not any(result.status == "fail" for result in results):
        logger.info("Rust UI/LVGL validation passed")
        return

    logger.error(
        "Rust UI/LVGL validation failed: {}",
        "; ".join(result.details for result in results if result.status == "fail"),
    )
    raise typer.Exit(code=1)
