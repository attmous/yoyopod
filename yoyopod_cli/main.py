"""
yoyopod — app launcher and CLI dispatcher.

Usage:
    yoyopod                      # Launch the YoyoPod app
    yoyopod deploy               # Sync code to the Pi and restart
    yoyopod status               # Pi health dashboard
    yoyopod logs [-f --errors]   # Tail logs from the Pi
    yoyopod restart              # Restart the app on the Pi
    yoyopod validate             # Run the validation suite on the Pi
    yoyopod remote <cmd>         # Dev-machine → Pi commands
    yoyopod pi <cmd>             # On-device commands
    yoyopod build <cmd>          # Native extension builds
    yoyopod setup <cmd>          # Host and Pi setup
"""

from __future__ import annotations

from typing import Any

import typer

from yoyopod_cli import __version__

app = typer.Typer(
    name="yoyopod",
    help="YoyoPod app launcher and CLI.",
    no_args_is_help=False,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yoyopod {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Launch the YoyoPod app when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        from yoyopod.main import main as launch_app

        rc = launch_app()
        raise typer.Exit(rc if isinstance(rc, int) else 0)


def run() -> None:
    """Entry-point shim used by ``[project.scripts]``."""
    app()


# --- subapps ---
from yoyopod_cli import build as _build  # noqa: E402

app.add_typer(_build.app, name="build")

from yoyopod_cli import setup as _setup  # noqa: E402

app.add_typer(_setup.app, name="setup")

# --- remote group (assembled from flat sub-modules)
from yoyopod_cli import (  # noqa: E402
    remote_config as _remote_config,
    remote_infra as _remote_infra,
    remote_ops as _remote_ops,
    remote_setup as _remote_setup,
    remote_validate as _remote_validate,
)
from yoyopod_cli.remote_shared import build_remote_app as _build_remote_app  # noqa: E402

remote_app = _build_remote_app("remote", "Dev-machine -> Pi commands via SSH.")

# ops commands
remote_app.command(name="status")(_remote_ops.status)
remote_app.command(name="sync")(_remote_ops.sync)
remote_app.command(name="restart")(_remote_ops.restart)
remote_app.command(name="logs")(_remote_ops.logs)
remote_app.command(name="screenshot")(_remote_ops.screenshot)

# validate / preflight
remote_app.command(name="preflight")(_remote_validate.preflight)
remote_app.command(name="validate")(_remote_validate.validate)

# infra
remote_app.command(name="power")(_remote_infra.power)
remote_app.command(name="rtc")(_remote_infra.rtc)
remote_app.command(name="service")(_remote_infra.service)

# setup
remote_app.command(name="setup")(_remote_setup.setup)
remote_app.command(name="verify-setup")(_remote_setup.verify_setup)

# config (operates on local files — its own subgroup)
remote_app.add_typer(_remote_config.app, name="config")

app.add_typer(remote_app, name="remote")

# --- pi group (commands that run on the Pi directly)
from yoyopod_cli import (  # noqa: E402
    pi_network as _pi_network,
    pi_power as _pi_power,
    pi_validate as _pi_validate,
    pi_voip as _pi_voip,
)

pi_app = typer.Typer(name="pi", help="Commands that run on the Raspberry Pi.", no_args_is_help=True)
pi_app.add_typer(_pi_validate.app, name="validate")
pi_app.add_typer(_pi_voip.app, name="voip")
pi_app.add_typer(_pi_power.app, name="power")
pi_app.add_typer(_pi_network.app, name="network")

app.add_typer(pi_app, name="pi")

# --- top-level shortcut commands (thin aliases to remote_ops / remote_validate)
from yoyopod_cli.remote_shared import _resolve_remote_connection as _resolve_conn  # noqa: E402


def _with_connection(host: str, user: str, project_dir: str, branch: str) -> Any:
    """Build a typer.Context-like object carrying a RemoteConnection for shortcut handlers."""

    class _Ctx:
        def __init__(self, conn: Any) -> None:
            self.obj = conn

        def ensure_object(self, cls: Any) -> Any:
            if not isinstance(self.obj, cls):
                raise RuntimeError("shortcut context not seeded with a RemoteConnection")
            return self.obj

    conn = _resolve_conn(host, user, project_dir, branch)
    return _Ctx(conn)


@app.command(name="deploy")
def _deploy_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Sync code to the Pi and restart (alias for `remote sync`)."""
    _remote_ops.sync(ctx=_with_connection(host, user, project_dir, branch), verbose=verbose)


@app.command(name="status")
def _status_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Show Pi health dashboard (alias for `remote status`)."""
    _remote_ops.status(ctx=_with_connection(host, user, project_dir, branch), verbose=verbose)


@app.command(name="restart")
def _restart_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Restart the yoyopod app on the Pi (alias for `remote restart`)."""
    _remote_ops.restart(ctx=_with_connection(host, user, project_dir, branch), verbose=verbose)


@app.command(name="logs")
def _logs_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    lines: int = typer.Option(50, "--lines"),
    follow: bool = typer.Option(False, "--follow", "-f"),
    errors: bool = typer.Option(False, "--errors"),
    filter: str = typer.Option("", "--filter"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Tail yoyopod logs on the Pi (alias for `remote logs`)."""
    _remote_ops.logs(
        ctx=_with_connection(host, user, project_dir, branch),
        lines=lines,
        follow=follow,
        errors=errors,
        filter=filter,
        verbose=verbose,
    )


@app.command(name="validate")
def _validate_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    sha: str = typer.Option(
        "",
        "--sha",
        help="Pin validation to a specific commit (must be an ancestor of origin/<branch>).",
    ),
    with_music: bool = typer.Option(False, "--with-music"),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_power: bool = typer.Option(False, "--with-power"),
    with_rtc: bool = typer.Option(False, "--with-rtc"),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation (alias for `remote validate`)."""
    _remote_validate.validate(
        ctx=_with_connection(host, user, project_dir, branch),
        sha=sha,
        with_music=with_music,
        with_voip=with_voip,
        with_power=with_power,
        with_rtc=with_rtc,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
        verbose=verbose,
    )


# --- dev utilities
dev_app = typer.Typer(name="dev", help="Developer utilities.", no_args_is_help=True)
app.add_typer(dev_app, name="dev")


@dev_app.command()
def docs() -> None:
    """Regenerate yoyopod_cli/COMMANDS.md from the live Typer tree."""
    from yoyopod_cli._docgen import generate_commands_md
    from yoyopod_cli.paths import HOST

    md = generate_commands_md(app)
    (HOST.repo_root / "yoyopod_cli" / "COMMANDS.md").write_text(md, encoding="utf-8")
    typer.echo("yoyopod_cli/COMMANDS.md regenerated.")
