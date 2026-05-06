"""Show or edit deploy/pi-deploy.local.yaml (the per-host override file)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

import yaml
import typer

from yoyopod_cli.paths import HOST, load_pi_paths
from yoyopod_cli.remote_shared import _resolve_remote_connection

app = typer.Typer(name="config", help="Show or edit pi-deploy.local.yaml.", no_args_is_help=True)

_FALLBACK_EDITORS: tuple[tuple[str, ...], ...] = (
    ("code", "-w"),
    ("notepad",),
    ("sensible-editor",),
    ("editor",),
    ("nano",),
    ("vim",),
    ("vi",),
)


def _resolve_editor_argv() -> list[str]:
    """Return the configured editor argv or an installed fallback."""
    configured = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if configured:
        argv = shlex.split(configured)
        if argv:
            return argv
        raise RuntimeError("VISUAL/EDITOR is set but empty after parsing.")

    for candidate in _FALLBACK_EDITORS:
        resolved = shutil.which(candidate[0])
        if resolved:
            return [resolved, *candidate[1:]]

    candidates = ", ".join(candidate[0] for candidate in _FALLBACK_EDITORS)
    raise RuntimeError(f"No editor found. Set VISUAL or EDITOR, or install one of: {candidates}.")


@app.command()
def show() -> None:
    """Print the effective pi-deploy config (base merged with local override)."""
    conn = _resolve_remote_connection("", "", "", "")
    pi = load_pi_paths()

    effective = {
        "host": conn.host,
        "user": conn.user,
        "project_dir": conn.project_dir,
        "branch": conn.branch,
        "venv": pi.venv,
        "start_cmd": pi.start_cmd,
        "log_file": pi.log_file,
        "error_log_file": pi.error_log_file,
        "pid_file": pi.pid_file,
        "screenshot_path": pi.screenshot_path,
        "startup_marker": pi.startup_marker,
        "kill_processes": list(pi.kill_processes),
        "rsync_exclude": list(pi.rsync_exclude),
    }
    typer.echo(yaml.safe_dump(effective, sort_keys=False))


@app.command()
def edit() -> None:
    """Open deploy/pi-deploy.local.yaml in $EDITOR."""
    path = HOST.deploy_config_local
    if not path.exists():
        path.write_text(
            "# Host-specific overrides for deploy/pi-deploy.yaml\n"
            "# host: rpi-zero\n"
            "# user: pi\n"
            "# project_dir: /opt/yoyopod-dev/checkout\n",
            encoding="utf-8",
        )
    try:
        editor_argv = _resolve_editor_argv()
        completed = subprocess.run([*editor_argv, str(path)], check=False)
    except FileNotFoundError as exc:
        typer.echo(
            f"Could not launch editor `{exc.filename}`. Set VISUAL or EDITOR to an installed command.",
            err=True,
        )
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    raise typer.Exit(completed.returncode)
