"""yoyopod health {preflight,live} — offline + online health probes.

preflight: given a slot directory (not yet active), validate that it is
structurally sound enough to become current. Runs BEFORE the symlink flip.
Checks performed:
  * manifest.json exists and parses
  * venv/bin/python exists
  * native runtime shim `.so` files exist
  * app/ exists
  * bin/launch exists and is executable

live: reads YOYOPOD_RELEASE_MANIFEST (via yoyopod_cli.contracts.release.current_release)
and prints the running version. Used as a readiness probe after the flip.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer

from yoyopod_cli.contracts.release import current_release
from yoyopod_cli.contracts.setup import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod_cli.release_manifest import load_manifest
from yoyopod_cli.slot_contract import (
    SLOT_REQUIRED_DIRS,
    missing_hydrated_runtime_paths,
    missing_self_contained_paths,
)

app = typer.Typer(name="health", help="Slot-deploy health probes.")


@app.command("preflight")
def preflight(
    slot: Path = typer.Option(..., help="Path to the release slot dir (before flip)."),
    allow_hydrated_runtime: bool = typer.Option(
        False,
        "--allow-hydrated-runtime",
        help=(
            "Accept a legacy source slot after Pi-side hydration. "
            "Default requires a fully self-contained slot."
        ),
    ),
) -> None:
    """Offline structural check of a release slot. Exit 0 = OK."""
    slot = slot.resolve()
    errors: list[str] = []

    manifest_path = slot / "manifest.json"
    if not manifest_path.exists():
        errors.append(f"manifest.json missing at {manifest_path}")
    else:
        try:
            load_manifest(manifest_path)
        except ValueError as exc:
            errors.append(f"manifest.json invalid: {exc}")

    for required in SLOT_REQUIRED_DIRS:
        if not (slot / required).is_dir():
            errors.append(f"{required}/ missing in {slot}")

    runtime_missing = (
        missing_hydrated_runtime_paths(slot)
        if allow_hydrated_runtime
        else missing_self_contained_paths(slot)
    )
    for relative in runtime_missing:
        errors.append(f"required runtime file missing: {relative.as_posix()}")

    # Each runtime-required config file must be present in the slot.
    for relative in RUNTIME_REQUIRED_CONFIG_FILES:
        target = slot / relative
        if not target.is_file():
            errors.append(f"required config file missing: {relative}")

    launch = slot / "bin" / "launch"
    if not launch.exists():
        errors.append(f"bin/launch missing in {slot}")
    elif not os.access(launch, os.X_OK):
        errors.append(f"bin/launch is not executable: {launch}")

    if errors:
        for err in errors:
            typer.echo(f"FAIL: {err}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK preflight {slot}")


@app.command("live")
def live(
    service: str = typer.Option(
        "yoyopod-prod.service",
        "--service",
        help="systemd unit to check for activity.",
    ),
    skip_systemd: bool = typer.Option(
        False,
        "--skip-systemd",
        help="Skip systemd activity check (for tests / non-deploy callers).",
    ),
) -> None:
    """Report the running version. Exit 0 = release detected AND service active."""
    info = current_release()
    if info is None:
        typer.echo("FAIL: no release manifest resolvable", err=True)
        raise typer.Exit(code=1)

    if not skip_systemd:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            typer.echo(f"FAIL: systemctl check failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        status = result.stdout.strip()
        if status != "active":
            typer.echo(f"FAIL: {service} is {status} (not active)", err=True)
            raise typer.Exit(code=1)

    typer.echo(f"version={info.version} channel={info.channel} released_at={info.released_at}")
