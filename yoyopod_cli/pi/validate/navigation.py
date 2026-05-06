"""Navigation validation subcommand."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir
from yoyopod_cli.pi.validate._common import _print_summary
from yoyopod_cli.pi.validate.rust_runtime import (
    rust_runtime_dry_run_check as _rust_runtime_dry_run_check,
    rust_ui_navigation_check as _rust_ui_navigation_check,
)


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
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run Rust UI one-button navigation through the runtime worker protocol."""
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
            tail_idle_seconds=tail_idle_seconds,
        ),
    ]
    _print_summary("navigation", results)
    if not any(result.status == "fail" for result in results):
        logger.info("Rust navigation validation passed")
        return

    logger.error(
        "Rust navigation validation failed: {}",
        "; ".join(result.details for result in results if result.status == "fail"),
    )
    raise typer.Exit(code=1)
