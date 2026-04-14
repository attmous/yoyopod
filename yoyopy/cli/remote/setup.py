"""yoyopy/cli/remote/setup.py - remote wrappers for repo-owned setup commands."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopy.cli.remote.ops import _resolve_remote_config, run_remote, validate_config

REMOTE_UV_PREFIX = 'export PATH="$HOME/.local/bin:$PATH";'


def build_setup_command(
    *,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
    skip_uv_sync: bool,
    skip_builds: bool,
    dry_run: bool,
) -> str:
    """Build the remote Raspberry Pi setup command."""

    parts = [REMOTE_UV_PREFIX, "uv", "run", "yoyoctl", "setup", "pi"]
    if with_voice:
        parts.append("--with-voice")
    if with_network:
        parts.append("--with-network")
    if with_pisugar:
        parts.append("--with-pisugar")
    if skip_uv_sync:
        parts.append("--skip-uv-sync")
    if skip_builds:
        parts.append("--skip-builds")
    if dry_run:
        parts.append("--dry-run")
    return " ".join(parts)


def build_verify_setup_command(
    *,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
) -> str:
    """Build the remote Raspberry Pi dependency verification command."""

    parts = [REMOTE_UV_PREFIX, "uv", "run", "yoyoctl", "setup", "verify-pi"]
    if with_voice:
        parts.append("--with-voice")
    if with_network:
        parts.append("--with-network")
    if with_pisugar:
        parts.append("--with-pisugar")
    return " ".join(parts)


def setup(
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
    with_voice: Annotated[
        bool, typer.Option("--with-voice", help="Install voice-path extras such as espeak-ng.")
    ] = False,
    with_network: Annotated[
        bool, typer.Option("--with-network", help="Install cellular and PPP extras.")
    ] = False,
    with_pisugar: Annotated[
        bool, typer.Option("--with-pisugar", help="Install PiSugar-specific packages.")
    ] = False,
    skip_uv_sync: Annotated[
        bool, typer.Option("--skip-uv-sync", help="Skip `uv sync --extra dev` after apt install.")
    ] = False,
    skip_builds: Annotated[
        bool, typer.Option("--skip-builds", help="Skip the native shim build steps.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the planned commands without executing them.")
    ] = False,
) -> None:
    """Run the baseline repo-owned Pi setup contract remotely over SSH."""

    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    rc = run_remote(
        config,
        build_setup_command(
            with_voice=with_voice,
            with_network=with_network,
            with_pisugar=with_pisugar,
            skip_uv_sync=skip_uv_sync,
            skip_builds=skip_builds,
            dry_run=dry_run,
        ),
        tty=True,
    )
    if rc != 0:
        raise typer.Exit(code=rc)


def verify_setup(
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
    with_voice: Annotated[
        bool, typer.Option("--with-voice", help="Require voice-path extras such as espeak-ng.")
    ] = False,
    with_network: Annotated[
        bool, typer.Option("--with-network", help="Require cellular and PPP extras.")
    ] = False,
    with_pisugar: Annotated[
        bool, typer.Option("--with-pisugar", help="Require PiSugar-specific packages and service.")
    ] = False,
) -> None:
    """Run the baseline repo-owned Pi setup verifier remotely over SSH."""

    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    rc = run_remote(
        config,
        build_verify_setup_command(
            with_voice=with_voice,
            with_network=with_network,
            with_pisugar=with_pisugar,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)
