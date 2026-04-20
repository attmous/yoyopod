"""Music smoke checks."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from .types import CheckResult

if TYPE_CHECKING:
    from yoyopod.cli.pi.music_fixtures import ProvisionedTestMusicLibrary
    from yoyopod.config import MediaConfig


def _prepare_music_validation_library(
    media_settings: "MediaConfig",
    *,
    provision_test_music: bool,
    test_music_dir: str,
) -> "ProvisionedTestMusicLibrary | None":
    """Provision the deterministic validation music library and point smoke at it."""
    from yoyopod.cli.pi.music_fixtures import provision_test_music_library

    if not provision_test_music:
        return None

    library = provision_test_music_library(Path(test_music_dir))
    media_settings.music.music_dir = str(library.target_dir)
    return library


def _music_check(
    media_settings: "MediaConfig",
    timeout_seconds: int,
    *,
    expected_library: "ProvisionedTestMusicLibrary | None" = None,
) -> CheckResult:
    """Validate music-backend startup and basic state queries."""
    from yoyopod.audio import LocalMusicService, MpvBackend, MusicConfig

    config = MusicConfig.from_media_settings(media_settings)
    backend = MpvBackend(config)
    try:
        started_at = time.monotonic()
        if not backend.start():
            return CheckResult(
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
            return CheckResult(
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
                return CheckResult(
                    name="music",
                    status="fail",
                    details=f"missing provisioned test assets: {missing_list}",
                )

            music_service = LocalMusicService(backend, music_dir=expected_library.target_dir)
            playlist_path = expected_library.default_playlist_path
            playlists = music_service.list_playlists()
            if str(playlist_path) not in {playlist.uri for playlist in playlists}:
                return CheckResult(
                    name="music",
                    status="fail",
                    details=f"provisioned playlist not discoverable under {expected_library.target_dir}",
                )

            if not music_service.load_playlist(str(playlist_path)):
                return CheckResult(
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
                return CheckResult(
                    name="music",
                    status="fail",
                    details=(
                        "music backend started, but it did not load one of the "
                        f"provisioned validation tracks from {expected_library.target_dir}; "
                        f"current_track={current_uri}"
                    ),
                )

            playback_state = backend.get_playback_state()
            return CheckResult(
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

        return CheckResult(
            name="music",
            status="pass",
            details=(
                f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                f"state={playback_state}, track={track_name}"
            ),
        )
    except Exception as exc:
        return CheckResult(name="music", status="fail", details=str(exc))
    finally:
        backend.stop()
