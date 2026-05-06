from __future__ import annotations

from types import SimpleNamespace

from yoyopod.backends.music import PlaybackQueue, Track
from yoyopod.core import AppContext
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot


def test_runtime_snapshot_serializes_current_app_context() -> None:
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.set_playlist(
        PlaybackQueue(
            name="Tiny Mix",
            source_uri="m3u:tiny",
            tracks=[
                Track(
                    uri="/music/little-song.mp3",
                    name="Little Song",
                    artists=["YoYo"],
                    length=120_000,
                )
            ],
        )
    )
    assert context.play()
    context.media.playback.position = 30.0
    context.power.update_battery_percent(42)
    app = SimpleNamespace(
        context=context,
        app_state_runtime=SimpleNamespace(get_state_name=lambda: "playing"),
        people_directory=None,
    )

    payload = RustUiRuntimeSnapshot.from_app(app).to_payload()

    assert payload["app_state"] == "playing"
    assert payload["music"]["title"] == "Little Song"
    assert payload["music"]["artist"] == "YoYo"
    assert payload["music"]["progress_permille"] == 250
    assert payload["power"]["battery_percent"] == 42
    assert [card["title"] for card in payload["hub"]["cards"]] == [
        "Listen",
        "Talk",
        "Ask",
        "Setup",
    ]


def test_runtime_snapshot_includes_recent_tracks_and_call_history() -> None:
    voip_manager = SimpleNamespace(
        call_history_recent_entries=lambda: [
            SimpleNamespace(
                sip_address="sip:mama@example.com",
                title="Mama",
                subtitle="Missed call",
                outcome="missed",
            )
        ]
    )
    app = SimpleNamespace(
        context=None,
        app_state_runtime=None,
        people_directory=None,
        voip_manager=voip_manager,
        get_music_library=lambda: SimpleNamespace(
            list_recent_tracks=lambda: [
                SimpleNamespace(
                    uri="file:///music/little-song.mp3",
                    title="Little Song",
                    subtitle="YoYo",
                )
            ]
        ),
    )

    payload = RustUiRuntimeSnapshot.from_app(app).to_payload()

    assert payload["music"]["recent_tracks"] == [
        {
            "id": "file:///music/little-song.mp3",
            "title": "Little Song",
            "subtitle": "YoYo",
            "icon_key": "track",
        }
    ]
    assert payload["call"]["history"] == [
        {
            "id": "sip:mama@example.com",
            "title": "Mama",
            "subtitle": "Missed call",
            "icon_key": "missed_call",
        }
    ]
