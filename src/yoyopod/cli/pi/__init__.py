"""src/yoyopod/cli/pi/__init__.py — pi command group (on-device commands)."""

from __future__ import annotations

import typer

from yoyopod.cli.pi.gallery import gallery_app
from yoyopod.cli.pi.lvgl import lvgl_app
from yoyopod.cli.pi.network import network_app
from yoyopod.cli.pi.power import power_app
from yoyopod.cli.pi.smoke import smoke_app
from yoyopod.cli.pi.tune import tune_app
from yoyopod.cli.pi.validate import validate_app
from yoyopod.cli.pi.voip import voip_app

pi_app = typer.Typer(name="pi", help="Commands that run ON the Raspberry Pi.", no_args_is_help=True)
pi_app.add_typer(validate_app)
pi_app.add_typer(voip_app)
pi_app.add_typer(power_app)
pi_app.add_typer(network_app)
pi_app.add_typer(lvgl_app)
pi_app.add_typer(smoke_app)
pi_app.add_typer(tune_app)
pi_app.add_typer(gallery_app)
