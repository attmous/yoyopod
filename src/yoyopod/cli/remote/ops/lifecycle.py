"""Runtime lifecycle-style remote operations."""

from __future__ import annotations

import argparse
from typing import Annotated, Optional

import typer

from yoyopod.cli.remote.config import load_pi_deploy_config
from yoyopod.cli.remote.transport import run_remote, validate_config

from .commands import (
    build_logs_command,
    build_restart_command,
    build_rtc_command,
    build_status_command,
    build_whisplay_command,
)
from .validation import _resolve_remote_config


def status(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
) -> None:
    """Show remote repo, music backend, and process status."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    rc = run_remote(config, build_status_command(deploy_config))
    if rc != 0:
        raise typer.Exit(code=rc)


def logs(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    lines: Annotated[int, typer.Option("--lines", help="Number of log lines to tail.")] = 50,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output.")] = False,
    errors: Annotated[
        bool, typer.Option("--errors", help="Tail the error log instead of the main log.")
    ] = False,
    filter: Annotated[
        Optional[str], typer.Option("--filter", help="Grep filter to apply to log output.")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Tail yoyopod logs on the Pi."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    args = argparse.Namespace(
        errors=errors,
        follow=follow,
        filter=filter,
        lines=lines,
    )
    rc = run_remote(config, build_logs_command(args, deploy_config), tty=follow)
    if rc != 0:
        raise typer.Exit(code=rc)


def restart(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Restart the yoyopod app on the Pi."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    rc = run_remote(config, build_restart_command(deploy_config))
    if rc != 0:
        raise typer.Exit(code=rc)


def whisplay(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    duration_seconds: Annotated[
        float, typer.Option("--duration-seconds", help="Session duration in seconds.")
    ] = 30.0,
    debounce_ms: Annotated[
        Optional[int], typer.Option("--debounce-ms", help="Debounce threshold in ms.")
    ] = None,
    double_tap_ms: Annotated[
        Optional[int], typer.Option("--double-tap-ms", help="Double-tap window in ms.")
    ] = None,
    long_hold_ms: Annotated[
        Optional[int], typer.Option("--long-hold-ms", help="Long-hold threshold in ms.")
    ] = None,
    no_display: Annotated[
        bool, typer.Option("--no-display", help="Disable display rendering.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Run the Whisplay gesture-tuning helper remotely."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    args = argparse.Namespace(
        verbose=verbose,
        no_display=no_display,
        duration_seconds=duration_seconds,
        debounce_ms=debounce_ms,
        double_tap_ms=double_tap_ms,
        long_hold_ms=long_hold_ms,
    )
    rc = run_remote(config, build_whisplay_command(args), tty=True)
    if rc != 0:
        raise typer.Exit(code=rc)


def rtc(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    action: Annotated[
        str,
        typer.Argument(help="RTC action: status, sync-to, sync-from, set-alarm, disable-alarm."),
    ] = "status",
    time: Annotated[
        Optional[str], typer.Option("--time", help="Alarm time in ISO 8601 format (for set-alarm).")
    ] = None,
    repeat_mask: Annotated[
        int, typer.Option("--repeat-mask", help="Repeat bitmask (default: every day).")
    ] = 127,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Inspect or control PiSugar RTC state remotely."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    args = argparse.Namespace(
        verbose=verbose,
        rtc_action=action,
        time=time,
        repeat_mask=repeat_mask,
    )
    rc = run_remote(config, build_rtc_command(args))
    if rc != 0:
        raise typer.Exit(code=rc)


__all__ = [
    "logs",
    "restart",
    "rtc",
    "status",
    "whisplay",
]
