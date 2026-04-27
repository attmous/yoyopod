"""Commands that run on the Raspberry Pi."""

from __future__ import annotations

import typer

from yoyopod_cli.pi import (
    network as _network,
    power as _power,
    validate as _validate,
    voip as _voip,
)

app = typer.Typer(
    name="pi",
    help="Commands that run on the Raspberry Pi.",
    no_args_is_help=True,
)
app.add_typer(_validate.app, name="validate")
app.add_typer(_voip.app, name="voip")
app.add_typer(_power.app, name="power")
app.add_typer(_network.app, name="network")

__all__ = ["app"]
