"""Runtime ops on the Pi via SSH — status, sync, restart, logs, screenshot."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from yoyopod_cli.common import checkout_module_command, configure_logging
from yoyopod_cli.paths import HOST, LanePaths, PiPaths, load_lane_paths, load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_remote,
    run_remote_capture,
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
        f"echo '=== processes ===' && (ps aux | grep -E 'yoyopod-runtime|mpv' | grep -v grep || true) && "
        f"echo '=== pid ===' && (cat {pid} 2>/dev/null || echo 'no pid file') && "
        f"echo '=== log tail ===' && (tail -n 20 {log} 2>/dev/null || echo 'no log file')"
    )


def _activate_script_path(venv: str) -> str:
    """Return the shell path for activating the configured virtualenv."""
    normalized = venv.rstrip("/")
    if normalized.endswith("/bin/activate"):
        return normalized
    return f"{normalized}/bin/activate"


def _build_startup_verification(pi: PiPaths, *, attempts: int = 20) -> str:
    """Build the shell that waits for the PID file and startup marker."""
    pid = shell_quote(pi.pid_file)
    log = shell_quote(pi.log_file)
    marker = shell_quote(pi.startup_marker)
    return " && ".join(
        [
            (f"for _ in $(seq 1 {attempts}); do " f"test -f {pid} && break; " "sleep 1; " "done"),
            f"test -f {pid}",
            f"pid=\"$(tr -d '\\n' < {pid})\"",
            'test -n "$pid"',
            'kill -0 "$pid"',
            (
                f"for _ in $(seq 1 {attempts}); do "
                f"if test -f {log} && "
                f'grep -F {marker} {log} | tail -n 1 | grep -F "pid=$pid" >/dev/null; then '
                "break; "
                "fi; "
                "sleep 1; "
                "done"
            ),
            f'grep -F {marker} {log} | tail -n 1 | grep -F "pid=$pid"',
        ]
    )


def _build_native_shim_refresh(pi: PiPaths) -> str:
    """Build the shell that refreshes missing or stale native artifacts before restart."""
    return "{ " f"{checkout_module_command(pi.venv, 'build', 'ensure-native')}" " ; }"


def _build_stale_app_cleanup() -> str:
    """Kill only unmanaged/stale YoYoPod app processes, without matching this shell."""
    return r"pkill -f '[y]oyopod-runtime' || true"


def _build_restart(pi: PiPaths, lanes: LanePaths | None = None) -> str:
    """Build the shell that restarts the app and waits for startup verification."""
    lane_paths = lanes or load_lane_paths()
    pid = shell_quote(pi.pid_file)
    dev_service = shell_quote(lane_paths.dev_service)
    selected_checkout_guard = (
        'selected_checkout="$(pwd -P)"; '
        'dev_service_checkout="$(set -a; '
        "[ -f /etc/default/yoyopod-dev ] && . /etc/default/yoyopod-dev; "
        'printf "%s" "${YOYOPOD_DEV_CHECKOUT:-/opt/yoyopod-dev/checkout}")"; '
        'dev_service_checkout="$(cd "$dev_service_checkout" 2>/dev/null && '
        'pwd -P || printf "%s" "$dev_service_checkout")"'
    )
    cleanup_commands = [f"rm -f {pid}"]
    cleanup_commands.append(_build_stale_app_cleanup())
    cleanup = " ; ".join(cleanup_commands)
    managed_restart = (
        f"{selected_checkout_guard}; "
        f"if ! systemctl cat {dev_service} >/dev/null 2>&1; then "
        "echo 'remote restart: dev lane service is not installed; run board bootstrap first' "
        ">&2; exit 2; "
        "fi; "
        'if [ "$selected_checkout" != "$dev_service_checkout" ]; then '
        'echo "remote restart: selected checkout $selected_checkout does not match '
        'dev lane checkout $dev_service_checkout" >&2; exit 2; '
        "fi; "
        f"sudo systemctl stop {dev_service} >/dev/null 2>&1 || true; "
        f"{cleanup} ; "
        f"sudo systemctl reset-failed {dev_service} >/dev/null 2>&1 || true; "
        f"sudo systemctl start {dev_service} || exit $?"
    )
    return " && ".join(
        [_build_native_shim_refresh(pi), managed_restart, _build_startup_verification(pi)]
    )


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
        cmd += f" | grep -- '{escaped}'"
    return cmd


def _build_sync(pi: PiPaths, branch: str, *, clean_native: bool = False) -> str:
    """Build the shell that syncs a clean checkout and restarts the app."""
    br = shell_quote(branch)
    origin_br = shell_quote(f"origin/{branch}")
    native_clean = (
        f"{checkout_module_command(pi.venv, 'build', 'clean-native')} && " if clean_native else ""
    )
    return (
        f"git fetch --prune origin && "
        "git clean -fd && "
        f"git checkout --force -B {br} {origin_br} && "
        "git clean -fd && "
        f"{native_clean}"
        f"{_build_restart(pi)}"
    )


def _build_screenshot_alive_check(pi: PiPaths) -> str:
    """Remote shell that prints ALIVE if the app PID is live, DEAD otherwise."""
    pid = shell_quote(pi.pid_file)
    return f"test -f {pid} && kill -0 $(cat {pid}) 2>/dev/null " "&& echo ALIVE || echo DEAD"


def _build_screenshot_ready_check(pi: PiPaths, *, attempts: int = 30) -> str:
    """Wait until the current app PID catches both screenshot signals."""
    pid = shell_quote(pi.pid_file)
    return (
        f"for _ in $(seq 1 {attempts}); do "
        f'pid_value="$(cat {pid} 2>/dev/null || true)"; '
        'if test -n "$pid_value" && kill -0 "$pid_value" 2>/dev/null && '
        'test -r "/proc/${pid_value}/status"; then '
        'sigcgt="$(awk \'/^SigCgt:/ {print $2}\' "/proc/${pid_value}/status")"; '
        'if test -n "$sigcgt"; then '
        "mask=$((16#$sigcgt)); "
        "if (( (mask & 0x200) != 0 && (mask & 0x800) != 0 )); then "
        "echo READY; exit 0; "
        "fi; "
        "fi; "
        "fi; "
        "sleep 1; "
        "done; "
        "echo NOT_READY; exit 1"
    )


def _build_screenshot_clear(pi: PiPaths) -> str:
    """Remote shell that removes any stale screenshot file."""
    return f"rm -f {shell_quote(pi.screenshot_path)}"


def _build_screenshot_signal(pi: PiPaths, *, readback: bool) -> str:
    """Remote shell that signals the app to capture a screenshot.

    SIGUSR1 = LVGL readback (hardware-accurate); SIGUSR2 = RGB565 framebuffer.
    """
    signal_name = "USR1" if readback else "USR2"
    pid = shell_quote(pi.pid_file)
    return f"kill -{signal_name} $(cat {pid})"


def _build_screenshot_wait(pi: PiPaths, *, attempts: int = 20) -> str:
    """Remote shell that waits up to `attempts` seconds for the PNG file."""
    path = shell_quote(pi.screenshot_path)
    return (
        f"for _ in $(seq 1 {attempts}); do "
        f"test -f {path} && echo READY && exit 0; "
        "sleep 1; "
        "done; "
        "echo MISSING"
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
def sync(
    ctx: typer.Context,
    clean_native: bool = typer.Option(
        False,
        "--clean-native",
        help="Remove dev lane native build dirs before rebuilding after a branch switch.",
    ),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Update the dev lane checkout from Git and restart the dev app service."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_sync(pi, conn.branch, clean_native=clean_native)))


@app.command()
def screenshot(
    ctx: typer.Context,
    out: str = typer.Option(
        "",
        "--out",
        help="Local file path. Default: logs/screenshots/<timestamp>.png",
    ),
    readback: bool = typer.Option(
        False,
        "--readback",
        help="Use LVGL readback (SIGUSR1) instead of shadow buffer (SIGUSR2).",
    ),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Capture a screenshot from the Pi's display and copy it locally.

    Signals the running app (PID from pid_file) via SIGUSR1/SIGUSR2 to trigger
    its registered save-screenshot handler. Requires the app to be running.
    """
    from datetime import datetime

    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()

    # 1. Verify the current app process has installed its signal handlers.
    ready = run_remote_capture(conn, _build_screenshot_ready_check(pi), workdir=None)
    if ready.returncode != 0 or ready.stdout.strip() != "READY":
        typer.echo(
            "Remote app is not ready for screenshot capture; "
            "wait for startup to finish or restart it before requesting a screenshot.",
            err=True,
        )
        if ready.stderr.strip():
            typer.echo(ready.stderr.strip(), err=True)
        raise typer.Exit(1)

    # 2. Clear stale screenshot
    clear = run_remote_capture(conn, _build_screenshot_clear(pi), workdir=None)
    if clear.returncode != 0:
        typer.echo("Failed to clear the previous screenshot on the Pi.", err=True)
        if clear.stderr.strip():
            typer.echo(clear.stderr.strip(), err=True)
        raise typer.Exit(clear.returncode)

    # 3. Signal the app to capture
    signal_result = run_remote_capture(
        conn, _build_screenshot_signal(pi, readback=readback), workdir=None
    )
    if signal_result.returncode != 0:
        typer.echo("Failed to trigger screenshot capture on the Pi.", err=True)
        if signal_result.stderr.strip():
            typer.echo(signal_result.stderr.strip(), err=True)
        raise typer.Exit(signal_result.returncode)

    # 4. Wait for the file to appear
    verify = run_remote_capture(conn, _build_screenshot_wait(pi), workdir=None)
    if verify.returncode != 0 or verify.stdout.strip() != "READY":
        typer.echo(
            "Screenshot was not created on the Pi within the timeout. "
            "Confirm the app is running and the screenshot signal handlers are installed. "
            "Inspect `yoyopod remote logs --errors` for tracebacks.",
            err=True,
        )
        if verify.stderr.strip():
            typer.echo(verify.stderr.strip(), err=True)
        raise typer.Exit(1)

    # 5. SCP the file back
    local_target = (
        Path(out)
        if out
        else HOST.repo_root / "logs" / "screenshots" / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    )
    local_target.parent.mkdir(parents=True, exist_ok=True)

    scp_cmd = ["scp", f"{conn.ssh_target}:{pi.screenshot_path}", str(local_target)]
    completed = subprocess.run(scp_cmd, check=False)
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)
    typer.echo(f"screenshot saved to {local_target}")
