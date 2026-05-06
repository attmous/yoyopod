"""Tests for the local-first music service and recent-track history."""

from __future__ import annotations

from pathlib import Path

import pytest

import yoyopod.integrations.music.library as library_module
from yoyopod.backends.music import MockMusicBackend, Playlist, Track
from yoyopod.integrations.music import LocalMusicService, RecentTrackHistoryStore
from yoyopod.integrations.music.history import RecentTrackEntry
from yoyopod.integrations.music.library import LocalLibraryItem
from yoyopod.integrations.music.runtime import MusicRuntime


class StubRuntime:
    def __init__(self) -> None:
        self.call_fsm = type("CallFSM", (), {"is_active": False})()
        self.music_fsm = type("MusicFSM", (), {"transition": lambda self, action: None})()
        self.call_interruption_policy = type("Policy", (), {"clear": lambda self: None})()

    def sync_app_state(self, _trigger: str):
        return type("StateChange", (), {"entered": lambda self, _state: False})()


class StubScreenManager:
    def __init__(self, route_name: str | None = None) -> None:
        self.now_playing_refreshes = 0
        self.current_screen_refreshes = 0
        self.current_screen = (
            None if route_name is None else type("Screen", (), {"route_name": route_name})()
        )

    def refresh_now_playing_screen(self) -> None:
        self.now_playing_refreshes += 1

    def refresh_current_screen(self) -> None:
        self.current_screen_refreshes += 1


class _SnapshotOwnedBackend:
    owns_library_state = True

    def __init__(
        self,
        *,
        connected: bool = True,
        library_state_ready: bool = True,
    ) -> None:
        self._connected = connected
        self.library_state_ready = library_state_ready
        self.playlists = [Playlist(uri="/music/rust.m3u", name="Rust", track_count=4)]
        self.recent_tracks = [
            RecentTrackEntry(
                uri="/music/recent.mp3",
                title="Recent",
                artist="Artist",
                album="Album",
                played_at="2026-04-30T00:00:00+00:00",
            )
        ]
        self.menu = [LocalLibraryItem(key="playlists", title="Playlists", subtitle="Saved mixes")]
        self.play_recent_calls: list[str] = []
        self.shuffle_calls = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def list_playlists(self, fetch_track_counts: bool = False) -> list[Playlist]:
        assert fetch_track_counts is True
        return list(self.playlists)

    def playlist_count(self) -> int:
        return len(self.playlists)

    def list_recent_tracks(self, limit: int | None = None) -> list[RecentTrackEntry]:
        return list(self.recent_tracks if limit is None else self.recent_tracks[:limit])

    def menu_items(self) -> list[LocalLibraryItem]:
        return list(self.menu)

    def play_recent_track(self, track_uri: str) -> bool:
        self.play_recent_calls.append(track_uri)
        return True

    def shuffle_all(self) -> bool:
        self.shuffle_calls += 1
        return True


def test_local_music_service_scans_playlists_with_track_counts_and_loads_local_only(
    tmp_path: Path,
) -> None:
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    playlist_path = music_dir / "local-mix.m3u"
    playlist_path.write_text("#EXTM3U\ntrack-a.mp3\ntrack-b.mp3\n", encoding="utf-8")

    backend = MockMusicBackend()
    backend.start()
    service = LocalMusicService(backend, music_dir=music_dir)

    playlists = service.list_playlists(fetch_track_counts=True)

    assert [playlist.name for playlist in playlists] == ["local-mix"]
    assert playlists[0].track_count == 2
    assert service.load_playlist(str(playlist_path)) is True
    assert backend.commands[-1] == f"load_playlist:{playlist_path}"
    assert service.load_playlist(str(tmp_path / "outside.m3u")) is False


def test_local_music_service_skips_playlist_track_counts_when_not_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    playlist_path = music_dir / "local-mix.m3u"
    playlist_path.write_text("#EXTM3U\ntrack-a.mp3\ntrack-b.mp3\n", encoding="utf-8")

    service = LocalMusicService(None, music_dir=music_dir)

    def _fail_read_text(self: Path, *args: object, **kwargs: object) -> str:
        raise AssertionError(f"unexpected playlist file read for {self}")

    monkeypatch.setattr(Path, "read_text", _fail_read_text)

    playlists = service.list_playlists(fetch_track_counts=False)

    assert [playlist.name for playlist in playlists] == ["local-mix"]
    assert playlists[0].track_count == 0


def test_recent_track_history_store_deduplicates_and_persists(tmp_path: Path) -> None:
    history_file = tmp_path / "recent_tracks.json"
    store = RecentTrackHistoryStore(history_file, max_entries=3)

    first = Track(uri=str(tmp_path / "first.mp3"), name="First", artists=["Artist"], album="Album")
    second = Track(uri=str(tmp_path / "second.flac"), name="Second", artists=["Artist"], album="Album")

    store.record_track(first)
    store.record_track(second)
    store.record_track(first)

    reloaded = RecentTrackHistoryStore(history_file, max_entries=3)
    assert [entry.title for entry in reloaded.list_recent()] == ["First", "Second"]


def test_local_music_service_shuffle_collects_local_tracks_and_starts_playback(tmp_path: Path) -> None:
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    (music_dir / "track-a.flac").write_bytes(b"a")
    albums_dir = music_dir / "Albums"
    albums_dir.mkdir()
    (albums_dir / "track-b.flac").write_bytes(b"b")

    backend = MockMusicBackend()
    backend.start()
    service = LocalMusicService(backend, music_dir=music_dir)

    assert service.shuffle_all() is True
    assert backend.commands[-1] == "load_tracks:2"


def test_local_music_service_collects_tracks_with_single_library_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    music_dir = tmp_path / "Music"
    albums_dir = music_dir / "Albums"
    singles_dir = music_dir / "Singles"
    albums_dir.mkdir(parents=True)
    singles_dir.mkdir()
    (albums_dir / "bravo.flac").write_bytes(b"b")
    (singles_dir / "alpha.mp3").write_bytes(b"a")
    (singles_dir / "ignore.txt").write_text("skip", encoding="utf-8")
    (music_dir / "charlie.opus").write_bytes(b"c")

    service = LocalMusicService(None, music_dir=music_dir)
    walk_calls: list[Path] = []
    original_walk = library_module.os.walk

    def _counting_walk(root: Path, *args: object, **kwargs: object):
        walk_calls.append(root)
        yield from original_walk(root, *args, **kwargs)

    monkeypatch.setattr(library_module.os, "walk", _counting_walk)

    track_uris = service._collect_local_track_uris()

    assert walk_calls == [music_dir]
    assert track_uris == [
        str(singles_dir / "alpha.mp3"),
        str(albums_dir / "bravo.flac"),
        str(music_dir / "charlie.opus"),
    ]


def test_local_music_service_delegates_library_queries_to_snapshot_owned_backend(
    tmp_path: Path,
) -> None:
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    (music_dir / "python-owned.m3u").write_text("#EXTM3U\nsong.mp3\n", encoding="utf-8")
    backend = _SnapshotOwnedBackend()
    service = LocalMusicService(backend, music_dir=music_dir)

    assert service.list_playlists(fetch_track_counts=True) == backend.playlists
    assert service.playlist_count() == 1
    assert service.list_recent_tracks() == backend.recent_tracks
    assert service.menu_items() == backend.menu


def test_local_music_service_is_available_when_snapshot_owned_backend_library_state_is_ready(
    tmp_path: Path,
) -> None:
    backend = _SnapshotOwnedBackend(connected=False, library_state_ready=True)
    service = LocalMusicService(backend, music_dir=tmp_path / "Music")

    assert service.is_available is True


def test_local_music_service_is_unavailable_until_snapshot_owned_library_state_arrives(
    tmp_path: Path,
) -> None:
    backend = _SnapshotOwnedBackend(connected=False, library_state_ready=False)
    service = LocalMusicService(backend, music_dir=tmp_path / "Music")

    assert service.is_available is False


def test_local_music_service_uses_backend_owned_recent_and_shuffle_actions(tmp_path: Path) -> None:
    backend = _SnapshotOwnedBackend()
    service = LocalMusicService(backend, music_dir=tmp_path / "Music")

    assert service.play_recent_track("/music/recent.mp3") is True
    assert backend.play_recent_calls == ["/music/recent.mp3"]
    assert service.shuffle_all() is True
    assert backend.shuffle_calls == 1


def test_local_music_service_skips_python_recent_store_when_backend_owns_library_state(
    tmp_path: Path,
) -> None:
    backend = _SnapshotOwnedBackend()
    store = RecentTrackHistoryStore(tmp_path / "recent_tracks.json")
    service = LocalMusicService(backend, music_dir=tmp_path / "Music", recent_store=store)

    service.record_recent_track(
        Track(
            uri="/music/recent.mp3",
            name="Recent",
            artists=["Artist"],
            album="Album",
        )
    )

    assert store.list_recent() == []


def test_music_runtime_records_recent_local_tracks(tmp_path: Path) -> None:
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track_path = music_dir / "alpha.mp3"
    track_path.write_bytes(b"a")

    backend = MockMusicBackend()
    backend.start()
    store = RecentTrackHistoryStore(tmp_path / "recent_tracks.json")
    service = LocalMusicService(backend, music_dir=music_dir, recent_store=store)
    runtime_owner = MusicRuntime(
        runtime=StubRuntime(),
        screen_manager=StubScreenManager(),
        local_music_service=service,
    )

    runtime_owner.handle_track_change(
        Track(
            uri=str(track_path),
            name="Alpha",
            artists=["Artist"],
            album="Album",
        )
    )

    assert [entry.title for entry in store.list_recent()] == ["Alpha"]


def test_music_runtime_refreshes_visible_playlist_screen_on_availability_change() -> None:
    runtime_owner = MusicRuntime(
        runtime=StubRuntime(),
        screen_manager=StubScreenManager(route_name="playlists"),
        local_music_service=None,
    )

    runtime_owner.handle_availability_change(True, "connected")

    screen_manager = runtime_owner.screen_manager
    assert screen_manager is not None
    assert screen_manager.current_screen_refreshes == 1
    assert screen_manager.now_playing_refreshes == 0
