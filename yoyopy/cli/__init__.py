"""yoyopy/cli/__init__.py — yoyoctl root application."""

from __future__ import annotations

try:
    import typer
except ImportError:
    import sys

    print(
        "yoyoctl requires dev dependencies. Install with:\n"
        "  uv sync --extra dev",
        file=sys.stderr,
    )
    raise SystemExit(1)

app = typer.Typer(
    name="yoyoctl",
    help="YoyoPod development and hardware CLI.",
    no_args_is_help=True,
)

# -- pi group (on-device commands) -----------------------------------------
from yoyopy.cli.pi import pi_app  # noqa: E402
app.add_typer(pi_app)

# -- remote group (SSH wrapper commands) ------------------------------------
from yoyopy.cli.remote import remote_app  # noqa: E402
app.add_typer(remote_app)

# -- build group (native extension builds) ----------------------------------
from yoyopy.cli.build import build_app  # noqa: E402
app.add_typer(build_app)


def run() -> None:
    """Entry point for the yoyoctl console script."""
    app()
