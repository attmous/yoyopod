"""Remote dev/prod lane switching commands."""

from __future__ import annotations

import shlex

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import LanePaths, load_lane_paths
from yoyopod_cli.remote_shared import pi_conn
from yoyopod_cli.remote_transport import run_remote, validate_config

app = typer.Typer(name="mode", help="Switch between dev checkout and prod OTA lanes.")


def _sudo_systemctl(action: str, unit: str, *, optional: bool = False) -> str:
    """Build one systemctl command, optionally tolerating absent legacy/OTA units."""
    command = f"sudo systemctl {action} {shlex.quote(unit)}"
    if optional:
        return f"{command} >/dev/null 2>&1 || true"
    return command


def _build_activate(lane: str, lanes: LanePaths) -> str:
    """Build the shell command that activates one lane and deactivates the other."""
    if lane == "dev":
        steps = [
            _sudo_systemctl("disable --now", lanes.prod_ota_timer, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_ota_service, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_service, optional=True),
            _sudo_systemctl("disable --now", lanes.legacy_slot_service, optional=True),
            _sudo_systemctl("reset-failed", lanes.dev_service, optional=True),
            _sudo_systemctl("enable --now", lanes.dev_service),
        ]
    elif lane == "prod":
        steps = [
            _sudo_systemctl("disable --now", lanes.dev_service, optional=True),
            _sudo_systemctl("reset-failed", lanes.prod_service, optional=True),
            _sudo_systemctl("enable --now", lanes.prod_service),
            _sudo_systemctl("enable --now", lanes.prod_ota_timer, optional=True),
        ]
    else:
        raise typer.BadParameter("lane must be one of: dev, prod")
    return " && ".join(steps)


def _build_deactivate(lane: str, lanes: LanePaths) -> str:
    """Build the shell command that disables one lane without enabling another."""
    if lane == "dev":
        steps = [_sudo_systemctl("disable --now", lanes.dev_service, optional=True)]
    elif lane == "prod":
        steps = [
            _sudo_systemctl("disable --now", lanes.prod_ota_timer, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_ota_service, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_service, optional=True),
            _sudo_systemctl("disable --now", lanes.legacy_slot_service, optional=True),
        ]
    else:
        raise typer.BadParameter("lane must be one of: dev, prod")
    return " && ".join(steps)


def _build_status(lanes: LanePaths) -> str:
    """Build a compact lane status report."""
    dev_service = shlex.quote(lanes.dev_service)
    prod_service = shlex.quote(lanes.prod_service)
    prod_ota_timer = shlex.quote(lanes.prod_ota_timer)
    dev_checkout = shlex.quote(lanes.dev_checkout)
    prod_current = shlex.quote(f"{lanes.prod_root}/current")
    return (
        f"dev_active=$(systemctl is-active {dev_service} 2>/dev/null || true); "
        f"prod_active=$(systemctl is-active {prod_service} 2>/dev/null || true); "
        'if [ "$dev_active" = active ] && [ "$prod_active" = active ]; then '
        "active_lane=conflict; "
        'elif [ "$dev_active" = active ]; then active_lane=dev; '
        'elif [ "$prod_active" = active ]; then active_lane=prod; '
        "else active_lane=none; fi; "
        'printf "active_lane=%s\\n" "$active_lane"; '
        f'printf "dev_service={lanes.dev_service} status=%s\\n" "$dev_active"; '
        f'printf "prod_service={lanes.prod_service} status=%s\\n" "$prod_active"; '
        f"printf 'prod_ota_timer={lanes.prod_ota_timer} status=%s\\n' "
        f'"$(systemctl is-active {prod_ota_timer} 2>/dev/null || true)"; '
        f"printf 'dev_checkout={lanes.dev_checkout} exists=%s\\n' "
        f'"$(test -d {dev_checkout} && echo yes || echo no)"; '
        f'prod_current="$(readlink -f {prod_current} 2>/dev/null || true)"; '
        'if [ -n "$prod_current" ]; then printf "prod_current=%s\\n" "$prod_current"; '
        "else printf 'prod_current=NONE\\n'; fi"
    )


@app.command("status")
def status(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Show which lane is active and where each lane points."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_status(load_lane_paths()), workdir=None))


@app.command("activate")
def activate(
    ctx: typer.Context,
    lane: str = typer.Argument(..., help="Lane to activate: dev or prod."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Activate one lane, stopping the other lane first."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_activate(lane, load_lane_paths()), workdir=None))


@app.command("deactivate")
def deactivate(
    ctx: typer.Context,
    lane: str = typer.Argument(..., help="Lane to deactivate: dev or prod."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Deactivate one lane without enabling the other."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_deactivate(lane, load_lane_paths()), workdir=None))
