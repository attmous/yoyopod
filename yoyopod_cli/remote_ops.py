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
        f"echo '=== processes ===' && (ps aux | grep -E 'python|mpv|linphonec' | grep -v grep || true) && "
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
    """Build the shell that rebuilds missing or stale native shims before restart."""
    activate = shell_quote(_activate_script_path(pi.venv))
    return (
        "{ "
        f"source {activate} && python - <<'PY'\n"
        "import subprocess\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def newest_mtime(paths: list[Path]) -> float:\n"
        "    newest = 0.0\n"
        "    for path in paths:\n"
        "        if not path.exists():\n"
        "            continue\n"
        "        if path.is_dir():\n"
        "            for candidate in path.rglob('*'):\n"
        "                if candidate.is_file():\n"
        "                    newest = max(newest, candidate.stat().st_mtime)\n"
        "            continue\n"
        "        newest = max(newest, path.stat().st_mtime)\n"
        "    return newest\n"
        "\n"
        "\n"
        "def is_stale(binary: Path, sources: list[Path]) -> bool:\n"
        "    if not binary.exists():\n"
        "        return True\n"
        "    return newest_mtime(sources) > binary.stat().st_mtime\n"
        "\n"
        "\n"
        "jobs = [\n"
        "    (\n"
        "        'LVGL',\n"
        "        Path('src/yoyopod/ui/lvgl_binding/native/build/libyoyopod_lvgl_shim.so'),\n"
        "        [Path('src/yoyopod/ui/lvgl_binding/native')],\n"
        "        ['uv', 'run', 'yoyopod', 'build', 'lvgl'],\n"
        "    ),\n"
        "    (\n"
        "        'Liblinphone',\n"
        "        Path('src/yoyopod/communication/integrations/liblinphone/native/build/libyoyopod_liblinphone_shim.so'),\n"
        "        [Path('src/yoyopod/communication/integrations/liblinphone/native')],\n"
        "        ['uv', 'run', 'yoyopod', 'build', 'liblinphone'],\n"
        "    ),\n"
        "]\n"
        "\n"
        "for label, output, sources, command in jobs:\n"
        "    if not is_stale(output, sources):\n"
        "        continue\n"
        "    print(f'[pi-remote] info=rebuilding {label} native shim')\n"
        "    subprocess.run(command, check=True)\n"
        "PY\n"
        "} "
    )


def _build_restart(pi: PiPaths) -> str:
    """Build the shell that restarts the app and waits for startup verification."""
    pid = shell_quote(pi.pid_file)
    activate = shell_quote(_activate_script_path(pi.venv))
    service_name = 'yoyopod@"$(id -un)".service'
    cleanup_commands = [f"rm -f {pid}"]
    cleanup_commands.extend(f"pkill -f {shell_quote(proc)} || true" for proc in pi.kill_processes)
    cleanup = " ; ".join(cleanup_commands)
    manual_restart = (
        f"{cleanup} ; " f"source {activate} && (nohup {pi.start_cmd} > /dev/null 2>&1 &)"
    )
    managed_restart = (
        f"if systemctl cat {service_name} >/dev/null 2>&1; then "
        f"sudo systemctl stop {service_name} >/dev/null 2>&1 || true; "
        f"{cleanup} ; "
        f"sudo systemctl start {service_name}; "
        f"else {manual_restart}; "
        "fi"
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


def _build_sync(pi: PiPaths, branch: str) -> str:
    """Build the shell that syncs a clean checkout and restarts the app."""
    br = shell_quote(branch)
    origin_br = shell_quote(f"origin/{branch}")
    return (
        f"git fetch --prune origin && "
        "git clean -fd && "
        f"git checkout --force -B {br} {origin_br} && "
        "git clean -fd && "
        f"{_build_restart(pi)}"
    )


def _build_screenshot_alive_check(pi: PiPaths) -> str:
    """Remote shell that prints ALIVE if the app PID is live, DEAD otherwise."""
    pid = shell_quote(pi.pid_file)
    return f"test -f {pid} && kill -0 $(cat {pid}) 2>/dev/null " "&& echo ALIVE || echo DEAD"


def _build_screenshot_clear(pi: PiPaths) -> str:
    """Remote shell that removes any stale screenshot file."""
    return f"rm -f {shell_quote(pi.screenshot_path)}"


def _build_screenshot_signal(pi: PiPaths, *, readback: bool) -> str:
    """Remote shell that signals the app to capture a screenshot.

    SIGUSR1 = LVGL readback (hardware-accurate); SIGUSR2 = PIL shadow buffer.
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

    # 1. Verify app is alive
    alive = run_remote_capture(conn, _build_screenshot_alive_check(pi))
    if alive.returncode != 0 or alive.stdout.strip() != "ALIVE":
        typer.echo(
            "Remote app is not running; start/restart it before requesting a screenshot.",
            err=True,
        )
        if alive.stderr.strip():
            typer.echo(alive.stderr.strip(), err=True)
        raise typer.Exit(1)

    # 2. Clear stale screenshot
    clear = run_remote_capture(conn, _build_screenshot_clear(pi))
    if clear.returncode != 0:
        typer.echo("Failed to clear the previous screenshot on the Pi.", err=True)
        if clear.stderr.strip():
            typer.echo(clear.stderr.strip(), err=True)
        raise typer.Exit(clear.returncode)

    # 3. Signal the app to capture
    signal_result = run_remote_capture(conn, _build_screenshot_signal(pi, readback=readback))
    if signal_result.returncode != 0:
        typer.echo("Failed to trigger screenshot capture on the Pi.", err=True)
        if signal_result.stderr.strip():
            typer.echo(signal_result.stderr.strip(), err=True)
        raise typer.Exit(signal_result.returncode)

    # 4. Wait for the file to appear
    verify = run_remote_capture(conn, _build_screenshot_wait(pi))
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
