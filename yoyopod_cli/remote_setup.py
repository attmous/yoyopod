"""Run Pi setup + verification remotely via SSH."""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote, validate_config

app = build_remote_app("setup_remote", "Run setup on the Pi via SSH.")


def _build_setup(
    *,
    venv_relpath: str,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
    skip_uv_sync: bool,
    skip_builds: bool,
    dry_run: bool,
) -> str:
    cmd = "uv run yoyopod setup pi"
    if with_voice:
        cmd += " --with-voice"
    if with_network:
        cmd += " --with-network"
    if with_pisugar:
        cmd += " --with-pisugar"
    if skip_uv_sync:
        cmd += " --skip-uv-sync"
    if skip_builds:
        cmd += " --skip-builds"
    if dry_run:
        cmd += " --dry-run"
    return cmd


def _build_verify_setup(
    *,
    venv_relpath: str,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
) -> str:
    cmd = "uv run yoyopod setup verify-pi"
    if with_voice:
        cmd += " --with-voice"
    if with_network:
        cmd += " --with-network"
    if with_pisugar:
        cmd += " --with-pisugar"
    return cmd


@app.command()
def setup(
    ctx: typer.Context,
    with_voice: bool = typer.Option(False, "--with-voice"),
    with_network: bool = typer.Option(False, "--with-network"),
    with_pisugar: bool = typer.Option(False, "--with-pisugar"),
    skip_uv_sync: bool = typer.Option(False, "--skip-uv-sync"),
    skip_builds: bool = typer.Option(False, "--skip-builds"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run full Pi setup remotely. Flags forward to `yoyopod setup pi` on the target."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    cmd = _build_setup(
        venv_relpath=pi.venv,
        with_voice=with_voice,
        with_network=with_network,
        with_pisugar=with_pisugar,
        skip_uv_sync=skip_uv_sync,
        skip_builds=skip_builds,
        dry_run=dry_run,
    )
    raise typer.Exit(run_remote(conn, cmd, tty=True))


@app.command(name="verify-setup")
def verify_setup(
    ctx: typer.Context,
    with_voice: bool = typer.Option(False, "--with-voice"),
    with_network: bool = typer.Option(False, "--with-network"),
    with_pisugar: bool = typer.Option(False, "--with-pisugar"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Verify Pi setup remotely. Flags forward to `yoyopod setup verify-pi` on the target."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    cmd = _build_verify_setup(
        venv_relpath=pi.venv,
        with_voice=with_voice,
        with_network=with_network,
        with_pisugar=with_pisugar,
    )
    raise typer.Exit(run_remote(conn, cmd))
