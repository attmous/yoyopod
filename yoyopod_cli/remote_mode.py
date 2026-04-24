"""Remote dev/prod lane switching commands."""

from __future__ import annotations

import shlex

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import LanePaths, SlotPaths, load_lane_paths, load_slot_paths
from yoyopod_cli.remote_shared import pi_conn
from yoyopod_cli.remote_transport import run_remote, validate_config

app = typer.Typer(
    name="mode",
    help="Inspect and switch mutually-exclusive dev checkout and prod OTA lanes.",
)


def _sudo_systemctl(action: str, unit: str, *, optional: bool = False) -> str:
    """Build one systemctl command, optionally tolerating absent legacy/OTA units."""
    command = f"sudo systemctl {action} {shlex.quote(unit)}"
    if optional:
        return f"{command} >/dev/null 2>&1 || true"
    return command


def _disable_legacy_template_services() -> str:
    """Disable old yoyopod@<user> services that predate the lane split."""
    pattern = shlex.quote("yoyopod@*.service")
    return (
        f"legacy_units=$(systemctl list-units --type=service --all --plain --no-legend "
        f"{pattern} 2>/dev/null | awk '{{print $1}}' || true); "
        'if [ -n "$legacy_units" ]; then '
        "sudo systemctl disable --now $legacy_units >/dev/null 2>&1 || true; "
        "fi"
    )


def _build_activate(lane: str, lanes: LanePaths) -> str:
    """Build the shell command that activates one lane and deactivates the other."""
    if lane == "dev":
        steps = [
            _sudo_systemctl("disable --now", lanes.prod_ota_timer, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_ota_service, optional=True),
            _sudo_systemctl("disable --now", lanes.prod_service, optional=True),
            _sudo_systemctl("disable --now", lanes.legacy_slot_service, optional=True),
            _disable_legacy_template_services(),
            _sudo_systemctl("reset-failed", lanes.dev_service, optional=True),
            _sudo_systemctl("enable --now", lanes.dev_service),
        ]
    elif lane == "prod":
        steps = [
            _sudo_systemctl("disable --now", lanes.dev_service, optional=True),
            _sudo_systemctl("disable --now", lanes.legacy_slot_service, optional=True),
            _disable_legacy_template_services(),
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


def _build_status(lanes: LanePaths, slot: SlotPaths) -> str:
    """Build a compact lane status report."""
    dev_service = shlex.quote(lanes.dev_service)
    prod_service = shlex.quote(lanes.prod_service)
    prod_ota_service = shlex.quote(lanes.prod_ota_service)
    prod_ota_timer = shlex.quote(lanes.prod_ota_timer)
    dev_checkout = shlex.quote(lanes.dev_checkout)
    prod_current = shlex.quote(slot.current_path())
    legacy_slot_service = shlex.quote(lanes.legacy_slot_service)
    legacy_pattern = shlex.quote("yoyopod@*.service")
    manual_pattern = shlex.quote(r"python(3)? .*yoyopod(\.py|\.main)")
    return (
        f"dev_active=$(systemctl is-active {dev_service} 2>/dev/null || true); "
        f"prod_active=$(systemctl is-active {prod_service} 2>/dev/null || true); "
        f"prod_ota_active=$(systemctl is-active {prod_ota_service} 2>/dev/null || true); "
        f"prod_ota_timer_active=$(systemctl is-active {prod_ota_timer} 2>/dev/null || true); "
        f"legacy_template_units=$(systemctl list-units --type=service --state=active --plain --no-legend "
        f"{legacy_pattern} 2>/dev/null | awk '{{print $1}}' | tr '\\n' ' ' | sed 's/[[:space:]]*$//' || true); "
        f"legacy_slot_unit={legacy_slot_service}; "
        'legacy_slot_active=$(systemctl is-active "$legacy_slot_unit" 2>/dev/null || true); '
        'legacy_units="$legacy_template_units"; '
        'if [ "$legacy_slot_active" = active ]; then legacy_units="${legacy_units:+$legacy_units }$legacy_slot_unit"; fi; '
        f"dev_pid=$(systemctl show -p MainPID --value {dev_service} 2>/dev/null || true); "
        f"prod_pid=$(systemctl show -p MainPID --value {prod_service} 2>/dev/null || true); "
        "legacy_pids=$(for unit in $legacy_units; do "
        'systemctl show -p MainPID --value "$unit" 2>/dev/null || true; '
        "done | tr '\\n' ' '); "
        f"manual_processes=$(pgrep -af {manual_pattern} 2>/dev/null | "
        "while read -r pid cmd; do "
        'case " $dev_pid $prod_pid $legacy_pids " in *" $pid "*) ;; '
        '*) printf "%s %s\\n" "$pid" "$cmd";; esac; '
        "done || true); "
        "lane_count=0; conflict_reasons=; "
        'if [ "$dev_active" = active ]; then lane_count=$((lane_count + 1)); '
        'conflict_reasons="$conflict_reasons dev"; fi; '
        'if [ "$prod_active" = active ]; then lane_count=$((lane_count + 1)); '
        'conflict_reasons="$conflict_reasons prod"; fi; '
        'if [ -n "$legacy_units" ]; then lane_count=$((lane_count + 1)); '
        'conflict_reasons="$conflict_reasons legacy"; fi; '
        'if [ -n "$manual_processes" ]; then lane_count=$((lane_count + 1)); '
        'conflict_reasons="$conflict_reasons manual-process"; fi; '
        'if [ "$dev_active" = active ] && '
        '{ [ "$prod_ota_active" = active ] || [ "$prod_ota_timer_active" = active ]; }; then '
        "prod_ota_conflict=prod-ota-active-while-dev; "
        'conflict_reasons="$conflict_reasons prod-ota"; '
        "else prod_ota_conflict=none; fi; "
        'if [ "$lane_count" -gt 1 ] || [ "$prod_ota_conflict" != none ]; then '
        "active_lane=conflict; "
        'elif [ "$dev_active" = active ]; then active_lane=dev; '
        'elif [ "$prod_active" = active ]; then active_lane=prod; '
        'elif [ -n "$legacy_units" ]; then active_lane=legacy; '
        'elif [ -n "$manual_processes" ]; then active_lane=manual-process; '
        "else active_lane=none; fi; "
        'printf "active_lane=%s\\n" "$active_lane"; '
        f'printf "dev_service={lanes.dev_service} status=%s\\n" "$dev_active"; '
        f'printf "prod_service={lanes.prod_service} status=%s\\n" "$prod_active"; '
        f'printf "prod_ota_service={lanes.prod_ota_service} status=%s\\n" "$prod_ota_active"; '
        f'printf "prod_ota_timer={lanes.prod_ota_timer} status=%s\\n" "$prod_ota_timer_active"; '
        'printf "prod_ota_conflict=%s\\n" "$prod_ota_conflict"; '
        'printf "legacy_units=%s\\n" "${legacy_units:-none}"; '
        'if [ -n "$manual_processes" ]; then printf "manual_processes=%s\\n" '
        "\"$(printf %s \"$manual_processes\" | tr '\\n' '|')\"; "
        "else printf 'manual_processes=none\\n'; fi; "
        'conflict_reasons="${conflict_reasons# }"; '
        'printf "conflict_reasons=%s\\n" "${conflict_reasons:-none}"; '
        f"printf 'dev_checkout={lanes.dev_checkout} exists=%s\\n' "
        f'"$(test -d {dev_checkout} && echo yes || echo no)"; '
        f'prod_current="$(readlink -f {prod_current} 2>/dev/null || true)"; '
        'if [ -n "$prod_current" ]; then printf "prod_current=%s\\n" "$prod_current"; '
        "else printf 'prod_current=NONE\\n'; fi"
    )


@app.command("status")
def status(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Show active lane, legacy services, manual processes, and OTA conflicts."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(
        run_remote(conn, _build_status(load_lane_paths(), load_slot_paths()), workdir=None)
    )


@app.command("activate")
def activate(
    ctx: typer.Context,
    lane: str = typer.Argument(..., help="Lane to activate: dev or prod."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Activate dev or prod, stopping conflicting app and legacy services first."""
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
