"""Tests for the user-facing power status screen."""

from __future__ import annotations

from datetime import datetime

from yoyopod.app_context import AppContext
from yoyopod.power import BatteryState, PowerDeviceInfo, PowerSnapshot, RTCState, ShutdownState
from yoyopod.ui.display import Display
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens.system.power import (
    PowerScreen,
    build_power_screen_actions,
    build_power_screen_state_provider,
)


class StubPowerManager:
    """Minimal power manager double for screen tests."""

    def __init__(self, snapshot: PowerSnapshot) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> PowerSnapshot:
        return self._snapshot


def _snapshot() -> PowerSnapshot:
    return PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 5, 12, 0, 0),
        device=PowerDeviceInfo(model="PiSugar 3"),
        battery=BatteryState(
            level_percent=55.2,
            voltage_volts=3.62,
            charging=True,
            power_plugged=True,
            temperature_celsius=29.5,
        ),
        rtc=RTCState(
            time=datetime(2026, 4, 5, 13, 30, 0),
            alarm_enabled=True,
            alarm_time=datetime(2026, 4, 6, 7, 30, 0),
        ),
        shutdown=ShutdownState(
            safe_shutdown_level_percent=10.0,
            safe_shutdown_delay_seconds=15,
        ),
    )


def test_power_screen_builds_battery_and_runtime_pages() -> None:
    """The power screen should split telemetry and care info into portrait-safe pages."""
    display = Display(simulate=True)
    try:
        status = {
            "app_uptime_seconds": 3661,
            "screen_on_seconds": 901,
            "screen_idle_seconds": 32,
            "screen_awake": True,
            "screen_timeout_seconds": 30.0,
            "warning_threshold_percent": 20.0,
            "critical_shutdown_percent": 10.0,
            "shutdown_delay_seconds": 15.0,
            "shutdown_pending": False,
            "watchdog_enabled": True,
            "watchdog_active": True,
            "watchdog_feed_suppressed": False,
        }
        screen = PowerScreen(
            display,
            AppContext(),
            state_provider=build_power_screen_state_provider(
                power_manager=StubPowerManager(_snapshot()),
                status_provider=lambda: status,
            ),
        )

        pages = screen.build_pages(
            snapshot=screen._get_snapshot(),
            status=status,
        )

        assert [page.title for page in pages] == ["Power", "Time", "Care", "Voice"]
        assert ("Model", "PiSugar 3") in pages[0].rows
        assert ("Battery", "55% chg") in pages[0].rows
        assert ("RTC", "04-05 13:30") in pages[1].rows
        assert ("Uptime", "1h01m") in pages[1].rows
        assert ("Timeout", "30s") in pages[2].rows
        assert ("Watchdog", "Active") in pages[2].rows
        assert ("Voice Cmds", "On") in pages[3].rows
        assert ("Speaker", "Auto") in pages[3].rows
        assert ("Mic Device", "Auto") in pages[3].rows
        assert ("Mic", "Live") in pages[3].rows
        assert all(len(page.rows) <= 7 for page in pages)
    finally:
        display.cleanup()


def test_power_screen_formats_unavailable_snapshot() -> None:
    """Unavailable power backends should still render a readable status page."""
    display = Display(simulate=True)
    try:
        snapshot = PowerSnapshot(
            available=False,
            checked_at=datetime(2026, 4, 5, 12, 0, 0),
            error="I2C not connected",
        )
        screen = PowerScreen(
            display,
            AppContext(),
            state_provider=build_power_screen_state_provider(
                power_manager=StubPowerManager(snapshot),
                status_provider=lambda: {},
            ),
        )

        pages = screen.build_pages(snapshot=snapshot, status={})

        assert [page.title for page in pages] == ["Power", "Time", "Care", "Voice"]
        assert ("Status", "Offline") in pages[0].rows
        assert ("Reason", "I2C not connected") in pages[0].rows
        assert ("Watchdog", "Off") in pages[2].rows
        assert ("Voice Cmds", "On") in pages[3].rows
    finally:
        display.cleanup()


def test_power_screen_voice_page_toggles_runtime_voice_settings() -> None:
    """The Setup voice page should let the user toggle voice state and adjust volume."""

    display = Display(simulate=True)
    try:
        context = AppContext()
        mute_calls: list[str] = []
        volume_calls: list[tuple[str, int]] = []

        def volume_up(step: int) -> int:
            volume_calls.append(("up", step))
            context.set_volume(context.voice.output_volume + step)
            return context.voice.output_volume

        def volume_down(step: int) -> int:
            volume_calls.append(("down", step))
            context.set_volume(context.voice.output_volume - step)
            return context.voice.output_volume

        screen = PowerScreen(
            display,
            context,
            state_provider=build_power_screen_state_provider(
                power_manager=StubPowerManager(_snapshot()),
                status_provider=lambda: {},
            ),
            actions=build_power_screen_actions(
                volume_up_action=volume_up,
                volume_down_action=volume_down,
                mute_action=lambda: mute_calls.append("mute") or True,
                unmute_action=lambda: mute_calls.append("unmute") or True,
            ),
        )

        screen.page_index = 3
        screen.on_select()
        assert screen.in_detail is True
        assert screen._is_voice_page() is True

        screen.on_select()
        assert context.voice.commands_enabled is False

        screen.on_advance()
        screen.on_select()
        assert context.voice.ai_requests_enabled is False

        screen.on_advance()
        screen.on_select()
        assert context.voice.screen_read_enabled is True

        screen.on_advance()
        screen.on_advance()
        screen.on_advance()
        screen.on_select()
        assert context.voice.mic_muted is True
        assert mute_calls == ["mute"]

        screen.on_select()
        assert context.voice.mic_muted is False
        assert mute_calls == ["mute", "unmute"]

        screen.on_advance()
        context.set_volume(50)
        screen.on_select()
        assert context.voice.output_volume == 55
        assert volume_calls == [("up", 5)]

        screen.on_left()
        assert context.voice.output_volume == 50
        assert volume_calls == [("up", 5), ("down", 5)]
    finally:
        display.cleanup()


def test_power_screen_one_button_voice_page_stays_in_fast_page_mode() -> None:
    """Whisplay Setup should treat Voice like a normal page, not an interactive trap."""

    display = Display(simulate=True)
    try:
        context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
        screen = PowerScreen(
            display,
            context,
            state_provider=build_power_screen_state_provider(
                power_manager=StubPowerManager(_snapshot()),
                status_provider=lambda: {},
            ),
        )

        screen.page_index = 3
        page = screen._active_page()
        assert page.title == "Voice"
        assert page.interactive is False

        visible_rows, visible_selected_index = screen._visible_rows_for_page(page)
        assert [label for label, _ in visible_rows] == [
            "Voice Cmds",
            "AI Requests",
            "Screen Read",
            "Mic",
            "Volume",
        ]
        assert visible_selected_index is None

        screen.on_advance()
        assert screen.page_index == 0
        assert screen.selected_row == 0
        assert screen._active_page().title == "Power"
    finally:
        display.cleanup()


def test_power_screen_uses_injected_voice_device_hooks() -> None:
    """Setup should use injected device providers and persistence hooks."""

    display = Display(simulate=True)
    try:
        context = AppContext()
        refresh_calls: list[str] = []
        persisted_devices: list[tuple[str, str | None]] = []

        screen = PowerScreen(
            display,
            context,
            state_provider=build_power_screen_state_provider(
                power_manager=StubPowerManager(_snapshot()),
                status_provider=lambda: {},
                playback_device_options_provider=lambda: ["plughw:CARD=wm8960soundcard,DEV=0"],
                capture_device_options_provider=lambda: ["plughw:CARD=USB,DEV=0"],
            ),
            actions=build_power_screen_actions(
                refresh_voice_device_options_action=lambda: refresh_calls.append("refresh"),
                persist_speaker_device_action=(
                    lambda device_id: persisted_devices.append(("speaker", device_id)) or True
                ),
                persist_capture_device_action=(
                    lambda device_id: persisted_devices.append(("capture", device_id)) or True
                ),
            ),
        )

        screen.enter()
        assert refresh_calls == ["refresh"]

        screen.page_index = 3
        screen.on_select()
        assert screen.in_detail is True

        screen.selected_row = 3
        screen.on_select()
        assert context.voice.speaker_device_id == "plughw:CARD=wm8960soundcard,DEV=0"

        screen.selected_row = 4
        screen.on_select()
        assert context.voice.capture_device_id == "plughw:CARD=USB,DEV=0"

        assert persisted_devices == [
            ("speaker", "plughw:CARD=wm8960soundcard,DEV=0"),
            ("capture", "plughw:CARD=USB,DEV=0"),
        ]
    finally:
        display.cleanup()
