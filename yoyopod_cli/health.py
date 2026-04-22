"""yoyopod health {preflight,live} — offline + online health probes.

preflight: given a slot directory (not yet active), validate that it is
structurally sound enough to become current. Runs BEFORE the symlink flip.
Checks performed:
  * manifest.json exists and parses
  * venv/ exists (even if empty, the dir must be there)
  * app/ exists
  * bin/launch exists and is executable

live: reads YOYOPOD_RELEASE_MANIFEST (via yoyopod.core.release.current_release)
and prints the running version. Used as a readiness probe after the flip.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from yoyopod.core.release import current_release
from yoyopod_cli.release_manifest import load_manifest

app = typer.Typer(name="health", help="Slot-deploy health probes.")


@app.command("preflight")
def preflight(
    slot: Path = typer.Option(..., help="Path to the release slot dir (before flip)."),
) -> None:
    """Offline structural check of a release slot. Exit 0 = OK."""
    errors: list[str] = []

    manifest_path = slot / "manifest.json"
    if not manifest_path.exists():
        errors.append(f"manifest.json missing at {manifest_path}")
    else:
        try:
            load_manifest(manifest_path)
        except ValueError as exc:
            errors.append(f"manifest.json invalid: {exc}")

    for required in ("venv", "app"):
        if not (slot / required).is_dir():
            errors.append(f"{required}/ missing in {slot}")

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
def live() -> None:
    """Report the running version from the release manifest. Exit 0 = release detected."""
    info = current_release()
    if info is None:
        typer.echo("FAIL: no release manifest resolvable", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"version={info.version} channel={info.channel} released_at={info.released_at}")
