"""Tests for music data models."""

from __future__ import annotations

import sys
from pathlib import Path

from yoyopod.app_context import AppContext
from yoyopod.audio.music.models import MusicConfig, PlaybackQueue, Playlist, Track


def test_track_get_artist_string_with_artists() -> None:
    track = Track(uri="/music/song.mp3", name="Song", artists=["Alice", "Bob"])
    assert track.get_artist_string() == "Alice, Bob"


def test_track_get_artist_string_empty() -> None:
    track = Track(uri="/music/song.mp3", name="Song", artists=[])
    assert track.get_artist_string() == "Unknown Artist"


def test_track_from_mpv_metadata_basic() -> None:
    track = Track.from_mpv_metadata(
        "/music/song.mp3",
        {"title": "My Song", "artist": "Alice", "album": "Debut", "duration": 180.5},
    )
    assert track.name == "My Song"
    assert track.artists == ["Alice"]
    assert track.album == "Debut"
    assert track.length == 180500
    assert track.uri == "/music/song.mp3"


def test_track_from_mpv_metadata_missing_fields() -> None:
    track = Track.from_mpv_metadata("/music/unknown.mp3", {})
    assert track.name == "unknown"
    assert track.artists == ["Unknown"]
    assert track.album == ""
    assert track.length == 0


def test_track_from_mpv_metadata_ignores_non_numeric_duration() -> None:
    track = Track.from_mpv_metadata(
        "/music/noisy.mp3",
        {"title": "Noisy", "artist": "Alice", "duration": "N/A"},
    )
    assert track.name == "Noisy"
    assert track.artists == ["Alice"]
    assert track.length == 0


def test_track_from_mpv_metadata_strips_file_extension_from_runtime_title() -> None:
    track = Track.from_mpv_metadata(
        "/music/OpenSampler/02-Moonlight-Sonata.ogg",
        {"title": "02-Moonlight-Sonata.ogg", "length": 123456},
    )
    assert track.name == "02-Moonlight-Sonata"


def test_track_from_mpv_metadata_falls_back_to_file_tags_for_sparse_local_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    music_file = tmp_path / "01-Fur-Elise.ogg"
    music_file.write_bytes(b"not-really-audio")

    fallback_track = Track(
        uri=str(music_file),
        name="01-Fur-Elise",
        artists=["sebion"],
        album="OpenSampler",
        length=176500,
    )

    def fake_from_file_tags(cls, path: Path) -> Track:
        assert path == music_file
        return fallback_track

    monkeypatch.setattr(Track, "from_file_tags", classmethod(fake_from_file_tags))

    track = Track.from_mpv_metadata(
        str(music_file),
        {"title": "01-Fur-Elise.ogg", "duration": 176.5},
    )

    assert track.name == "01-Fur-Elise"
    assert track.artists == ["sebion"]
    assert track.album == "OpenSampler"
    assert track.length == 176500


def test_track_from_file_tags(tmp_path: Path) -> None:
    # Create a minimal test - from_file_tags falls back to filename when tinytag fails
    fake_file = tmp_path / "test_song.mp3"
    fake_file.write_bytes(b"\x00" * 100)
    track = Track.from_file_tags(fake_file)
    assert track.uri == str(fake_file)
    assert track.name == "test_song"


def test_playlist_dataclass() -> None:
    pl = Playlist(uri="/music/chill.m3u", name="chill", track_count=5)
    assert pl.name == "chill"
    assert pl.track_count == 5


def test_playback_queue_tracks_current_selection() -> None:
    queue = PlaybackQueue(
        name="Road Trip",
        tracks=[
            Track(uri="demo://golden-hour", name="Golden Hour", artists=["Kacey Musgraves"]),
            Track(uri="demo://midnight-train", name="Midnight Train", artists=["Sam Smith"]),
        ],
    )

    assert queue.track_count == 2
    assert queue.current_track() == queue.tracks[0]
    assert queue.has_previous() is False
    assert queue.has_next() is True

    assert queue.next_track() == queue.tracks[1]
    assert queue.current_track() == queue.tracks[1]
    assert queue.has_previous() is True
    assert queue.has_next() is False

    assert queue.previous_track() == queue.tracks[0]
    assert queue.current_track() == queue.tracks[0]


def test_app_context_demo_playlist_uses_canonical_track_model() -> None:
    context = AppContext()
    playlist = context.create_demo_playlist()
    context.set_playlist(playlist)
    context.media.playback.position = 45.0

    track = context.get_current_track()

    assert isinstance(track, Track)
    assert track is not None
    assert track.name == "The Adventure Begins"
    assert track.length == 180_000
    assert context.get_playback_progress() == 0.25


def test_music_config_defaults() -> None:
    cfg = MusicConfig(music_dir=Path("/home/pi/Music"))
    expected_socket = (
        r"\\.\pipe\yoyopod-mpv" if sys.platform == "win32" else "/tmp/yoyopod-mpv.sock"
    )
    assert cfg.mpv_socket == expected_socket
    assert cfg.mpv_binary == "mpv"
    assert cfg.alsa_device == "default"
