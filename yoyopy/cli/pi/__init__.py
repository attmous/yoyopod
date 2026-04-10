"""yoyopy/cli/pi/__init__.py — pi command group (on-device commands)."""

from __future__ import annotations

import typer

from yoyopy.cli.pi.voip import voip_app

pi_app = typer.Typer(name="pi", help="Commands that run ON the Raspberry Pi.", no_args_is_help=True)
pi_app.add_typer(voip_app)
