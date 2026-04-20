"""Shared Pi-connection state for remote CLI groups.

Every `yoyopod remote <group>` has a typer.callback() that captures the four
Pi-connection flags once. Individual command handlers pull the typed
`RemoteConnection` via `pi_conn(ctx)` -- no duplication.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from yoyopod_cli.paths import HOST, _load_yaml, load_pi_paths


@dataclass(frozen=True)
class RemoteConnection:
    """Connection details resolved from CLI flags + env vars + YAML defaults."""

    host: str
    user: str
    project_dir: str
    branch: str

    @property
    def ssh_target(self) -> str:
        """Return the SSH target as `user@host` or just `host`."""
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


def _coerce_text(value: object, default: str) -> str:
    """Normalize one YAML/default value into text, treating None as missing."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _resolve_remote_connection(
    host: str,
    user: str,
    project_dir: str,
    branch: str,
) -> RemoteConnection:
    """Merge CLI flags (highest) -> env (already handled by Typer) -> YAML defaults."""
    pi = load_pi_paths()

    defaults: dict[str, object] = {}
    for layer in (_load_yaml(HOST.deploy_config), _load_yaml(HOST.deploy_config_local)):
        for key, value in layer.items():
            if value is not None:
                defaults[key] = value

    return RemoteConnection(
        host=host or _coerce_text(defaults.get("host"), ""),
        user=user or _coerce_text(defaults.get("user"), ""),
        project_dir=project_dir or _coerce_text(defaults.get("project_dir"), pi.project_dir),
        branch=branch or _coerce_text(defaults.get("branch"), "main"),
    )


def build_remote_app(name: str, help: str) -> typer.Typer:
    """Build a Typer sub-app with the shared Pi-connection callback."""
    app = typer.Typer(name=name, help=help, no_args_is_help=True)

    @app.callback()
    def _capture_connection(
        ctx: typer.Context,
        host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST", help="SSH host or alias."),
        user: str = typer.Option(
            "", "--user", envvar="YOYOPOD_PI_USER", help="SSH user (optional)."
        ),
        project_dir: str = typer.Option(
            "", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR", help="Project dir on the Pi."
        ),
        branch: str = typer.Option(
            "", "--branch", envvar="YOYOPOD_PI_BRANCH", help="Git branch to target."
        ),
    ) -> None:
        ctx.obj = _resolve_remote_connection(host, user, project_dir, branch)

    return app


def pi_conn(ctx: typer.Context) -> RemoteConnection:
    """Typed accessor for the shared Pi connection."""
    if not isinstance(ctx.obj, RemoteConnection):
        raise RuntimeError(
            "pi_conn() called on a context without a RemoteConnection. "
            "Ensure the parent group is built via build_remote_app()."
        )
    return ctx.obj
