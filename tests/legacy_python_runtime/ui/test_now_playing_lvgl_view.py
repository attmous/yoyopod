"""Focused tests for the LVGL-backed now-playing screen delegation."""

from __future__ import annotations

from yoyopod.core import AppContext
from yoyopod.backends.music import MockMusicBackend, Track
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens.music.now_playing import (
    NowPlayingSnapshot,
    NowPlayingScreen,
    build_now_playing_actions,
    build_now_playing_state_provider,
)


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


def _snapshot_provider(backend: MockMusicBackend):
    def provider() -> NowPlayingSnapshot:
        return NowPlayingSnapshot(
            is_connected=backend.is_connected,
            track=backend.get_current_track(),
            playback_state=backend.get_playback_state(),
            time_position=float(backend.get_time_position()),
        )

    return provider


def _toggle_playback_action(backend: MockMusicBackend):
    def action() -> None:
        if backend.get_playback_state() == "playing":
            backend.pause()
        else:
            backend.play()

    return action


def test_now_playing_screen_reuses_retained_lvgl_view_across_exit_and_reentry() -> None:
    """NowPlayingScreen should retain its LVGL view across transitions."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.power.battery_percent = 84
    context.power.battery_charging = True
    context.power.available = True

    backend = MockMusicBackend()
    backend.start()
    backend.current_track = Track(
        uri="/music/adventure-song.mp3",
        name="Adventure Song",
        artists=["Kid Band"],
        length=200000,
    )
    backend.time_position = 50000
    backend.play()
    screen = NowPlayingScreen(
        display,
        context,
        state_provider=build_now_playing_state_provider(
            context=context,
            snapshot_provider=_snapshot_provider(backend),
        ),
        actions=build_now_playing_actions(
            context=context,
            toggle_playback_action=_toggle_playback_action(backend),
            previous_track_action=backend.previous_track,
            next_track_action=backend.next_track,
        ),
    )

    screen.enter()
    screen.render()

    assert binding.now_playing_build_calls == 1
    assert len(binding.now_playing_sync_payloads) == 1
    payload = binding.now_playing_sync_payloads[-1]
    assert payload["title_text"] == "Adventure Song"
    assert payload["artist_text"] == "Kid Band"
    assert payload["state_text"] == "Playing"
    assert payload["footer"] == "Tap skip / Double pause"
    assert payload["progress_permille"] == 250
    assert payload["voip_state"] == 1
    assert payload["battery_percent"] == 84
    assert payload["charging"] is True
    assert payload["power_available"] is True

    screen.exit()
    assert binding.now_playing_destroy_calls == 0

    screen.enter()
    screen.render()

    assert binding.now_playing_build_calls == 1
    assert len(binding.now_playing_sync_payloads) == 2


def test_now_playing_screen_syncs_offline_state_through_lvgl() -> None:
    """NowPlayingScreen should send the music-offline state through LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    backend = MockMusicBackend()
    screen = NowPlayingScreen(
        display,
        context,
        state_provider=build_now_playing_state_provider(
            context=context,
            snapshot_provider=_snapshot_provider(backend),
        ),
        actions=build_now_playing_actions(
            context=context,
            toggle_playback_action=_toggle_playback_action(backend),
            previous_track_action=backend.previous_track,
            next_track_action=backend.next_track,
        ),
    )

    screen.enter()
    screen.render()

    payload = binding.now_playing_sync_payloads[-1]
    assert payload["title_text"] == "Music Offline"
    assert payload["artist_text"] == "Trying to reconnect"
    assert payload["state_text"] == "Offline"
    assert payload["footer"] == "Hold back"
    assert payload["progress_permille"] == 0


def test_now_playing_screen_syncs_paused_state_through_lvgl() -> None:
    """NowPlayingScreen should expose the paused state through LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)

    backend = MockMusicBackend()
    backend.start()
    backend.current_track = Track(
        uri="/music/golden-hour.mp3",
        name="Golden Hour",
        artists=["Kacey Musgraves"],
        length=214000,
    )
    backend.time_position = 74000
    backend.pause()

    screen = NowPlayingScreen(
        display,
        context,
        state_provider=build_now_playing_state_provider(
            context=context,
            snapshot_provider=_snapshot_provider(backend),
        ),
        actions=build_now_playing_actions(
            context=context,
            toggle_playback_action=_toggle_playback_action(backend),
            previous_track_action=backend.previous_track,
            next_track_action=backend.next_track,
        ),
    )

    screen.enter()
    screen.render()

    payload = binding.now_playing_sync_payloads[-1]
    assert payload["title_text"] == "Golden Hour"
    assert payload["artist_text"] == "Kacey Musgraves"
    assert payload["state_text"] == "Paused"
    assert payload["footer"] == "Tap skip / Double play"
    assert payload["progress_permille"] == 345
