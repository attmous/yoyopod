"""Focused tests for the LVGL-backed playlist screen delegation."""

from __future__ import annotations

from yoyopy.app_context import AppContext
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import PlaylistScreen


class FakeLvglBinding:
    """Small native-binding double for playlist view tests."""

    def __init__(self) -> None:
        self.playlist_build_calls = 0
        self.playlist_destroy_calls = 0
        self.playlist_sync_payloads: list[dict] = []

    def playlist_build(self) -> None:
        self.playlist_build_calls += 1

    def playlist_sync(self, **payload) -> None:
        self.playlist_sync_payloads.append(payload)

    def playlist_destroy(self) -> None:
        self.playlist_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True


class FakeLvglDisplay:
    """Tiny Display double for LVGL playlist delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend

    def is_portrait(self) -> bool:
        return True


class FakePlaylist:
    """Minimal playlist record with track count metadata."""

    def __init__(self, name: str, uri: str, track_count: int = 0) -> None:
        self.name = name
        self.uri = uri
        self.track_count = track_count


class FakeMopidyClient:
    """Minimal Mopidy client for playlist view tests."""

    def __init__(self, playlists: list[FakePlaylist], *, is_connected: bool = True) -> None:
        self.playlists = playlists
        self.is_connected = is_connected

    def get_playlists(self, fetch_track_counts: bool = True) -> list[FakePlaylist]:
        return list(self.playlists)


def test_playlist_screen_builds_syncs_and_destroys_lvgl_view() -> None:
    """PlaylistScreen should delegate lifecycle and visible-window state to LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.battery_percent = 61
    context.battery_charging = False
    context.power_available = True
    context.current_audio_source = "spotify"

    mopidy = FakeMopidyClient(
        [
            FakePlaylist("Alpha", "playlist:alpha", 12),
            FakePlaylist("Beta", "playlist:beta", 4),
            FakePlaylist("Gamma", "playlist:gamma", 0),
            FakePlaylist("Delta", "playlist:delta", 9),
        ]
    )
    screen = PlaylistScreen(display, context, mopidy_client=mopidy)

    screen.enter()

    assert binding.playlist_build_calls == 1
    assert len(binding.playlist_sync_payloads) >= 2

    final_payload = binding.playlist_sync_payloads[-1]
    assert final_payload["title_text"] == "Spotify"
    assert final_payload["page_text"] is None
    assert final_payload["items"] == ["Alpha", "Beta", "Gamma"]
    assert final_payload["badges"] == ["12", "4", ""]
    assert final_payload["selected_visible_index"] == 0
    assert final_payload["voip_state"] == 1
    assert final_payload["battery_percent"] == 61

    screen.selected_index = 3
    screen.render()

    scrolled_payload = binding.playlist_sync_payloads[-1]
    assert scrolled_payload["page_text"] is None
    assert scrolled_payload["items"] == ["Beta", "Gamma", "Delta"]
    assert scrolled_payload["badges"] == ["4", "", "9"]
    assert scrolled_payload["selected_visible_index"] == 2

    screen.exit()
    assert binding.playlist_destroy_calls == 1


def test_playlist_screen_syncs_error_state_through_lvgl() -> None:
    """PlaylistScreen should send the music-offline empty state through LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    screen = PlaylistScreen(
        display,
        context,
        mopidy_client=FakeMopidyClient([], is_connected=False),
    )

    screen.enter()
    screen.render()

    payload = binding.playlist_sync_payloads[-1]
    assert payload["items"] == []
    assert payload["page_text"] is None
    assert payload["empty_title"] == "Music hiccup"
    assert payload["empty_subtitle"] == "Music offline"
