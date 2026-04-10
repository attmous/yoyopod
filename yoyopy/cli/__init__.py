"""yoyopy/cli/__init__.py — yoyoctl root application."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="yoyoctl",
    help="YoyoPod development and hardware CLI.",
    no_args_is_help=True,
)

# -- pi group (on-device commands) -----------------------------------------
from yoyopy.cli.pi import pi_app  # noqa: E402
app.add_typer(pi_app)

# -- remote group (SSH wrapper commands) ------------------------------------
remote_app = typer.Typer(name="remote", help="Commands that SSH to the Raspberry Pi from the dev machine.", no_args_is_help=True)
app.add_typer(remote_app)

# -- build group (native extension builds) ----------------------------------
from yoyopy.cli.build import build_app  # noqa: E402
app.add_typer(build_app)


def run() -> None:
    """Entry point for the yoyoctl console script."""
    app()
