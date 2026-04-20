"""Focused tests for the LVGL-backed Listen menu delegation."""

from __future__ import annotations

from yoyopod.app_context import AppContext
from yoyopod.audio import LocalMusicService
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens import ListenScreen


class FakeLvglBinding:
    """Small native-binding double for Listen view tests."""

    def __init__(self) -> None:
        self.listen_build_calls = 0
        self.listen_destroy_calls = 0
        self.listen_sync_payloads: list[dict] = []

    def listen_build(self) -> None:
        self.listen_build_calls += 1

    def listen_sync(self, **payload) -> None:
        self.listen_sync_payloads.append(payload)

    def listen_destroy(self) -> None:
        self.listen_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True


class FakeLvglDisplay:
    """Tiny Display double for LVGL Listen delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend


def test_listen_screen_reuses_retained_lvgl_view_across_exit_and_reentry() -> None:
    """ListenScreen should retain its LVGL view across transitions."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=False)
    context.power.battery_percent = 58
    context.power.battery_charging = False
    context.power.available = True

    screen = ListenScreen(
        display,
        context,
        music_service=LocalMusicService(None),
    )

    screen.enter()
    screen.render()

    assert binding.listen_build_calls == 1
    assert len(binding.listen_sync_payloads) == 1
    first_payload = binding.listen_sync_payloads[-1]
    assert first_payload["page_text"] is None
    assert first_payload["items"] == ["Playlists", "Recent", "Shuffle"]
    assert first_payload["subtitles"] == ["Saved mixes", "Played lately", "Start something fun"]
    assert first_payload["icon_keys"] == ["playlist", "music_note", "listen"]
    assert first_payload["footer"] == "Tap next / 2x open / Hold back"
    assert first_payload["selected_index"] == 0
    assert first_payload["voip_state"] == 2
    assert first_payload["battery_percent"] == 58

    screen.on_advance()
    screen.render()

    second_payload = binding.listen_sync_payloads[-1]
    assert second_payload["page_text"] is None
    assert second_payload["icon_keys"] == ["playlist", "music_note", "listen"]
    assert second_payload["selected_index"] == 1

    screen.exit()
    assert binding.listen_destroy_calls == 0

    screen.enter()
    screen.render()

    assert binding.listen_build_calls == 1
    assert len(binding.listen_sync_payloads) == 3
