"""Focused tests for the LVGL-backed Hub screen delegation."""

from __future__ import annotations

from yoyopod.app_context import AppContext
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens import HubScreen


class FakeLvglBinding:
    """Small native-binding double for Hub view tests."""

    def __init__(self) -> None:
        self.hub_build_calls = 0
        self.hub_destroy_calls = 0
        self.hub_sync_payloads: list[dict] = []

    def hub_build(self) -> None:
        self.hub_build_calls += 1

    def hub_sync(self, **payload) -> None:
        self.hub_sync_payloads.append(payload)

    def hub_destroy(self) -> None:
        self.hub_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True
        self.scene_generation = 0

    def reset(self) -> None:
        self.scene_generation += 1


class FakeLvglDisplay:
    """Tiny Display double for LVGL Hub delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend


def test_hub_screen_reuses_retained_lvgl_view_across_exit_and_reentry() -> None:
    """HubScreen should retain its LVGL view across transitions."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.power.battery_percent = 77
    context.power.battery_charging = True
    context.power.available = True

    screen = HubScreen(display, context)

    screen.enter()
    screen.render()

    assert binding.hub_build_calls == 1
    assert len(binding.hub_sync_payloads) == 1
    first_payload = binding.hub_sync_payloads[-1]
    assert first_payload["title"] == "Listen"
    assert first_payload["subtitle"] == ""
    assert first_payload["footer"] == "Tap = Next | 2x Tap = Open"
    assert first_payload["selected_index"] == 0
    assert first_payload["total_cards"] == 4
    assert first_payload["voip_state"] == 1
    assert first_payload["battery_percent"] == 77
    assert first_payload["charging"] is True
    assert first_payload["power_available"] is True

    screen.on_advance()
    screen.render()

    second_payload = binding.hub_sync_payloads[-1]
    assert second_payload["title"] == "Talk"
    assert second_payload["selected_index"] == 1

    screen.exit()
    assert binding.hub_destroy_calls == 0

    screen.enter()
    screen.render()

    assert binding.hub_build_calls == 1
    assert len(binding.hub_sync_payloads) == 3


def test_hub_screen_rebuilds_retained_lvgl_view_after_backend_reset() -> None:
    """HubScreen should rebuild a retained view after the backend clears native scenes."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    screen = HubScreen(display, AppContext(interaction_profile=InteractionProfile.ONE_BUTTON))

    screen.enter()
    screen.render()

    assert binding.hub_build_calls == 1
    first_view = screen._lvgl_view

    display.get_ui_backend().reset()
    screen.enter()
    screen.render()

    assert screen._lvgl_view is not first_view
    assert binding.hub_build_calls == 2
    assert len(binding.hub_sync_payloads) == 2


def test_hub_screen_falls_back_cleanly_when_lvgl_backend_is_unavailable() -> None:
    """Missing LVGL backend state should leave the Hub without a delegated view."""

    class MissingBackendDisplay:
        backend_kind = "lvgl"

        def get_ui_backend(self):
            return None

    screen = HubScreen(MissingBackendDisplay(), AppContext(interaction_profile=InteractionProfile.ONE_BUTTON))

    screen.enter()

    assert screen._lvgl_view is None
