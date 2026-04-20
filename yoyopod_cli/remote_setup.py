"""Run Pi setup + verification remotely via SSH."""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote, validate_config, venv_activate_prefix

app = build_remote_app("setup_remote", "Run setup on the Pi via SSH.")


def _build_setup() -> str:
    pi = load_pi_paths()
    return f"{venv_activate_prefix(pi.venv)} && yoyopod setup pi"


def _build_verify_setup() -> str:
    pi = load_pi_paths()
    return f"{venv_activate_prefix(pi.venv)} && yoyopod setup verify-pi"


@app.command()
def setup(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Run full Pi setup remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_setup(), tty=True))


@app.command(name="verify-setup")
def verify_setup(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Verify Pi setup remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_verify_setup()))
