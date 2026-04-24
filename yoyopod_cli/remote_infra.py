"""Remote infra commands: power snapshot, rtc, systemd service management."""

from __future__ import annotations

import typer

from yoyopod_cli.common import checkout_module_command, configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_remote,
    shell_quote,
    validate_config,
)

app = build_remote_app("infra", "Remote power, rtc, and service commands.")

LEGACY_SERVICE_UNSUPPORTED = (
    "Legacy yoyopod@ service management is no longer supported. "
    "Bootstrap dev/prod lanes and use `yoyopod remote mode activate dev|prod`."
)


def _build_power(*, venv_relpath: str) -> str:
    """Invoke ``yoyopod pi power battery`` on the Pi."""
    return checkout_module_command(venv_relpath, "pi", "power", "battery")


def _build_rtc(action: str, *, venv_relpath: str, time_iso: str, repeat_mask: int) -> str:
    """Build ``yoyopod pi power rtc <action>`` remote shell."""
    cmd = f"{checkout_module_command(venv_relpath, 'pi', 'power', 'rtc', action)}"
    if action == "set-alarm":
        if not time_iso:
            raise typer.BadParameter("set-alarm requires --time")
        cmd += f" --time {shell_quote(time_iso)} --repeat-mask {repeat_mask}"
    return cmd


@app.command()
def power(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Query PiSugar state remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_power(venv_relpath=pi.venv)))


@app.command()
def rtc(
    ctx: typer.Context,
    action: str = typer.Argument(
        "status", help="status | sync-to | sync-from | set-alarm | disable-alarm"
    ),
    time: str = typer.Option("", "--time", help="ISO 8601 timestamp for set-alarm."),
    repeat_mask: int = typer.Option(
        127, "--repeat-mask", help="Repeat-bitmask (default every day)."
    ),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Inspect or control PiSugar RTC remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(
        run_remote(
            conn, _build_rtc(action, venv_relpath=pi.venv, time_iso=time, repeat_mask=repeat_mask)
        )
    )


@app.command()
def service(
    action: str = typer.Argument(..., help="Legacy service action (unsupported)."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Unsupported legacy yoyopod@ service manager."""
    configure_logging(verbose)
    typer.echo(f"{LEGACY_SERVICE_UNSUPPORTED} Requested legacy action: {action}.", err=True)
    raise typer.Exit(2)
