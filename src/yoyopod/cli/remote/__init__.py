"""src/yoyopod/cli/remote/__init__.py — remote command group (SSH wrapper commands)."""

from __future__ import annotations

import typer

from yoyopod.cli.remote.infra import config, power, service
from yoyopod.cli.remote.lvgl import lvgl_soak
from yoyopod.cli.remote.ops import (
    logs,
    preflight,
    provision_test_music,
    restart,
    rsync,
    rtc,
    screenshot,
    smoke,
    status,
    sync,
    validate,
    whisplay,
)
from yoyopod.cli.remote.setup import setup, verify_setup

remote_app = typer.Typer(
    name="remote",
    help="Commands that SSH to the Raspberry Pi from the dev machine.",
    no_args_is_help=True,
)

remote_app.command()(status)
remote_app.command()(sync)
remote_app.command()(validate)
remote_app.command()(smoke)
remote_app.command(name="provision-test-music")(provision_test_music)
remote_app.command()(preflight)
remote_app.command()(restart)
remote_app.command()(logs)
remote_app.command()(screenshot)
remote_app.command()(rsync)
remote_app.command(name="lvgl-soak")(lvgl_soak)
remote_app.command()(power)
remote_app.command()(whisplay)
remote_app.command()(rtc)
remote_app.command()(config)
remote_app.command()(service)
remote_app.command()(setup)
remote_app.command(name="verify-setup")(verify_setup)
