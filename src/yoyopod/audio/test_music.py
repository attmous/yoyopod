"""Deterministic test-music library provisioning for Pi-side validation."""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEST_MUSIC_TARGET_DIR = "~/YoyoPod_Test_Music"
TEST_MUSIC_MANIFEST_FILENAME = ".yoyopod_test_music_manifest.json"
TEST_MUSIC_LIBRARY_VERSION = 1


@dataclass(frozen=True, slots=True)
class TestToneSpec:
    """One generated WAV track for playback validation."""

    relative_path: str
    title: str
    frequency_hz: float
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class TestPlaylistSpec:
    """One generated M3U playlist for playback validation."""

    relative_path: str
    title: str
    tracks: tuple[TestToneSpec, ...]


@dataclass(frozen=True, slots=True)
class ProvisionedTestMusicLibrary:
    """Concrete target paths for one provisioned validation library."""

    target_dir: Path
    track_paths: tuple[Path, ...]
    playlist_paths: tuple[Path, ...]
    manifest_path: Path

    @property
    def default_playlist_path(self) -> Path:
        """Return the primary validation playlist."""

        return self.playlist_paths[0]

    @property
    def expected_asset_paths(self) -> tuple[Path, ...]:
        """Return the managed files that should exist after provisioning."""

        return (*self.track_paths, *self.playlist_paths, self.manifest_path)


TEST_TONE_SPECS: tuple[TestToneSpec, ...] = (
    TestToneSpec(
        relative_path="tracks/alpha-beacon.wav",
        title="Alpha Beacon",
        frequency_hz=440.0,
        duration_seconds=1.10,
    ),
    TestToneSpec(
        relative_path="tracks/bravo-lantern.wav",
        title="Bravo Lantern",
        frequency_hz=554.37,
        duration_seconds=1.25,
    ),
    TestToneSpec(
        relative_path="tracks/charlie-sundial.wav",
        title="Charlie Sundial",
        frequency_hz=659.25,
        duration_seconds=0.95,
    ),
)

TEST_PLAYLIST_SPECS: tuple[TestPlaylistSpec, ...] = (
    TestPlaylistSpec(
        relative_path="yoyopod-validation-set.m3u",
        title="YoyoPod Validation Set",
        tracks=TEST_TONE_SPECS,
    ),
)


def expected_test_music_relative_paths() -> tuple[str, ...]:
    """Return the tracked asset set for the validation library."""

    return tuple(
        [*(spec.relative_path for spec in TEST_TONE_SPECS), *(spec.relative_path for spec in TEST_PLAYLIST_SPECS)]
    )


def provision_test_music_library(target_dir: Path) -> ProvisionedTestMusicLibrary:
    """Provision the known-good validation music set into one dedicated directory."""

    resolved_target_dir = target_dir.expanduser().resolve()
    resolved_target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = resolved_target_dir / TEST_MUSIC_MANIFEST_FILENAME
    _remove_previously_managed_assets(resolved_target_dir, manifest_path)

    track_paths = tuple(
        _write_tone_track(resolved_target_dir, spec)
        for spec in TEST_TONE_SPECS
    )
    playlist_paths = tuple(
        _write_playlist(resolved_target_dir, spec)
        for spec in TEST_PLAYLIST_SPECS
    )

    manifest_payload = {
        "version": TEST_MUSIC_LIBRARY_VERSION,
        "target_dir": str(resolved_target_dir),
        "managed_paths": list(expected_test_music_relative_paths()),
        "tracks": [
            {
                "path": spec.relative_path,
                "title": spec.title,
                "frequency_hz": spec.frequency_hz,
                "duration_seconds": spec.duration_seconds,
            }
            for spec in TEST_TONE_SPECS
        ],
        "playlists": [
            {
                "path": spec.relative_path,
                "title": spec.title,
                "tracks": [track.relative_path for track in spec.tracks],
            }
            for spec in TEST_PLAYLIST_SPECS
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return ProvisionedTestMusicLibrary(
        target_dir=resolved_target_dir,
        track_paths=track_paths,
        playlist_paths=playlist_paths,
        manifest_path=manifest_path,
    )


def _write_tone_track(target_dir: Path, spec: TestToneSpec) -> Path:
    """Write one deterministic mono PCM WAV test tone."""

    path = _resolve_relative_asset_path(target_dir, spec.relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 22050
    amplitude = 12000
    frame_count = int(sample_rate * spec.duration_seconds)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)

        frames = bytearray()
        for index in range(frame_count):
            attack = min(1.0, index / max(1, sample_rate // 50))
            release = min(1.0, (frame_count - index) / max(1, sample_rate // 20))
            envelope = min(attack, release)
            sample = int(
                amplitude
                * envelope
                * math.sin((2.0 * math.pi * spec.frequency_hz * index) / sample_rate)
            )
            frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
        handle.writeframes(bytes(frames))

    return path


def _write_playlist(target_dir: Path, spec: TestPlaylistSpec) -> Path:
    """Write one deterministic M3U playlist that references the generated tracks."""

    path = _resolve_relative_asset_path(target_dir, spec.relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["#EXTM3U"]
    for track in spec.tracks:
        track_path = _resolve_relative_asset_path(target_dir, track.relative_path)
        lines.append(f"#EXTINF:{round(track.duration_seconds)}, {track.title}")
        lines.append(str(track_path.relative_to(path.parent)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _remove_previously_managed_assets(target_dir: Path, manifest_path: Path) -> None:
    """Delete only the previously managed validation assets for repeatable reprovisioning."""

    managed_paths = _load_managed_paths_from_manifest(manifest_path)
    for relative_path in managed_paths:
        asset_path = _resolve_relative_asset_path(target_dir, relative_path)
        if asset_path.is_file() or asset_path.is_symlink():
            asset_path.unlink()

    if manifest_path.exists():
        manifest_path.unlink()

    for current_path in sorted(target_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if current_path.is_dir():
            try:
                current_path.rmdir()
            except OSError:
                continue


def _load_managed_paths_from_manifest(manifest_path: Path) -> tuple[str, ...]:
    """Load the previous managed relative-path list when a manifest exists."""

    if not manifest_path.exists():
        return ()

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()

    raw_paths = payload.get("managed_paths", [])
    if not isinstance(raw_paths, list):
        return ()

    managed_paths: list[str] = []
    for candidate in raw_paths:
        text = str(candidate).strip()
        if text:
            managed_paths.append(text)
    return tuple(managed_paths)


def _resolve_relative_asset_path(target_dir: Path, relative_path: str) -> Path:
    """Resolve one managed asset path and reject unsafe values."""

    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe test-music asset path: {relative_path}")
    return target_dir / relative
