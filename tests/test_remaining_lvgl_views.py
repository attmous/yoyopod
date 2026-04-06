"""Focused tests for the remaining LVGL-backed screen delegations."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopy.app_context import AppContext
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import (
    AskScreen,
    CallScreen,
    ContactListScreen,
    InCallScreen,
    OutgoingCallScreen,
    PowerScreen,
    TalkContactScreen,
)


class FakeLvglBinding:
    """Small native-binding double for LVGL view tests."""

    def __init__(self) -> None:
        self.hub_build_calls = 0
        self.hub_destroy_calls = 0
        self.hub_sync_payloads: list[dict] = []
        self.playlist_build_calls = 0
        self.playlist_destroy_calls = 0
        self.playlist_sync_payloads: list[dict] = []
        self.outgoing_call_build_calls = 0
        self.outgoing_call_destroy_calls = 0
        self.outgoing_call_sync_payloads: list[dict] = []
        self.in_call_build_calls = 0
        self.in_call_destroy_calls = 0
        self.in_call_sync_payloads: list[dict] = []
        self.ask_build_calls = 0
        self.ask_destroy_calls = 0
        self.ask_sync_payloads: list[dict] = []
        self.power_build_calls = 0
        self.power_destroy_calls = 0
        self.power_sync_payloads: list[dict] = []

    def hub_build(self) -> None:
        self.hub_build_calls += 1

    def hub_sync(self, **payload) -> None:
        self.hub_sync_payloads.append(payload)

    def hub_destroy(self) -> None:
        self.hub_destroy_calls += 1

    def playlist_build(self) -> None:
        self.playlist_build_calls += 1

    def playlist_sync(self, **payload) -> None:
        self.playlist_sync_payloads.append(payload)

    def playlist_destroy(self) -> None:
        self.playlist_destroy_calls += 1

    def outgoing_call_build(self) -> None:
        self.outgoing_call_build_calls += 1

    def outgoing_call_sync(self, **payload) -> None:
        self.outgoing_call_sync_payloads.append(payload)

    def outgoing_call_destroy(self) -> None:
        self.outgoing_call_destroy_calls += 1

    def in_call_build(self) -> None:
        self.in_call_build_calls += 1

    def in_call_sync(self, **payload) -> None:
        self.in_call_sync_payloads.append(payload)

    def in_call_destroy(self) -> None:
        self.in_call_destroy_calls += 1

    def ask_build(self) -> None:
        self.ask_build_calls += 1

    def ask_sync(self, **payload) -> None:
        self.ask_sync_payloads.append(payload)

    def ask_destroy(self) -> None:
        self.ask_destroy_calls += 1

    def power_build(self) -> None:
        self.power_build_calls += 1

    def power_sync(self, **payload) -> None:
        self.power_sync_payloads.append(payload)

    def power_destroy(self) -> None:
        self.power_destroy_calls += 1


class FakeLvglBackend:
    """Minimal LVGL backend double exposed through Display.get_ui_backend()."""

    def __init__(self, binding: FakeLvglBinding) -> None:
        self.binding = binding
        self.initialized = True


class FakeLvglDisplay:
    """Tiny Display double for LVGL screen delegation tests."""

    backend_kind = "lvgl"
    COLOR_RED = (255, 0, 0)
    COLOR_GREEN = (0, 255, 0)
    COLOR_YELLOW = (255, 255, 0)
    COLOR_GRAY = (128, 128, 128)

    def __init__(self, binding: FakeLvglBinding) -> None:
        self._ui_backend = FakeLvglBackend(binding)

    def get_ui_backend(self) -> FakeLvglBackend:
        return self._ui_backend

    def is_portrait(self) -> bool:
        return True


@dataclass(slots=True)
class FakeContact:
    """Minimal contact model for Talk screen tests."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.notes or self.name


class FakeConfigManager:
    """Minimal config manager returning a stable contact list."""

    def __init__(self, contacts: list[FakeContact]) -> None:
        self._contacts = list(contacts)

    def get_contacts(self) -> list[FakeContact]:
        return list(self._contacts)


class FakeVoipManager:
    """Minimal VoIP manager for Talk/call LVGL delegation tests."""

    def __init__(
        self,
        *,
        status: dict | None = None,
        caller_info: dict | None = None,
        duration_seconds: int = 0,
        muted: bool = False,
    ) -> None:
        self._status = status or {
            "sip_identity": "sip:kid@example.com",
            "running": True,
            "registered": True,
            "registration_state": "ok",
            "call_state": "idle",
        }
        self._caller_info = caller_info or {}
        self._duration_seconds = duration_seconds
        self.is_muted = muted

    def get_status(self) -> dict:
        return dict(self._status)

    def get_caller_info(self) -> dict:
        return dict(self._caller_info)

    def get_call_duration(self) -> int:
        return self._duration_seconds


def make_one_button_context() -> AppContext:
    """Create a stable one-button app context for LVGL tests."""

    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.battery_percent = 64
    context.battery_charging = False
    context.power_available = True
    return context


def test_call_screen_builds_syncs_and_destroys_lvgl_view() -> None:
    """CallScreen should delegate the Talk contact deck through LVGL."""

    binding = FakeLvglBinding()
    screen = CallScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(),
        config_manager=FakeConfigManager(
            [
                FakeContact("Hagar", "sip:hagar@example.com", True),
                FakeContact("Mama", "sip:mama@example.com", True),
            ]
        ),
    )

    screen.enter()
    screen.render()

    assert binding.hub_build_calls == 1
    payload = binding.hub_sync_payloads[-1]
    assert payload["title"] == "Hagar"
    assert payload["subtitle"] == "Call or voice note"
    assert payload["footer"] == "Tap next / Double open"
    assert payload["selected_index"] == 0
    assert payload["total_cards"] == 2

    screen.on_advance()
    screen.render()

    payload = binding.hub_sync_payloads[-1]
    assert payload["title"] == "Mama"
    assert payload["selected_index"] == 1

    screen.exit()
    assert binding.hub_destroy_calls == 1


def test_call_screen_can_reenter_lvgl_view_without_lifecycle_errors() -> None:
    """Talk should survive repeated enter/render/exit cycles on the LVGL path."""

    binding = FakeLvglBinding()
    screen = CallScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(),
        config_manager=FakeConfigManager(
            [
                FakeContact("Hagar", "sip:hagar@example.com", True),
                FakeContact("Mama", "sip:mama@example.com", True),
            ]
        ),
    )

    for expected_title, advance in (("Hagar", False), ("Mama", True)):
        screen.enter()
        if advance:
            screen.on_advance()
        screen.render()
        payload = binding.hub_sync_payloads[-1]
        assert payload["title"] == expected_title
        screen.exit()

    assert binding.hub_build_calls == 2
    assert binding.hub_destroy_calls == 2


def test_talk_contact_screen_syncs_actions_through_lvgl() -> None:
    """TalkContactScreen should delegate its action list through LVGL."""

    binding = FakeLvglBinding()
    context = make_one_button_context()
    context.set_talk_contact(name="Mama", sip_address="sip:mama@example.com")
    screen = TalkContactScreen(
        FakeLvglDisplay(binding),
        context,
        voip_manager=FakeVoipManager(),
    )

    screen.enter()
    screen.render()

    assert binding.playlist_build_calls == 1
    payload = binding.playlist_sync_payloads[-1]
    assert payload["title_text"] == "Mama"
    assert payload["items"] == ["Call", "Voice Note"]
    assert payload["footer"] == "Tap next / Double choose"

    screen.exit()
    assert binding.playlist_destroy_calls == 1


def test_contact_list_screen_syncs_sorted_contacts_through_lvgl() -> None:
    """ContactListScreen should delegate its visible list window to LVGL."""

    binding = FakeLvglBinding()
    screen = ContactListScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(),
        config_manager=FakeConfigManager(
            [
                FakeContact("Zed", "sip:zed@example.com", False),
                FakeContact("Amy", "sip:amy@example.com", True, notes="Mama"),
                FakeContact("Mona", "sip:mona@example.com", False),
            ]
        ),
    )

    screen.enter()
    screen.render()

    assert binding.playlist_build_calls == 1
    payload = binding.playlist_sync_payloads[-1]
    assert payload["title_text"] == "Contacts"
    assert payload["page_text"] is None
    assert payload["items"] == ["Mama", "Zed", "Mona"]
    assert payload["badges"] == ["", "", ""]

    screen.exit()
    assert binding.playlist_destroy_calls == 1


def test_outgoing_call_screen_syncs_current_callee_through_lvgl() -> None:
    """OutgoingCallScreen should send callee and footer state through LVGL."""

    binding = FakeLvglBinding()
    screen = OutgoingCallScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(
            caller_info={
                "display_name": "Parent",
                "address": "sip:parent@example.com",
            }
        ),
    )

    screen.enter()
    screen.render()

    assert binding.outgoing_call_build_calls == 1
    payload = binding.outgoing_call_sync_payloads[-1]
    assert payload["callee_name"] == "Parent"
    assert payload["callee_address"] == "sip:parent@example.com"
    assert payload["footer"] == "Hold cancel"

    screen.exit()
    assert binding.outgoing_call_destroy_calls == 1


def test_in_call_screen_syncs_duration_and_mute_state_through_lvgl() -> None:
    """InCallScreen should delegate live call state through LVGL."""

    binding = FakeLvglBinding()
    screen = InCallScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(
            caller_info={"display_name": "Parent"},
            duration_seconds=83,
            muted=True,
        ),
    )

    screen.enter()
    screen.render()

    assert binding.in_call_build_calls == 1
    payload = binding.in_call_sync_payloads[-1]
    assert payload["caller_name"] == "Parent"
    assert payload["duration_text"] == "01:23"
    assert payload["mute_text"] == "Muted"
    assert payload["muted"] is True
    assert payload["footer"] == "Tap unmute / End"

    screen.exit()
    assert binding.in_call_destroy_calls == 1


def test_ask_screen_syncs_staged_shell_through_lvgl() -> None:
    """AskScreen should expose the staged Ask shell through LVGL."""

    binding = FakeLvglBinding()
    screen = AskScreen(FakeLvglDisplay(binding), make_one_button_context())

    screen.enter()
    screen.render()

    assert binding.ask_build_calls == 1
    payload = binding.ask_sync_payloads[-1]
    assert payload["icon_key"] == "ask"
    assert payload["title_text"] == "Ask AI"
    assert payload["subtitle_text"] == "Tell me a fun fact"
    assert payload["footer"] == "Tap idea / Double start / Hold back"

    screen.exit()
    assert binding.ask_destroy_calls == 1


def test_voice_note_screen_uses_playlist_scene_with_talk_voice_note_copy() -> None:
    """VoiceNoteScreen should use the richer playlist-style LVGL scene for review states."""

    from yoyopy.ui.screens.voip.voice_note import VoiceNoteScreen

    binding = FakeLvglBinding()
    context = make_one_button_context()
    context.set_voice_note_recipient(name="Hagar", sip_address="sip:hagar@example.com")
    screen = VoiceNoteScreen(FakeLvglDisplay(binding), context)

    screen.enter()
    screen.render()

    payload = binding.playlist_sync_payloads[-1]
    assert payload["title_text"] == "Hagar"
    assert payload["status_chip_text"] == "Ready"
    assert payload["empty_title"] == "Voice Note"
    assert payload["empty_subtitle"] == "Hold to record for Hagar."
    assert payload["footer"] == "Hold record / Double back"
    assert payload["empty_icon_key"] == "voice_note"

    screen.exit()
    assert binding.playlist_destroy_calls == 1


def test_power_screen_cycles_three_lvgl_pages() -> None:
    """PowerScreen should expose all three Setup pages through LVGL."""

    binding = FakeLvglBinding()
    screen = PowerScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        power_manager=None,
        status_provider=lambda: {
            "app_uptime_seconds": 99,
            "screen_awake": True,
            "screen_on_seconds": 42,
            "screen_idle_seconds": 3,
            "screen_timeout_seconds": 60,
            "warning_threshold_percent": 20,
            "critical_shutdown_percent": 10,
            "shutdown_delay_seconds": 15,
            "shutdown_pending": False,
            "watchdog_enabled": True,
            "watchdog_active": True,
            "watchdog_feed_suppressed": False,
        },
    )

    screen.enter()
    screen.render()

    assert binding.power_build_calls == 1
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Power"
    assert payload["page_text"] is None
    assert payload["items"] == [
        "Source: Unavailable",
        "Battery: Unknown",
        "Charging: Unknown",
        "RTC: Unknown",
    ]

    screen.on_advance()
    screen.render()
    assert binding.power_sync_payloads[-1]["title_text"] == "Time"
    assert binding.power_sync_payloads[-1]["page_text"] is None

    screen.on_advance()
    screen.render()
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Care"
    assert payload["page_text"] is None

    screen.exit()
    assert binding.power_destroy_calls == 1
