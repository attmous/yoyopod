"""Runtime ops on the Pi via SSH — status, sync, restart, logs, screenshot."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import HOST, PiPaths, load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_remote,
    shell_quote,
    validate_config,
)

app = build_remote_app("ops", "Runtime ops on the Pi via SSH.")


# ---- shell builders (private, single-file) ----------------------------------


def _build_status(pi: PiPaths) -> str:
    """Build the shell that prints repo SHA, process list, and log tail."""
    log = shell_quote(pi.log_file)
    pid = shell_quote(pi.pid_file)
    return (
        f"echo '=== git ===' && git rev-parse HEAD && "
        f"echo '=== processes ===' && (ps aux | grep -E 'python|mpv|linphonec' | grep -v grep || true) && "
        f"echo '=== pid ===' && (cat {pid} 2>/dev/null || echo 'no pid file') && "
        f"echo '=== log tail ===' && (tail -n 20 {log} 2>/dev/null || echo 'no log file')"
    )


def _build_restart(pi: PiPaths) -> str:
    """Build the shell that kills the app processes; systemd restarts them."""
    kills = " ; ".join(f"pkill -f {shell_quote(proc)} || true" for proc in pi.kill_processes)
    return f"{kills} ; echo 'processes signalled - systemd will respawn'"


def _build_logs_tail(
    pi: PiPaths,
    *,
    lines: int,
    follow: bool,
    errors: bool,
    filter_pattern: str,
) -> str:
    """Build the log-tail shell with optional follow/errors/filter."""
    log = pi.error_log_file if errors else pi.log_file
    cmd = f"tail -n {lines}{' -f' if follow else ''} {shell_quote(log)}"
    if filter_pattern:
        # Always single-quote the pattern so grep receives it verbatim on the remote.
        # POSIX escape for a single quote inside single-quoted string: '\''
        escaped = filter_pattern.replace("'", "'\\''")
        cmd += f" | grep '{escaped}'"
    return cmd


def _build_sync(pi: PiPaths, branch: str) -> str:
    """Build the shell that fetches + fast-forwards branch and restarts via kill."""
    br = shell_quote(branch)
    return (
        f"git fetch origin && "
        f"git checkout {br} && "
        f"git reset --hard origin/{br} && "
        f"{_build_restart(pi)}"
    )


# ---- commands ---------------------------------------------------------------


@app.command()
def status(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Show repo SHA, processes, and log tail on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_status(pi)))


@app.command()
def restart(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Restart the yoyopod app on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_restart(pi)))


@app.command()
def logs(
    ctx: typer.Context,
    lines: int = typer.Option(50, "--lines", help="Number of lines to tail."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
    errors: bool = typer.Option(False, "--errors", help="Tail the error log."),
    filter: str = typer.Option("", "--filter", help="Grep filter applied to the output."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Tail yoyopod logs on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    cmd = _build_logs_tail(pi, lines=lines, follow=follow, errors=errors, filter_pattern=filter)
    raise typer.Exit(run_remote(conn, cmd, tty=follow))


@app.command()
def sync(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Fetch + hard-reset branch on the Pi and restart the app (fast deploy)."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_sync(pi, conn.branch)))


@app.command()
def screenshot(
    ctx: typer.Context,
    out: str = typer.Option(
        "", "--out", help="Local file path. Default: logs/screenshots/<timestamp>.png"
    ),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Capture the display shadow buffer from the Pi and copy it locally."""
    from datetime import datetime

    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()

    remote_png = pi.screenshot_path
    # Use a heredoc so shell quoting doesn't conflict with Python string quotes.
    python_path_literal = repr(remote_png)
    python_src = (
        "from yoyopod.ui.display.factory import capture_shadow_png\n"
        f"capture_shadow_png({python_path_literal})\n"
    )
    cmd = f"python - <<'PY_SCREENSHOT_EOF'\n{python_src}PY_SCREENSHOT_EOF"
    rc = run_remote(conn, cmd)
    if rc != 0:
        raise typer.Exit(rc)

    local_target = (
        Path(out)
        if out
        else HOST.repo_root / "logs" / "screenshots" / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    )
    local_target.parent.mkdir(parents=True, exist_ok=True)

    scp_cmd = ["scp", f"{conn.ssh_target}:{remote_png}", str(local_target)]
    completed = subprocess.run(scp_cmd, check=False)
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)
    typer.echo(f"screenshot saved to {local_target}")
