"""Pi validation suite — staged checks for deployed YoYoPod hardware."""

from __future__ import annotations

import typer

from yoyopod_cli.pi.validate import (
    cloud_voice as _cloud_voice,
    deploy as _deploy,
    lvgl as _lvgl,
    music as _music,
    navigation as _navigation,
    stability as _stability,
    system as _system,
    voip as _voip,
)

app = typer.Typer(
    name="validate",
    help=(
        "Focused target-side validation suite for deploy, smoke, music, voip, "
        "and navigation stability checks."
    ),
    no_args_is_help=True,
)

app.command(name="deploy")(_deploy.deploy)
app.command(name="cloud-voice")(_cloud_voice.cloud_voice)
app.command(name="smoke")(_system.smoke)
app.command(name="music")(_music.music)
app.command(name="voip")(_voip.voip)
app.command(name="stability")(_stability.stability)
app.command(name="navigation")(_navigation.navigation)
app.command(name="lvgl")(_lvgl.lvgl)

__all__ = ["app"]
