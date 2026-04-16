"""On-device helpers for deterministic test-music provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from yoyopod.audio.test_music import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    provision_test_music_library,
)
from yoyopod.cli.common import configure_logging

music_app = typer.Typer(
    name="music",
    help="Commands for deterministic local-music validation assets on the Pi.",
    no_args_is_help=True,
)


@music_app.command("provision-test-library")
def provision_test_library(
    target_dir: Annotated[
        str,
        typer.Option(
            "--target-dir",
            help="Dedicated target directory for validation-only test music.",
        ),
    ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable DEBUG logging for provisioning."),
    ] = False,
) -> None:
    """Generate the known-good validation music library into one dedicated target path."""

    configure_logging(verbose)
    library = provision_test_music_library(Path(target_dir))

    print("Provisioned YoyoPod validation music")
    print(f"target_dir: {library.target_dir}")
    print(f"playlist: {library.default_playlist_path}")
    for track_path in library.track_paths:
        print(f"track: {track_path}")
    print(f"manifest: {library.manifest_path}")
