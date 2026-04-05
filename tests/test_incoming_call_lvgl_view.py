"""Focused tests for the LVGL-backed incoming-call screen delegation."""

from __future__ import annotations

from yoyopy.app_context import AppContext
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import IncomingCallScreen


class FakeLvglBinding:
    """Small native-binding double for incoming-call view tests."""

    def __init__(self) -> None:
        self.incoming_call_build_calls = 0
        self.incoming_call_destroy_calls = 0
        self.incoming_call_sync_payloads: list[dict] = []

    def incoming_call_build(self) -> None:
        self.incoming_call_build_calls += 1

    def incoming_call_sync(self, **payload) -> None:
        self.incoming_call_sync_payloads.append(payload)

    def incoming_call_destroy(self) -> None:
        self.incoming_call_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True


class FakeLvglDisplay:
    """Tiny Display double for LVGL incoming-call delegation tests."""

    backend_kind = "lvgl"

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend


def test_incoming_call_screen_builds_syncs_and_destroys_lvgl_view() -> None:
    """IncomingCallScreen should delegate lifecycle and caller state to LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.battery_percent = 49
    context.battery_charging = False
    context.power_available = True

    screen = IncomingCallScreen(
        display,
        context,
        caller_address="sip:parent@example.com",
        caller_name="Parent",
    )

    screen.enter()
    screen.render()

    assert binding.incoming_call_build_calls == 1
    assert len(binding.incoming_call_sync_payloads) == 1
    payload = binding.incoming_call_sync_payloads[-1]
    assert payload["caller_name"] == "Parent"
    assert payload["caller_address"] == "sip:parent@example.com"
    assert payload["voip_state"] == 1
    assert payload["battery_percent"] == 49
    assert payload["charging"] is False
    assert payload["power_available"] is True
    assert payload["footer"] == "Open answer / Hold reject"

    screen.exit()
    assert binding.incoming_call_destroy_calls == 1


def test_incoming_call_screen_uses_safe_unknown_defaults_through_lvgl() -> None:
    """IncomingCallScreen should normalize missing caller details for LVGL."""

    binding = FakeLvglBinding()
    display = FakeLvglDisplay(binding)
    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)

    screen = IncomingCallScreen(
        display,
        context,
        caller_address="",
        caller_name="",
    )

    screen.enter()
    screen.render()

    payload = binding.incoming_call_sync_payloads[-1]
    assert payload["caller_name"] == "Unknown"
    assert payload["caller_address"] == "Unknown"
