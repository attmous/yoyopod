"""Tests for the user-facing power status screen."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime
import time
from types import SimpleNamespace

from yoyopod.core import AppContext
from yoyopod.core import VoiceState
from yoyopod.integrations.power.models import (
    BatteryState,
    PowerDeviceInfo,
    PowerSnapshot,
    RTCState,
    ShutdownState,
)
from yoyopod.ui.display import Display
from yoyopod.ui.input import InteractionProfile
from yoyopod.ui.screens.system.power import (
    PowerScreen,
    PowerScreenActions,
    PowerScreenState,
    build_power_screen_actions,
    build_power_screen_state_provider,
)
from yoyopod.ui.screens.system.power_viewmodel import _VOICE_PAGE_SIGNATURE_FIELDS


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
        screen.enter()

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
        screen.enter()

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


def test_power_screen_can_resolve_state_and_actions_from_app() -> None:
    """PowerScreen should build its providers from the owning app seam."""

    display = Display(simulate=True)
    try:
        context = AppContext()
        refresh_calls: list[str] = []
        persist_calls: list[tuple[str, str | None]] = []
        volume_calls: list[tuple[str, int]] = []
        context.set_volume(50)
        app = SimpleNamespace(
            power_manager=StubPowerManager(_snapshot()),
            network_manager=None,
            get_status=lambda: {},
            audio_device_catalog=SimpleNamespace(
                playback_devices=lambda: ["Speaker A"],
                capture_devices=lambda: ["Mic A"],
                refresh_async=lambda: refresh_calls.append("refresh"),
            ),
            config_manager=SimpleNamespace(
                set_voice_speaker_device_id=lambda value: persist_calls.append(("speaker", value))
                or True,
                set_voice_capture_device_id=lambda value: persist_calls.append(("capture", value))
                or True,
            ),
            audio_volume_controller=SimpleNamespace(
                volume_up=lambda step: volume_calls.append(("up", step))
                or context.voice.output_volume + step,
                volume_down=lambda step: volume_calls.append(("down", step))
                or context.voice.output_volume - step,
            ),
            voip_manager=SimpleNamespace(
                mute=lambda: True,
                unmute=lambda: True,
            ),
        )
        screen = PowerScreen(
            display,
            context,
            app=app,
        )

        screen.enter()
        assert refresh_calls == ["refresh"]
        assert screen._get_state().playback_devices == ("Speaker A",)
        assert screen._get_state().capture_devices == ("Mic A",)

        screen.page_index = 3
        screen.on_select()
        screen.selected_row = 3
        screen.on_select()
        assert context.voice.speaker_device_id == "Speaker A"
        assert persist_calls == [("speaker", "Speaker A")]

        screen.selected_row = 6
        screen.on_select()
        assert context.voice.output_volume == 55
        assert volume_calls == [("up", 5)]
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


def test_power_screen_reuses_prepared_pages_until_explicit_refresh() -> None:
    """Setup should reuse cached prepared pages until an explicit refresh updates state."""

    class TogglingStateProvider:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> PowerScreenState:
            self.calls += 1
            network_enabled = self.calls > 1
            return PowerScreenState(
                network_enabled=network_enabled,
                network_rows=(("Status", "Online"),),
                gps_rows=(
                    ("Fix", "Yes"),
                    ("Lat", "48.873800"),
                    ("Lng", "2.352200"),
                    ("Alt", "349.6m"),
                    ("Speed", "0.0km/h"),
                ),
            )

    display = Display(simulate=True)
    try:
        provider = TogglingStateProvider()
        screen = PowerScreen(display, AppContext(), state_provider=provider)

        screen.enter()
        first_payload = screen.lvgl_payload()
        second_payload = screen.lvgl_payload()

        assert provider.calls == 1
        assert first_payload.total_pages == 4
        assert second_payload.total_pages == 4

        screen.refresh_prepared_state()
        refreshed_payload = screen.lvgl_payload()

        assert provider.calls == 2
        assert refreshed_payload.total_pages == 6
    finally:
        display.cleanup()


def test_power_screen_visible_tick_skips_immediate_post_enter_refresh() -> None:
    """Entering Setup should not immediately double-fetch on the next visible tick."""

    class CountingStateProvider:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> PowerScreenState:
            self.calls += 1
            return PowerScreenState()

    display = Display(simulate=True)
    try:
        provider = CountingStateProvider()
        screen = PowerScreen(display, AppContext(), state_provider=provider)
        screen._visible_tick_refresh_grace_seconds = 60.0

        screen.enter()
        screen.refresh_for_visible_tick()

        assert provider.calls == 1
    finally:
        display.cleanup()


def test_power_screen_page_change_to_gps_uses_cached_rows_without_immediate_query() -> None:
    """Entering the GPS page should not synchronously hit the modem on page change."""

    display = Display(simulate=True)
    try:
        gps_refresh_calls: list[str] = []
        screen = PowerScreen(
            display,
            AppContext(),
            state_provider=lambda: PowerScreenState(
                network_enabled=True,
                network_rows=(("Status", "Online"),),
                gps_rows=(
                    ("Fix", "Searching"),
                    ("Lat", "--"),
                    ("Lng", "--"),
                    ("Alt", "--"),
                    ("Speed", "--"),
                ),
            ),
            actions=PowerScreenActions(
                refresh_gps=lambda: gps_refresh_calls.append("refresh") or True,
            ),
        )

        screen.enter()
        screen.on_advance()
        screen.on_advance()

        assert screen._current_page_title() == "GPS"
        assert gps_refresh_calls == []
    finally:
        display.cleanup()


def test_power_screen_visible_tick_waits_for_gps_page_dwell_before_query() -> None:
    """Visible ticks should wait for a short GPS-page dwell before polling the modem."""

    display = Display(simulate=True)
    try:
        gps_refresh_calls: list[str] = []
        screen = PowerScreen(
            display,
            AppContext(),
            state_provider=lambda: PowerScreenState(
                network_enabled=True,
                network_rows=(("Status", "Online"),),
                gps_rows=(
                    ("Fix", "Searching"),
                    ("Lat", "--"),
                    ("Lng", "--"),
                    ("Alt", "--"),
                    ("Speed", "--"),
                ),
            ),
            actions=PowerScreenActions(
                refresh_gps=lambda: gps_refresh_calls.append("refresh") or True,
            ),
        )
        screen._visible_tick_refresh_grace_seconds = 0.0
        screen._gps_page_refresh_delay_seconds = 30.0

        screen.enter()
        screen.on_advance()
        screen.on_advance()
        screen.refresh_for_visible_tick()

        assert gps_refresh_calls == []

        screen._gps_page_entered_at = time.monotonic() - 31.0
        screen._last_gps_query_at = 0.0
        screen.refresh_for_visible_tick()

        assert gps_refresh_calls == ["refresh"]
    finally:
        display.cleanup()


def test_power_screen_visible_tick_stays_clean_when_prepared_state_is_unchanged() -> None:
    """Visible ticks should not force a render when the prepared state is unchanged."""

    state = PowerScreenState(
        network_enabled=True,
        network_rows=(("Status", "Online"),),
    )

    display = Display(simulate=True)
    try:
        screen = PowerScreen(display, AppContext(), state_provider=lambda: state)
        screen._visible_tick_refresh_grace_seconds = 0.0

        screen.enter()
        screen.clear_dirty()
        screen.refresh_for_visible_tick()

        assert screen.should_render_for_visible_tick() is False
    finally:
        display.cleanup()


def test_power_screen_visible_tick_marks_dirty_when_prepared_state_changes() -> None:
    """Visible ticks should mark the screen dirty when the prepared state changes."""

    first_snapshot = _snapshot()
    second_snapshot = replace(
        first_snapshot,
        battery=replace(first_snapshot.battery, level_percent=42.0),
    )

    states = iter(
        (
            PowerScreenState(
                snapshot=first_snapshot,
            ),
            PowerScreenState(
                snapshot=second_snapshot,
            ),
        )
    )

    display = Display(simulate=True)
    try:
        screen = PowerScreen(display, AppContext(), state_provider=lambda: next(states))
        screen._visible_tick_refresh_grace_seconds = 0.0

        screen.enter()
        screen.in_detail = True
        screen.clear_dirty()
        screen.refresh_for_visible_tick()

        assert screen.should_render_for_visible_tick() is True
    finally:
        display.cleanup()


def test_power_screen_visible_tick_ignores_volatile_status_ages_for_dirty_flag() -> None:
    """Visible ticks should ignore status-only age churn that does not change visible rows."""

    states = iter(
        (
            PowerScreenState(status={"input_activity_age_seconds": 1.0}),
            PowerScreenState(status={"input_activity_age_seconds": 2.0}),
        )
    )

    display = Display(simulate=True)
    try:
        screen = PowerScreen(display, AppContext(), state_provider=lambda: next(states))
        screen._visible_tick_refresh_grace_seconds = 0.0

        screen.enter()
        screen.clear_dirty()
        screen.refresh_for_visible_tick()

        assert screen.should_render_for_visible_tick() is False
    finally:
        display.cleanup()


def test_power_screen_copies_provider_status_on_refresh() -> None:
    """Prepared state should not retain provider-owned mutable status mappings."""

    shared_status = {"screen_awake": True}

    def provider() -> PowerScreenState:
        return PowerScreenState(status=shared_status)

    display = Display(simulate=True)
    try:
        screen = PowerScreen(display, AppContext(), state_provider=provider)

        refreshed_state = screen.refresh_prepared_state()
        shared_status["screen_awake"] = False

        assert refreshed_state.status["screen_awake"] is True
        assert screen._get_status()["screen_awake"] is True
    finally:
        display.cleanup()


def test_power_screen_snapshot_cache_ignores_hidden_snapshot_fields() -> None:
    """Prepared pages should survive snapshot-only churn that does not affect Setup rows."""

    class HiddenFieldChurnProvider:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> PowerScreenState:
            self.calls += 1
            return PowerScreenState(
                snapshot=PowerSnapshot(
                    available=True,
                    checked_at=datetime(2026, 4, 5, 12, 0, self.calls),
                    source="battery",
                    error=None,
                    device=PowerDeviceInfo(
                        model="PiSugar 3",
                        firmware_version=f"v{self.calls}",
                    ),
                    battery=BatteryState(
                        level_percent=55.2,
                        voltage_volts=3.62,
                        charging=True,
                        power_plugged=True,
                        allow_charging=bool(self.calls % 2),
                        output_enabled=bool((self.calls + 1) % 2),
                        temperature_celsius=29.5,
                    ),
                    rtc=RTCState(
                        time=datetime(2026, 4, 5, 13, 30, 0),
                        alarm_enabled=True,
                        alarm_time=datetime(2026, 4, 6, 7, 30, 0),
                        alarm_repeat_mask=self.calls,
                        adjust_ppm=self.calls,
                    ),
                    shutdown=ShutdownState(
                        safe_shutdown_level_percent=10.0,
                        safe_shutdown_delay_seconds=15 + self.calls,
                    ),
                )
            )

    display = Display(simulate=True)
    try:
        provider = HiddenFieldChurnProvider()
        screen = PowerScreen(display, AppContext(), state_provider=provider)

        screen.enter()
        first_pages = screen._prepared_pages()

        screen.refresh_prepared_state()
        second_pages = screen._prepared_pages()

        assert provider.calls == 2
        assert second_pages is first_pages
    finally:
        display.cleanup()


def test_power_screen_voice_signature_fields_stay_in_sync_with_voice_state() -> None:
    """Only the voice-signature subset should require review when the schema changes."""

    assert _VOICE_PAGE_SIGNATURE_FIELDS == (
        "commands_enabled",
        "ai_requests_enabled",
        "screen_read_enabled",
        "speaker_device_id",
        "capture_device_id",
        "mic_muted",
        "output_volume",
    )
    assert set(_VOICE_PAGE_SIGNATURE_FIELDS).issubset(
        {field_info.name for field_info in fields(VoiceState)}
    )


def test_power_screen_render_path_uses_default_state_without_provider_call() -> None:
    """Render-adjacent page preparation should not hydrate the provider on cache miss."""

    class CountingStateProvider:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> PowerScreenState:
            self.calls += 1
            return PowerScreenState(network_enabled=True)

    display = Display(simulate=True)
    try:
        provider = CountingStateProvider()
        screen = PowerScreen(display, AppContext(), state_provider=provider)

        payload = screen.lvgl_payload()

        assert payload.total_pages == 4
        assert provider.calls == 0
    finally:
        display.cleanup()
