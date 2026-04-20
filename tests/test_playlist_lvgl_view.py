"""Focused tests for the LVGL-backed playlist screen delegation."""

from __future__ import annotations

from pathlib import Path

from yoyopod.app_context import AppContext
from yoyopod.audio import LocalMusicService, MockMusicBackend
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens import PlaylistScreen


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
        self.scene_generation = 0

    def reset(self) -> None:
        self.scene_generation += 1


class FakeLvglDisplay:
    """Tiny Display double for LVGL playlist delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend

    def is_portrait(self) -> bool:
        return True


def _write_playlist(path: Path, track_count: int) -> None:
    lines = ["#EXTM3U", *[f"track-{index}.mp3" for index in range(track_count)]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_playlist_screen_reuses_retained_lvgl_view_across_exit_and_reentry(tmp_path: Path) -> None:
    """PlaylistScreen should retain its LVGL view across transitions."""

    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    _write_playlist(music_dir / "Alpha.m3u", 12)
    _write_playlist(music_dir / "Beta.m3u", 4)
    _write_playlist(music_dir / "Gamma.m3u", 0)
    _write_playlist(music_dir / "Delta.m3u", 9)

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.power.battery_percent = 61
    context.power.battery_charging = False
    context.power.available = True

    backend = MockMusicBackend()
    backend.start()
    screen = PlaylistScreen(
        display,
        context,
        music_service=LocalMusicService(backend, music_dir=music_dir),
    )

    screen.enter()

    assert binding.playlist_build_calls == 1
    assert len(binding.playlist_sync_payloads) >= 2

    final_payload = binding.playlist_sync_payloads[-1]
    assert final_payload["title_text"] == "Playlists"
    assert final_payload["page_text"] is None
    assert final_payload["items"] == ["Alpha", "Beta", "Delta"]
    assert final_payload["badges"] == ["12", "4", "9"]
    assert final_payload["selected_visible_index"] == 0
    assert final_payload["voip_state"] == 1
    assert final_payload["battery_percent"] == 61

    screen.selected_index = 3
    screen.render()

    scrolled_payload = binding.playlist_sync_payloads[-1]
    assert scrolled_payload["page_text"] is None
    assert scrolled_payload["items"] == ["Beta", "Delta", "Gamma"]
    assert scrolled_payload["badges"] == ["4", "9", ""]
    assert scrolled_payload["selected_visible_index"] == 2

    screen.exit()
    assert binding.playlist_destroy_calls == 0

    screen.enter()

    assert binding.playlist_build_calls == 1
    assert len(binding.playlist_sync_payloads) >= 4


def test_playlist_screen_rebuilds_retained_lvgl_view_after_backend_reset(tmp_path: Path) -> None:
    """PlaylistScreen should rebuild after a backend clear releases the native scene."""

    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    _write_playlist(music_dir / "Alpha.m3u", 12)

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    backend = MockMusicBackend()
    backend.start()
    screen = PlaylistScreen(
        display,
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        music_service=LocalMusicService(backend, music_dir=music_dir),
    )

    screen.enter()

    assert binding.playlist_build_calls == 1
    first_view = screen._lvgl_view

    display.get_ui_backend().reset()
    screen.enter()

    assert screen._lvgl_view is not first_view
    assert binding.playlist_build_calls == 2


def test_playlist_view_sync_rebuilds_same_retained_instance_after_backend_reset(
    tmp_path: Path,
) -> None:
    """A built retained playlist view should self-rebuild on sync after backend reset."""

    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    _write_playlist(music_dir / "Alpha.m3u", 12)

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    backend = MockMusicBackend()
    backend.start()
    screen = PlaylistScreen(
        display,
        AppContext(interaction_profile=InteractionProfile.ONE_BUTTON),
        music_service=LocalMusicService(backend, music_dir=music_dir),
    )

    screen.enter()

    retained_view = screen._lvgl_view
    assert retained_view is not None
    assert binding.playlist_build_calls == 1
    sync_count_before_reset = len(binding.playlist_sync_payloads)

    display.get_ui_backend().reset()
    retained_view.sync()

    assert screen._lvgl_view is retained_view
    assert binding.playlist_build_calls == 2
    assert len(binding.playlist_sync_payloads) == sync_count_before_reset + 1
    assert binding.playlist_sync_payloads[-1]["items"] == ["Alpha"]


def test_playlist_screen_syncs_error_state_through_lvgl(tmp_path: Path) -> None:
    """PlaylistScreen should send the music-offline empty state through LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    screen = PlaylistScreen(
        display,
        context,
        music_service=LocalMusicService(MockMusicBackend(), music_dir=tmp_path / "Music"),
    )

    screen.enter()
    screen.render()

    payload = binding.playlist_sync_payloads[-1]
    assert payload["items"] == []
    assert payload["page_text"] is None
    assert payload["empty_title"] == "Music hiccup"
    assert payload["empty_subtitle"] == "Music offline"
