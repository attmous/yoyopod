"""Focused tests for the remaining LVGL-backed screen delegations."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.app_context import AppContext
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens import (
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
        self.status_bar_state_payloads: list[dict] = []
        self.hub_build_calls = 0
        self.hub_destroy_calls = 0
        self.hub_sync_payloads: list[dict] = []
        self.talk_build_calls = 0
        self.talk_destroy_calls = 0
        self.talk_sync_payloads: list[dict] = []
        self.talk_actions_build_calls = 0
        self.talk_actions_destroy_calls = 0
        self.talk_actions_sync_payloads: list[dict] = []
        self.playlist_build_calls = 0
        self.playlist_destroy_calls = 0
        self.playlist_sync_payloads: list[dict] = []
        self.incoming_call_build_calls = 0
        self.incoming_call_destroy_calls = 0
        self.incoming_call_sync_payloads: list[dict] = []
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

    def talk_build(self) -> None:
        self.talk_build_calls += 1

    def talk_sync(self, **payload) -> None:
        self.talk_sync_payloads.append(payload)

    def talk_destroy(self) -> None:
        self.talk_destroy_calls += 1

    def hub_build(self) -> None:
        self.hub_build_calls += 1

    def hub_sync(self, **payload) -> None:
        self.hub_sync_payloads.append(payload)

    def hub_destroy(self) -> None:
        self.hub_destroy_calls += 1

    def talk_actions_build(self) -> None:
        self.talk_actions_build_calls += 1

    def talk_actions_sync(self, **payload) -> None:
        self.talk_actions_sync_payloads.append(payload)

    def talk_actions_destroy(self) -> None:
        self.talk_actions_destroy_calls += 1

    def playlist_build(self) -> None:
        self.playlist_build_calls += 1

    def playlist_sync(self, **payload) -> None:
        self.playlist_sync_payloads.append(payload)

    def playlist_destroy(self) -> None:
        self.playlist_destroy_calls += 1

    def incoming_call_build(self) -> None:
        self.incoming_call_build_calls += 1

    def incoming_call_sync(self, **payload) -> None:
        self.incoming_call_sync_payloads.append(payload)

    def incoming_call_destroy(self) -> None:
        self.incoming_call_destroy_calls += 1

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

    def set_status_bar_state(self, **payload) -> None:
        self.status_bar_state_payloads.append(payload)


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
        people_directory=FakeConfigManager(
            [
                FakeContact("Hagar", "sip:hagar@example.com", True),
                FakeContact("Mama", "sip:mama@example.com", True),
            ]
        ),
    )

    screen.enter()
    screen.render()

    assert binding.talk_build_calls == 1
    payload = binding.talk_sync_payloads[-1]
    assert payload["title_text"] == "Hagar"
    assert payload["icon_key"] is None
    assert payload["footer"] == "Tap Next | 2x Open | Hold Back"
    assert payload["selected_index"] == 0
    assert payload["total_cards"] == 2

    screen.on_advance()
    screen.render()

    payload = binding.talk_sync_payloads[-1]
    assert payload["title_text"] == "Mama"
    assert payload["selected_index"] == 1

    screen.exit()
    assert binding.talk_destroy_calls == 1


def test_call_screen_can_reenter_lvgl_view_without_lifecycle_errors() -> None:
    """Talk should survive repeated enter/render/exit cycles on the LVGL path."""

    binding = FakeLvglBinding()
    screen = CallScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(),
        people_directory=FakeConfigManager(
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
        payload = binding.talk_sync_payloads[-1]
        assert payload["title_text"] == expected_title
        screen.exit()

    assert binding.talk_build_calls == 2
    assert binding.talk_destroy_calls == 2


def test_hub_view_syncs_network_status_bar_state_through_lvgl() -> None:
    """HubScreen should push cellular and GPS state into the native status bar."""

    from yoyopod.ui.screens.navigation.hub import HubScreen

    binding = FakeLvglBinding()
    context = make_one_button_context()
    context.update_network_status(
        network_enabled=True,
        signal_bars=3,
        connected=False,
        gps_has_fix=True,
    )
    screen = HubScreen(FakeLvglDisplay(binding), context)

    screen.enter()
    screen.render()

    assert binding.status_bar_state_payloads[-1] == {
        "network_enabled": 1,
        "network_connected": 0,
        "wifi_connected": 0,
        "signal_strength": 3,
        "gps_has_fix": 1,
    }


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

    assert binding.talk_actions_build_calls == 1
    payload = binding.talk_actions_sync_payloads[-1]
    assert payload["contact_name"] == "Mama"
    assert payload["title_text"] == "Call"
    assert payload["icon_keys"] == ["call", "voice_note"]
    assert payload["action_count"] == 2
    assert payload["layout_kind"] == 0
    assert payload["button_size_kind"] == 1
    assert payload["footer"] == "Tap Next | 2x Select | Hold Back"

    screen.exit()
    assert binding.talk_actions_destroy_calls == 1


def test_contact_list_screen_syncs_sorted_contacts_through_lvgl() -> None:
    """ContactListScreen should delegate its visible list window to LVGL."""

    binding = FakeLvglBinding()
    screen = ContactListScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        voip_manager=FakeVoipManager(),
        people_directory=FakeConfigManager(
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
    assert payload["title_text"] == "More People"
    assert payload["page_text"] is None
    assert payload["items"] == ["Mama", "Zed", "Mona"]
    assert payload["subtitles"] == ["", "", ""]
    assert payload["badges"] == ["", "", ""]
    assert payload["icon_keys"] == ["mono:MA", "mono:ZE", "mono:MO"]
    assert payload["footer"] == "Tap Next | 2x Open | Hold Back"

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
    assert payload["footer"] == "Hold = Cancel"

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
    assert payload["duration_text"] == "IN CALL | 01:23"
    assert payload["mute_text"] == "MUTED"
    assert payload["muted"] is True
    assert payload["footer"] == "Tap = Unmute | Hold = End"

    screen.exit()
    assert binding.in_call_destroy_calls == 1


def test_ask_screen_builds_syncs_and_destroys_lvgl_view() -> None:
    """AskScreen should delegate its voice-command shell through LVGL."""

    from yoyopod.ui.screens.navigation.ask import AskScreen as _AskScreen

    binding = FakeLvglBinding()
    screen = _AskScreen(
        display=FakeLvglDisplay(binding),
        context=make_one_button_context(),
    )

    screen.render()

    assert binding.ask_build_calls == 1
    payload = binding.ask_sync_payloads[-1]
    assert payload["title_text"] == "Ask"
    assert payload["subtitle_text"] == "Ask me anything..."
    assert payload["footer"] == "Double listen / Hold back"
    assert payload["icon_key"] == "ask"

    screen.exit()
    assert binding.ask_destroy_calls == 1


def test_voice_note_screen_uses_talk_actions_scene_for_voice_note_states() -> None:
    """VoiceNoteScreen should delegate to the Talk actions scene on LVGL."""

    from yoyopod.ui.screens.voip.voice_note import VoiceNoteScreen
    from yoyopod.ui.screens.voip.voice_note import (
        build_voice_note_actions,
        build_voice_note_state_provider,
    )

    binding = FakeLvglBinding()
    context = make_one_button_context()
    context.set_voice_note_recipient(name="Hagar", sip_address="sip:hagar@example.com")
    screen = VoiceNoteScreen(
        FakeLvglDisplay(binding),
        context,
        state_provider=build_voice_note_state_provider(context=context),
        actions=build_voice_note_actions(),
    )

    screen.enter()
    screen.render()

    payload = binding.talk_actions_sync_payloads[-1]
    assert payload["contact_name"] == "Hagar"
    assert payload["title_text"] == "Voice Note"
    assert payload["status_text"] == "Hold to record"
    assert payload["footer"] == "Hold record / Double back"
    assert payload["layout_kind"] == 1
    assert payload["icon_keys"] == ["voice_note"]

    screen.exit()
    assert binding.talk_actions_destroy_calls == 1


def test_power_screen_cycles_four_lvgl_pages() -> None:
    """PowerScreen should use the picker/detail Setup flow on standard controls."""

    from yoyopod.ui.screens.system.power import build_power_screen_state_provider

    binding = FakeLvglBinding()
    screen = PowerScreen(
        FakeLvglDisplay(binding),
        AppContext(),
        state_provider=build_power_screen_state_provider(
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
        ),
    )

    screen.enter()
    screen.render()

    assert binding.power_build_calls == 1
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Setup"
    assert payload["page_text"] is None
    assert payload["icon_key"] == "battery"
    assert payload["current_page_index"] == 0
    assert payload["total_pages"] == 4
    assert payload["footer"] == "A open | B back | X/Y move"
    assert payload["items"] == [
        "> Power",
        "Time",
        "Care",
        "Voice",
    ]

    screen.on_advance()
    screen.render()
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Setup"
    assert payload["icon_key"] == "clock"
    assert payload["items"] == [
        "Power",
        "> Time",
        "Care",
        "Voice",
    ]
    assert binding.power_sync_payloads[-1]["icon_key"] == "clock"
    assert binding.power_sync_payloads[-1]["page_text"] is None

    screen.on_advance()
    screen.render()
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Setup"
    assert payload["icon_key"] == "care"
    assert payload["page_text"] is None
    assert payload["items"] == [
        "Power",
        "Time",
        "> Care",
        "Voice",
    ]

    screen.on_advance()
    screen.render()
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Setup"
    assert payload["icon_key"] == "voice_note"
    assert payload["page_text"] is None
    assert payload["items"] == [
        "Power",
        "Time",
        "Care",
        "> Voice",
    ]

    # Open the selected Voice page to confirm it renders interactively.
    screen.on_select()
    screen.render()
    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "Voice"
    assert payload["icon_key"] == "voice_note"
    assert payload["page_text"] is None
    assert payload["footer"] == "A change | B back | X/Y item | L/R page"
    assert payload["items"][0].startswith("> Voice Cmds:")
    assert any("Speaker:" in item for item in payload["items"])

    screen.exit()
    assert binding.power_destroy_calls == 1


def test_power_screen_one_button_voice_page_wraps_immediately() -> None:
    """The Whisplay Voice page should stay in the normal page-to-page loop."""

    from yoyopod.ui.screens.system.power import build_power_screen_state_provider

    binding = FakeLvglBinding()
    screen = PowerScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        state_provider=build_power_screen_state_provider(status_provider=lambda: {}),
    )

    screen.enter()
    screen.page_index = 3
    screen.render()

    assert binding.power_sync_payloads[-1]["title_text"] == "Voice"
    assert binding.power_sync_payloads[-1]["footer"] == "Tap page / Hold back"
    assert binding.power_sync_payloads[-1]["items"] == [
        "Voice Cmds: On",
        "AI Requests: On",
        "Screen Read: Off",
        "Mic: Live",
        "Volume: 50%",
    ]

    screen.on_advance()
    screen.render()
    assert binding.power_sync_payloads[-1]["title_text"] == "Power"
    assert binding.power_sync_payloads[-1]["current_page_index"] == 0

    screen.exit()


def test_power_screen_reports_full_network_page_count_through_lvgl() -> None:
    """Network-enabled Setup pages should preserve the full page count in LVGL payloads."""

    from yoyopod.network.models import ModemPhase, ModemState, SignalInfo
    from yoyopod.ui.screens.system.power import (
        build_power_screen_actions,
        build_power_screen_state_provider,
    )

    class _FakeNetworkManager:
        def __init__(self) -> None:
            self.config = type("Config", (), {"enabled": True, "gps_enabled": True})()
            self._state = ModemState(
                phase=ModemPhase.REGISTERED,
                signal=SignalInfo(csq=20),
                carrier="Telekom.de",
                network_type="4G",
                sim_ready=True,
            )
            self.query_gps_calls = 0

        @property
        def modem_state(self) -> ModemState:
            return self._state

        def query_gps(self):
            self.query_gps_calls += 1
            return None

    binding = FakeLvglBinding()
    network_manager = _FakeNetworkManager()
    screen = PowerScreen(
        FakeLvglDisplay(binding),
        make_one_button_context(),
        state_provider=build_power_screen_state_provider(
            network_manager=network_manager,
            status_provider=lambda: {},
        ),
        actions=build_power_screen_actions(network_manager=network_manager),
    )

    screen.enter()
    screen.page_index = 2
    screen.render()

    payload = binding.power_sync_payloads[-1]
    assert payload["title_text"] == "GPS"
    assert payload["current_page_index"] == 2
    assert payload["total_pages"] == 6
    assert payload["items"] == [
        "Fix: Searching",
        "Lat: --",
        "Lng: --",
        "Alt: --",
        "Speed: --",
    ]

    screen.exit()
