"""System validation subcommand."""

from __future__ import annotations

import platform
from typing import Annotated

import typer

from yoyopod_cli.pi.validate._common import (
    _CheckResult,
    _load_app_config,
    _print_summary,
)
from yoyopod_cli.common import configure_logging, resolve_config_dir
from yoyopod_cli.pi.validate.rust_runtime import (
    rust_runtime_dry_run_check as _rust_runtime_dry_run_check,
    rust_ui_smoke_check as _rust_ui_smoke_check,
)


def _environment_check() -> _CheckResult:
    """Capture the current execution environment."""
    system = platform.system()
    machine = platform.machine()
    python_version = platform.python_version()

    if system == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower()):
        status = "pass"
    else:
        status = "warn"

    return _CheckResult(
        name="environment",
        status=status,
        details=f"system={system}, machine={machine}, python={python_version}",
    )


def smoke(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    display_hold_seconds: Annotated[
        float,
        typer.Option(
            "--display-hold-seconds",
            help="How long to keep the display confirmation text visible.",
        ),
    ] = 0.5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate the Rust runtime stack on target hardware."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running Rust runtime smoke validation")

    app_config = _load_app_config(config_path)
    results: list[_CheckResult] = [
        _environment_check(),
        _rust_runtime_dry_run_check(config_path),
        _rust_ui_smoke_check(config_path, app_config, display_hold_seconds),
    ]

    _print_summary("smoke", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
