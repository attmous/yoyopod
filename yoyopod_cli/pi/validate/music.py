"""Music validation subcommand."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Annotated

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir
from yoyopod_cli.pi.validate._common import (
    _CheckResult,
    _load_media_config,
    _print_summary,
)

if TYPE_CHECKING:
    from yoyopod_cli.config import MediaConfig
    from yoyopod_cli.music_fixtures import ProvisionedTestMusicLibrary


def _music_check(
    media_settings: MediaConfig,
    timeout_seconds: int,
    *,
    expected_library: ProvisionedTestMusicLibrary | None = None,
) -> _CheckResult:
    """Validate music-backend startup and basic state queries."""
    from yoyopod.backends.music import MpvBackend, MusicConfig
    from yoyopod.integrations.music import LocalMusicService

    config = MusicConfig.from_media_settings(media_settings)
    backend = MpvBackend(config)
    try:
        started_at = time.monotonic()
        if not backend.start():
            return _CheckResult(
                name="music",
                status="fail",
                details=(
                    "could not start the mpv music backend "
                    f"(binary={config.mpv_binary}, socket={config.mpv_socket})"
                ),
            )

        while not backend.is_connected and (time.monotonic() - started_at) < timeout_seconds:
            time.sleep(0.1)

        if not backend.is_connected:
            return _CheckResult(
                name="music",
                status="fail",
                details=f"music backend did not report ready within {timeout_seconds}s",
            )

        if expected_library is not None:
            missing_assets = [
                path for path in expected_library.expected_asset_paths if not path.exists()
            ]
            if missing_assets:
                missing_list = ", ".join(str(path) for path in missing_assets)
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"missing provisioned test assets: {missing_list}",
                )

            music_service = LocalMusicService(backend, music_dir=expected_library.target_dir)
            playlist_path = expected_library.default_playlist_path
            playlists = music_service.list_playlists()
            if str(playlist_path) not in {playlist.uri for playlist in playlists}:
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"provisioned playlist not discoverable under {expected_library.target_dir}",
                )

            if not music_service.load_playlist(str(playlist_path)):
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=f"mpv could not load the provisioned playlist {playlist_path}",
                )

            expected_track_uris = {str(path) for path in expected_library.track_paths}
            loaded_track = None
            while (time.monotonic() - started_at) < timeout_seconds:
                loaded_track = backend.get_current_track()
                if loaded_track is not None and loaded_track.uri in expected_track_uris:
                    break
                time.sleep(0.1)

            if loaded_track is None or loaded_track.uri not in expected_track_uris:
                current_uri = loaded_track.uri if loaded_track is not None else "none"
                return _CheckResult(
                    name="music",
                    status="fail",
                    details=(
                        "music backend started, but it did not load one of the "
                        f"provisioned validation tracks from {expected_library.target_dir}; "
                        f"current_track={current_uri}"
                    ),
                )

            playback_state = backend.get_playback_state()
            return _CheckResult(
                name="music",
                status="pass",
                details=(
                    f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                    f"music_dir={expected_library.target_dir}, "
                    f"playlist={playlist_path.name}, state={playback_state}, "
                    f"track={loaded_track.name}"
                ),
            )

        playback_state = backend.get_playback_state()
        track = backend.get_current_track()
        track_name = track.name if track else "none"

        return _CheckResult(
            name="music",
            status="pass",
            details=(
                f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                f"state={playback_state}, track={track_name}"
            ),
        )
    except Exception as exc:
        return _CheckResult(name="music", status="fail", details=str(exc))
    finally:
        backend.stop()


def music(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    timeout: Annotated[
        int, typer.Option("--timeout", help="Startup timeout in seconds for the music backend.")
    ] = 5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate the mpv music backend on the target without starting the full app."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target music validation")

    media_config = _load_media_config(config_path)
    results = [_music_check(media_config, timeout)]

    _print_summary("music", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
