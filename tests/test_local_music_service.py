"""Tests for the local-first music service and recent-track history."""

from __future__ import annotations

from pathlib import Path

from yoyopy.audio import LocalMusicService, MopidyTrack, RecentTrackHistoryStore
from yoyopy.coordinators.playback import PlaybackCoordinator


class FakePlaylist:
    def __init__(self, name: str, uri: str, track_count: int = 0) -> None:
        self.name = name
        self.uri = uri
        self.track_count = track_count


class FakeMopidyClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.loaded_playlist_uri: str | None = None
        self.loaded_track_uris: list[str] = []
        self.playlists = [
            FakePlaylist("Local Mix", "m3u:local-mix", 8),
            FakePlaylist("Cloud Mix", "spotify:cloud-mix", 99),
        ]
        self.browse_map: dict[str, list[dict[str, object]]] = {
            "file:": [
                {"uri": "file:Albums", "type": "directory", "name": "Albums"},
                {"uri": "file:///music/track-a.flac", "type": "track", "name": "Track A"},
            ],
            "file:Albums": [
                {"uri": "file:///music/track-b.flac", "type": "track", "name": "Track B"},
            ],
        }

    def get_playlists(self, fetch_track_counts: bool = False) -> list[FakePlaylist]:
        return list(self.playlists)

    def load_playlist(self, playlist_uri: str) -> bool:
        self.loaded_playlist_uri = playlist_uri
        return True

    def browse_library(self, uri: str | None = None) -> list[dict[str, object]]:
        return list(self.browse_map.get(uri or "", []))

    def load_track_uris(self, track_uris: list[str]) -> bool:
        self.loaded_track_uris = list(track_uris)
        return True


class StubRuntime:
    def __init__(self) -> None:
        self.call_fsm = type("CallFSM", (), {"is_active": False})()
        self.music_fsm = type("MusicFSM", (), {"transition": lambda self, action: None})()
        self.call_interruption_policy = type("Policy", (), {"clear": lambda self: None})()

    def sync_app_state(self, _trigger: str):
        return type("StateChange", (), {"entered": lambda self, _state: False})()


class StubScreenCoordinator:
    def __init__(self) -> None:
        self.now_playing_refreshes = 0

    def update_now_playing_if_needed(self) -> None:
        return

    def refresh_now_playing_screen(self) -> None:
        self.now_playing_refreshes += 1


def test_local_music_service_filters_playlists_and_loads_local_only() -> None:
    mopidy = FakeMopidyClient()
    service = LocalMusicService(mopidy)

    playlists = service.list_playlists(fetch_track_counts=True)

    assert [playlist.name for playlist in playlists] == ["Local Mix"]
    assert service.load_playlist("m3u:local-mix") is True
    assert mopidy.loaded_playlist_uri == "m3u:local-mix"
    assert service.load_playlist("spotify:cloud-mix") is False


def test_recent_track_history_store_deduplicates_and_persists(tmp_path: Path) -> None:
    history_file = tmp_path / "recent_tracks.json"
    store = RecentTrackHistoryStore(history_file, max_entries=3)

    first = MopidyTrack(uri="local:track:first", name="First", artists=["Artist"], album="Album")
    second = MopidyTrack(uri="file:///music/second.flac", name="Second", artists=["Artist"], album="Album")

    store.record_track(first)
    store.record_track(second)
    store.record_track(first)

    reloaded = RecentTrackHistoryStore(history_file, max_entries=3)
    assert [entry.title for entry in reloaded.list_recent()] == ["First", "Second"]


def test_local_music_service_shuffle_collects_local_tracks_and_starts_playback() -> None:
    mopidy = FakeMopidyClient()
    service = LocalMusicService(mopidy)

    assert service.shuffle_all() is True
    assert sorted(mopidy.loaded_track_uris) == [
        "file:///music/track-a.flac",
        "file:///music/track-b.flac",
    ]


def test_playback_coordinator_records_recent_local_tracks(tmp_path: Path) -> None:
    mopidy = FakeMopidyClient()
    store = RecentTrackHistoryStore(tmp_path / "recent_tracks.json")
    service = LocalMusicService(mopidy, recent_store=store)
    coordinator = PlaybackCoordinator(
        runtime=StubRuntime(),
        screen_coordinator=StubScreenCoordinator(),
        local_music_service=service,
    )

    coordinator.handle_track_change(
        MopidyTrack(
            uri="local:track:alpha",
            name="Alpha",
            artists=["Artist"],
            album="Album",
        )
    )

    assert [entry.title for entry in store.list_recent()] == ["Alpha"]
