"""Focused tests for the LVGL-backed now-playing screen delegation."""

from __future__ import annotations

from yoyopy.app_context import AppContext
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import NowPlayingScreen


class FakeLvglBinding:
    """Small native-binding double for now-playing view tests."""

    def __init__(self) -> None:
        self.now_playing_build_calls = 0
        self.now_playing_destroy_calls = 0
        self.now_playing_sync_payloads: list[dict] = []

    def now_playing_build(self) -> None:
        self.now_playing_build_calls += 1

    def now_playing_sync(self, **payload) -> None:
        self.now_playing_sync_payloads.append(payload)

    def now_playing_destroy(self) -> None:
        self.now_playing_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True


class FakeLvglDisplay:
    """Tiny Display double for LVGL now-playing delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend


class FakeTrack:
    """Minimal Mopidy track used by the now-playing tests."""

    def __init__(self, name: str, artist: str, length: int) -> None:
        self.name = name
        self._artist = artist
        self.length = length

    def get_artist_string(self) -> str:
        return self._artist


class FakeMopidyClient:
    """Minimal Mopidy client for now-playing view tests."""

    def __init__(
        self,
        track: FakeTrack | None,
        *,
        playback_state: str = "playing",
        position: int = 0,
        is_connected: bool = True,
    ) -> None:
        self.track = track
        self.playback_state = playback_state
        self.position = position
        self.is_connected = is_connected

    def get_current_track(self) -> FakeTrack | None:
        return self.track

    def get_playback_state(self) -> str:
        return self.playback_state

    def get_time_position(self) -> int:
        return self.position


def test_now_playing_screen_builds_syncs_and_destroys_lvgl_view() -> None:
    """NowPlayingScreen should delegate lifecycle and playback state to LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.battery_percent = 84
    context.battery_charging = True
    context.power_available = True

    mopidy = FakeMopidyClient(
        FakeTrack("Adventure Song", "Kid Band", 200000),
        playback_state="playing",
        position=50000,
    )
    screen = NowPlayingScreen(display, context, mopidy_client=mopidy)

    screen.enter()
    screen.render()

    assert binding.now_playing_build_calls == 1
    assert len(binding.now_playing_sync_payloads) == 1
    payload = binding.now_playing_sync_payloads[-1]
    assert payload["title_text"] == "Adventure Song"
    assert payload["artist_text"] == "Kid Band"
    assert payload["state_text"] == "PLAYING"
    assert payload["progress_permille"] == 250
    assert payload["voip_state"] == 1
    assert payload["battery_percent"] == 84
    assert payload["charging"] is True
    assert payload["power_available"] is True

    screen.exit()
    assert binding.now_playing_destroy_calls == 1


def test_now_playing_screen_syncs_offline_state_through_lvgl() -> None:
    """NowPlayingScreen should send the music-offline state through LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    screen = NowPlayingScreen(
        display,
        context,
        mopidy_client=FakeMopidyClient(None, is_connected=False),
    )

    screen.enter()
    screen.render()

    payload = binding.now_playing_sync_payloads[-1]
    assert payload["title_text"] == "Music Offline"
    assert payload["artist_text"] == "Trying to reconnect"
    assert payload["state_text"] == "OFFLINE"
    assert payload["progress_permille"] == 0
