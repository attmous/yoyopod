from __future__ import annotations

from types import SimpleNamespace

from yoyopod.backends.music import PlaybackQueue, Track
from yoyopod.core import AppContext
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.rust_sidecar.state import RustUiRuntimeSnapshot


class _Contact:
    def __init__(self, name: str, sip_address: str) -> None:
        self.name = name
        self.sip_address = sip_address

    @property
    def display_name(self) -> str:
        return self.name

    def preferred_call_target(self, *, gsm_enabled: bool = False) -> tuple[str | None, str]:
        return "sip", self.sip_address


class _PeopleDirectory:
    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[_Contact]:
        return [_Contact("Mama", "sip:mama@example.com")]


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
    context.power.battery_charging = True
    context.power.available = True
    context.update_voip_status(
        configured=True,
        ready=True,
        running=True,
        registration_state="ok",
    )
    app = SimpleNamespace(
        context=context,
        app_state_runtime=SimpleNamespace(get_state_name=lambda: "playing"),
        people_directory=_PeopleDirectory(),
    )

    payload = RustUiRuntimeSnapshot.from_app(app).to_payload()

    assert payload["app_state"] == "playing"
    assert payload["music"]["title"] == "Little Song"
    assert payload["music"]["artist"] == "YoYo"
    assert payload["music"]["progress_permille"] == 250
    assert payload["power"]["battery_percent"] == 42
    assert payload["power"]["charging"] is True
    assert payload["call"]["contacts"] == [
        {
            "id": "sip:mama@example.com",
            "title": "Mama",
            "subtitle": "sip:mama@example.com",
            "icon_key": "person",
        }
    ]
    assert [card["title"] for card in payload["hub"]["cards"]] == [
        "Listen",
        "Talk",
        "Ask",
        "Setup",
    ]
