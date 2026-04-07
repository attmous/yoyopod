"""Focused tests for Mopidy client local playback behavior."""

from __future__ import annotations

from yoyopy.audio.mopidy_client import MopidyClient


class StubMopidyClient(MopidyClient):
    """RPC-free Mopidy client stub for unit tests."""

    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__(host="localhost", port=6680)
        self._responses = responses

    def _rpc_call(self, method: str, params=None):  # type: ignore[override]
        return self._responses.get(method)


def test_get_current_track_falls_back_to_tracklist_when_current_tl_track_is_missing() -> None:
    """Queued local playback should still surface the first active track during handoff."""

    client = StubMopidyClient(
        {
            "core.playback.get_current_tl_track": None,
            "core.tracklist.index": 1,
            "core.tracklist.get_tl_tracks": [
                {
                    "track": {
                        "uri": "file:///music/intro.ogg",
                        "name": "Intro.ogg",
                        "artists": [],
                    }
                },
                {
                    "track": {
                        "uri": "file:///music/main-theme.ogg",
                        "name": "Main Theme.ogg",
                        "artists": [{"name": "Open Orchestra"}],
                        "length": 123000,
                    }
                },
            ],
        }
    )

    track = client.get_current_track()

    assert track is not None
    assert track.uri == "file:///music/main-theme.ogg"
    assert track.name == "Main Theme.ogg"
    assert track.get_artist_string() == "Open Orchestra"


def test_get_current_track_skips_null_tracklist_entries() -> None:
    """Sparse tracklists from Mopidy should still yield the first valid track."""

    client = StubMopidyClient(
        {
            "core.playback.get_current_tl_track": None,
            "core.tracklist.index": 0,
            "core.tracklist.get_tl_tracks": [
                None,
                {
                    "track": {
                        "uri": "file:///music/recovered.ogg",
                        "name": "Recovered.ogg",
                        "artists": [{"name": "Sampler"}],
                    }
                },
            ],
        }
    )

    track = client.get_current_track()

    assert track is not None
    assert track.uri == "file:///music/recovered.ogg"
    assert track.get_artist_string() == "Sampler"


def test_get_current_track_ignores_null_track_payload_before_falling_back() -> None:
    """A null current_tl_track payload should not raise or mask a valid fallback track."""

    client = StubMopidyClient(
        {
            "core.playback.get_current_tl_track": {"track": None},
            "core.tracklist.index": 0,
            "core.tracklist.get_tl_tracks": [
                {
                    "track": {
                        "uri": "file:///music/fallback.ogg",
                        "name": "Fallback.ogg",
                        "artists": [],
                    }
                }
            ],
        }
    )

    track = client.get_current_track()

    assert track is not None
    assert track.uri == "file:///music/fallback.ogg"


def test_get_current_track_uses_cached_track_when_rpc_and_tracklist_are_empty() -> None:
    """A previously known track should survive one empty RPC cycle."""

    client = StubMopidyClient(
        {
            "core.playback.get_current_tl_track": None,
            "core.tracklist.index": None,
            "core.tracklist.get_tl_tracks": [],
        }
    )
    client.current_track = type(
        "Track",
        (),
        {
            "uri": "file:///music/cached.ogg",
            "name": "Cached.ogg",
            "get_artist_string": lambda self: "Unknown Artist",
        },
    )()

    track = client.get_current_track()

    assert track is client.current_track
