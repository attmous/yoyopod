"""Setup screen for power, runtime, and device care."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger

from yoyopod.device import format_device_label
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.system.lvgl import LvglPowerView
from yoyopod.ui.screens.theme import (
    INK,
    MUTED,
    SETUP,
    SURFACE_RAISED,
    draw_icon,
    render_footer,
    render_backdrop,
    render_status_bar,
    rounded_panel,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.power import PowerManager, PowerSnapshot
    from yoyopod.ui.screens import ScreenView


@dataclass(frozen=True, slots=True)
class PowerPage:
    """One setup page made of compact rows."""

    title: str
    rows: list[tuple[str, str]]
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class PowerScreenState:
    """Prepared power/setup state consumed by the Setup screen."""

    snapshot: "PowerSnapshot | None" = None
    status: dict[str, object] = field(default_factory=dict)
    network_enabled: bool = False
    network_rows: tuple[tuple[str, str], ...] = ()
    gps_rows: tuple[tuple[str, str], ...] = ()
    playback_devices: tuple[str, ...] = ()
    capture_devices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PowerScreenActions:
    """Focused actions exposed to the Setup screen."""

    refresh_voice_devices: Callable[[], None] | None = None
    refresh_gps: Callable[[], bool] | None = None
    persist_speaker_device: Callable[[str | None], bool] | None = None
    persist_capture_device: Callable[[str | None], bool] | None = None
    volume_up: Callable[[int], int | None] | None = None
    volume_down: Callable[[int], int | None] | None = None
    mute: Callable[[], bool] | None = None
    unmute: Callable[[], bool] | None = None


def _build_network_rows_from_manager(network_manager: object | None) -> list[tuple[str, str]]:
    """Build the cellular network status rows from a backend-facing manager."""

    if network_manager is None or not network_manager.config.enabled:
        return [("Status", "Disabled")]

    from yoyopod.network.models import ModemPhase

    state = network_manager.modem_state
    if state.phase == ModemPhase.ONLINE:
        status_text = "Online"
    elif state.phase in (
        ModemPhase.REGISTERED,
        ModemPhase.PPP_STARTING,
        ModemPhase.PPP_STOPPING,
    ):
        status_text = "Registered"
    elif state.phase in (ModemPhase.PROBING, ModemPhase.READY, ModemPhase.REGISTERING):
        status_text = "Connecting"
    else:
        status_text = "Offline"

    return [
        ("Status", status_text),
        ("Carrier", state.carrier or "Unknown"),
        ("Type", state.network_type or "Unknown"),
        ("Signal", f"{state.signal.bars}/4" if state.signal else "Unknown"),
        ("PPP", "Up" if state.phase == ModemPhase.ONLINE else "Down"),
    ]


def _build_gps_rows_from_manager(network_manager: object | None) -> list[tuple[str, str]]:
    """Build the GPS status rows from a backend-facing manager."""

    if network_manager is None or not network_manager.config.enabled:
        return [
            ("Fix", "Disabled"),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]
    if not network_manager.config.gps_enabled:
        return [
            ("Fix", "Disabled"),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]

    from yoyopod.network.models import ModemPhase

    state = network_manager.modem_state
    if state.gps is None:
        fix_status = "Searching"
        if state.phase in (ModemPhase.OFF, ModemPhase.PROBING, ModemPhase.READY):
            fix_status = "Starting"
        elif state.phase not in (
            ModemPhase.REGISTERING,
            ModemPhase.REGISTERED,
            ModemPhase.PPP_STARTING,
            ModemPhase.PPP_STOPPING,
            ModemPhase.ONLINE,
        ):
            fix_status = "Unavailable"
        return [
            ("Fix", fix_status),
            ("Lat", "--"),
            ("Lng", "--"),
            ("Alt", "--"),
            ("Speed", "--"),
        ]

    coord = state.gps
    return [
        ("Fix", "Yes"),
        ("Lat", f"{coord.lat:.6f}"),
        ("Lng", f"{coord.lng:.6f}"),
        ("Alt", f"{coord.altitude:.1f}m"),
        ("Speed", f"{coord.speed:.1f}km/h"),
    ]


def build_power_screen_state_provider(
    *,
    power_manager: "PowerManager | None" = None,
    network_manager: object | None = None,
    status_provider: Callable[[], dict[str, object]] | None = None,
    playback_device_options_provider: Callable[[], list[str]] | None = None,
    capture_device_options_provider: Callable[[], list[str]] | None = None,
) -> Callable[[], PowerScreenState]:
    """Build a prepared-state provider for the Setup screen."""

    def provider() -> PowerScreenState:
        snapshot = power_manager.get_snapshot() if power_manager is not None else None
        try:
            status = dict(status_provider() if status_provider is not None else {})
        except Exception:
            status = {}

        return PowerScreenState(
            snapshot=snapshot,
            status=status,
            network_enabled=bool(
                network_manager is not None and getattr(network_manager.config, "enabled", False)
            ),
            network_rows=tuple(_build_network_rows_from_manager(network_manager)),
            gps_rows=tuple(_build_gps_rows_from_manager(network_manager)),
            playback_devices=tuple(
                playback_device_options_provider()
                if playback_device_options_provider is not None
                else []
            ),
            capture_devices=tuple(
                capture_device_options_provider()
                if capture_device_options_provider is not None
                else []
            ),
        )

    return provider


def build_power_screen_actions(
    *,
    network_manager: object | None = None,
    refresh_voice_device_options_action: Callable[[], None] | None = None,
    persist_speaker_device_action: Callable[[str | None], bool] | None = None,
    persist_capture_device_action: Callable[[str | None], bool] | None = None,
    volume_up_action: Callable[[int], int | None] | None = None,
    volume_down_action: Callable[[int], int | None] | None = None,
    mute_action: Callable[[], bool] | None = None,
    unmute_action: Callable[[], bool] | None = None,
) -> PowerScreenActions:
    """Build the focused actions for the Setup screen."""

    def refresh_gps() -> bool:
        if network_manager is None or not getattr(network_manager.config, "enabled", False):
            return False
        if not getattr(network_manager.config, "gps_enabled", False):
            return False

        query_gps = getattr(network_manager, "query_gps", None)
        if not callable(query_gps):
            return False
        return query_gps() is not None

    return PowerScreenActions(
        refresh_voice_devices=refresh_voice_device_options_action,
        refresh_gps=refresh_gps,
        persist_speaker_device=persist_speaker_device_action,
        persist_capture_device=persist_capture_device_action,
        volume_up=volume_up_action,
        volume_down=volume_down_action,
        mute=mute_action,
        unmute=unmute_action,
    )


class PowerScreen(Screen):
    """Compact Setup screen for power and device care state."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        state_provider: Callable[[], PowerScreenState] | None = None,
        actions: PowerScreenActions | None = None,
    ) -> None:
        super().__init__(display, context, "PowerStatus")
        self._state_provider = state_provider or build_power_screen_state_provider()
        self._actions = actions or PowerScreenActions()
        self.page_index = 0
        self.selected_row = 0
        self.in_detail = False
        self._lvgl_view: "ScreenView | None" = None
        self._last_gps_query_at = 0.0
        self._gps_refresh_interval_seconds = 2.0

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        # Returning to Setup should not trap users in the Voice page.
        self.page_index = 0
        self.selected_row = 0
        self.in_detail = False
        if self._actions.refresh_voice_devices is not None:
            self._actions.refresh_voice_devices()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving Setup."""
        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglPowerView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the active Setup page."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        state = self._get_state()
        pages = self._build_pages_for_display(state=state)
        self.page_index %= len(pages)
        active_page = pages[self.page_index]
        picker_mode = not self.is_one_button_mode() and not self.in_detail
        render_backdrop(self.display, "setup")
        render_status_bar(self.display, self.context, show_time=False)
        page_text = f"{self.page_index + 1}/{len(pages)}"

        halo_size = 44
        halo_left = (self.display.WIDTH - halo_size) // 2
        halo_top = self.display.STATUS_BAR_HEIGHT + 10
        rounded_panel(
            self.display,
            halo_left,
            halo_top,
            halo_left + halo_size,
            halo_top + halo_size,
            fill=(73, 77, 89),
            outline=None,
            radius=22,
        )
        icon_key = self._page_icon_key(active_page.title)
        draw_icon(self.display, icon_key, halo_left + 10, halo_top + 10, 24, (225, 228, 234))

        title_y = halo_top + halo_size + 8
        header_title = "Setup" if picker_mode else active_page.title
        title_width, _ = self.display.get_text_size(header_title, 18)
        self.display.text(
            header_title,
            (self.display.WIDTH - title_width) // 2,
            title_y,
            color=INK,
            font_size=18,
        )

        page_width, _ = self.display.get_text_size(page_text, 10)
        rounded_panel(
            self.display,
            self.display.WIDTH - page_width - 34,
            halo_top + 10,
            self.display.WIDTH - 18,
            halo_top + 30,
            fill=SETUP.accent_dim,
            outline=None,
            radius=10,
        )
        self.display.text(
            page_text,
            self.display.WIDTH - page_width - 26,
            halo_top + 15,
            color=SETUP.accent,
            font_size=10,
        )

        if not picker_mode:
            visible_rows, visible_selected_index = self._visible_rows_for_page(active_page)
            row_y = title_y + 18
            row_height = 20
            row_gap = 4
            max_row_bottom = self.display.HEIGHT - 60
            for row_index, (label, value) in enumerate(visible_rows):
                row_bottom = row_y + row_height
                if row_bottom > max_row_bottom:
                    break
                is_selected = (
                    visible_selected_index is not None and row_index == visible_selected_index
                )
                rounded_panel(
                    self.display,
                    16,
                    row_y,
                    self.display.WIDTH - 16,
                    row_bottom,
                    fill=SETUP.accent_dim if is_selected else SURFACE_RAISED,
                    outline=None,
                    radius=11,
                )
                label_text = text_fit(self.display, label, 92, 10)
                value_text = text_fit(self.display, value, self.display.WIDTH - 130, 12)
                self.display.text(
                    label_text,
                    26,
                    row_y + 5,
                    color=SETUP.accent if is_selected else MUTED,
                    font_size=10,
                )
                value_width, _ = self.display.get_text_size(value_text, 12)
                self.display.text(
                    value_text,
                    self.display.WIDTH - value_width - 26,
                    row_y + 4,
                    color=INK,
                    font_size=12,
                )
                row_y += row_height + row_gap
        else:
            panel_top = title_y + 20
            panel_bottom = self.display.HEIGHT - 60
            rounded_panel(
                self.display,
                12,
                panel_top,
                self.display.WIDTH - 12,
                panel_bottom,
                fill=(30, 34, 41),
                outline=None,
                radius=24,
            )

            item_height = 40
            row_top = panel_top + 10
            row_bottom = panel_bottom - 8
            available = max(0, row_bottom - row_top)
            max_visible = max(1, min(len(pages), available // item_height))

            for offset, (index, page) in enumerate(
                self._visible_picker_pages(pages, max_items=max_visible)
            ):
                title = page.title
                subtitle = self._page_subtitle(page.title)
                icon = self._page_icon_key(page.title)
                y1 = row_top + (offset * item_height)
                y2 = y1 + (item_height - 4)
                selected = index == self.page_index
                rounded_panel(
                    self.display,
                    16,
                    y1,
                    self.display.WIDTH - 16,
                    y2,
                    fill=(250, 250, 250) if selected else SURFACE_RAISED,
                    outline=None,
                    radius=14,
                )

                icon_color = SETUP.accent if selected else MUTED
                draw_icon(self.display, icon, 26, y1 + 8, 16, icon_color)
                title_color = (30, 34, 41) if selected else INK
                subtitle_color = (90, 96, 108) if selected else MUTED
                self.display.text(title, 48, y1 + 6, color=title_color, font_size=14)
                self.display.text(
                    text_fit(self.display, subtitle, self.display.WIDTH - 90, 11),
                    48,
                    y1 + 22,
                    color=subtitle_color,
                    font_size=11,
                )

        self._render_page_dots(total_pages=len(pages))

        help_text = self._instruction_text(active_page)
        render_footer(self.display, help_text, mode="setup")
        self.display.update()

    def _page_icon_key(self, title: str) -> str:
        """Return the page hero icon for the current Setup page."""

        if title == "Power":
            return "battery"
        if title == "Time":
            return "clock"
        if title == "Voice":
            return "voice_note"
        if title == "Network":
            return "signal"
        if title == "GPS":
            return "care"
        return "care"

    @staticmethod
    def _page_subtitle(title: str) -> str:
        """Return the short subtitle shown in the Setup page picker."""

        if title == "Power":
            return "Battery and charging"
        if title == "Network":
            return "Cellular status"
        if title == "GPS":
            return "Location fix"
        if title == "Time":
            return "RTC and alarms"
        if title == "Care":
            return "Screen and watchdog"
        if title == "Voice":
            return "Commands and audio"
        return ""

    def _visible_picker_pages(
        self,
        pages: list[PowerPage],
        *,
        max_items: int,
    ) -> list[tuple[int, PowerPage]]:
        """Return the visible page-picker window around the current page."""

        if not pages:
            return []

        max_items = max(1, min(max_items, len(pages)))
        start_index = max(0, min(self.page_index - (max_items // 2), len(pages) - max_items))
        return [(start_index + offset, pages[start_index + offset]) for offset in range(max_items)]

    def _visible_rows_for_page(
        self,
        page: PowerPage,
        *,
        max_rows: int | None = None,
    ) -> tuple[list[tuple[str, str]], int | None]:
        """Return the visible row window plus the selected index inside it."""

        if max_rows is None:
            max_rows = self._row_capacity_for_page(page)

        if not page.rows:
            self.selected_row = 0
            return [], None

        self.selected_row %= len(page.rows)
        if not page.interactive or len(page.rows) <= max_rows:
            return page.rows[:max_rows], (self.selected_row if page.interactive else None)

        start = max(0, self.selected_row - (max_rows - 1))
        end = min(len(page.rows), start + max_rows)
        start = max(0, end - max_rows)
        visible_rows = page.rows[start:end]
        return visible_rows, self.selected_row - start

    def _row_capacity_for_page(self, page: PowerPage) -> int:
        """Return how many rows the current display/layout can safely show."""

        if self.display.is_portrait() and not page.interactive:
            return 5
        return 4

    def _render_page_dots(self, *, total_pages: int) -> None:
        """Render the compact Setup page-position dots."""

        if total_pages <= 1:
            return

        dots_width = max(0, (total_pages - 1) * 10)
        dots_x = (self.display.WIDTH - dots_width) // 2
        dots_y = self.display.HEIGHT - 42
        for index in range(total_pages):
            color = SETUP.accent if index == self.page_index else MUTED
            self.display.circle(dots_x + (index * 10), dots_y, 2, fill=color)

    def build_pages(
        self,
        *,
        snapshot: Optional["PowerSnapshot"] = None,
        status: dict[str, object] | None = None,
        state: PowerScreenState | None = None,
    ) -> list[PowerPage]:
        """Build compact setup pages for rendering and tests."""
        resolved_state = state or self._get_state()
        resolved_snapshot = snapshot if snapshot is not None else resolved_state.snapshot
        resolved_status = status if status is not None else resolved_state.status
        battery_rows = self._build_battery_rows(snapshot=resolved_snapshot)
        runtime_rows = self._build_runtime_rows(
            snapshot=resolved_snapshot,
            status=resolved_status,
        )

        pages = [
            PowerPage(title="Power", rows=battery_rows[:4]),
        ]
        if resolved_state.network_enabled:
            pages.append(PowerPage(title="Network", rows=self._build_network_rows(resolved_state)))
            pages.append(PowerPage(title="GPS", rows=self._build_gps_rows(resolved_state)))
        voice_interactive = not self.is_one_button_mode()
        pages.extend(
            [
                PowerPage(title="Time", rows=battery_rows[4:6] + runtime_rows[:2]),
                PowerPage(title="Care", rows=runtime_rows[2:]),
                PowerPage(
                    title="Voice",
                    rows=self._build_voice_rows(summary_mode=not voice_interactive),
                    interactive=voice_interactive,
                ),
            ]
        )
        return pages

    def _build_pages_for_display(
        self,
        *,
        snapshot: Optional["PowerSnapshot"] = None,
        status: dict[str, object] | None = None,
        state: PowerScreenState | None = None,
    ) -> list[PowerPage]:
        """Build pages and opportunistically refresh GPS when the GPS page is active."""

        resolved_state = state or self._get_state()
        pages = self.build_pages(
            snapshot=snapshot,
            status=status,
            state=resolved_state,
        )
        if not pages:
            return pages

        self.page_index %= len(pages)
        active_page = pages[self.page_index]
        if active_page.title != "GPS":
            return pages

        if self._maybe_refresh_gps_page():
            pages = self.build_pages(state=self._get_state())
        return pages

    def _build_voice_rows(self, *, summary_mode: bool = False) -> list[tuple[str, str]]:
        """Build the voice-related settings page."""

        if self.context is None:
            rows = [
                ("Voice Cmds", "Unknown"),
                ("AI Requests", "Unknown"),
                ("Screen Read", "Unknown"),
                ("Speaker", "Auto"),
                ("Mic Device", "Auto"),
                ("Mic", "Unknown"),
                ("Volume", "--"),
            ]
            if summary_mode:
                return [
                    ("Voice Cmds", "Unknown"),
                    ("AI Requests", "Unknown"),
                    ("Screen Read", "Unknown"),
                    ("Mic", "Unknown"),
                    ("Volume", "--"),
                ]
            return rows

        voice = self.context.voice
        rows = [
            ("Voice Cmds", "On" if voice.commands_enabled else "Off"),
            ("AI Requests", "On" if voice.ai_requests_enabled else "Off"),
            ("Screen Read", "On" if voice.screen_read_enabled else "Off"),
            ("Speaker", format_device_label(voice.speaker_device_id)),
            ("Mic Device", format_device_label(voice.capture_device_id)),
            ("Mic", "Muted" if voice.mic_muted else "Live"),
            ("Volume", f"{voice.output_volume}%"),
        ]
        if summary_mode:
            return [
                ("Voice Cmds", rows[0][1]),
                ("AI Requests", rows[1][1]),
                ("Screen Read", rows[2][1]),
                ("Mic", rows[5][1]),
                ("Volume", rows[6][1]),
            ]
        return rows

    def _build_network_rows(
        self,
        state: PowerScreenState | None = None,
    ) -> list[tuple[str, str]]:
        """Build the cellular network status page."""
        resolved_state = state or self._get_state()
        return list(resolved_state.network_rows or (("Status", "Disabled"),))

    def _build_gps_rows(
        self,
        state: PowerScreenState | None = None,
    ) -> list[tuple[str, str]]:
        """Build the GPS status page."""
        resolved_state = state or self._get_state()
        return list(
            resolved_state.gps_rows
            or (
                ("Fix", "Disabled"),
                ("Lat", "--"),
                ("Lng", "--"),
                ("Alt", "--"),
                ("Speed", "--"),
            )
        )

    def _maybe_refresh_gps_page(self) -> bool:
        """Query GPS when the user is actively viewing the GPS page."""

        now = time.monotonic()
        if now - self._last_gps_query_at < self._gps_refresh_interval_seconds:
            return False

        self._last_gps_query_at = now
        try:
            coord = False if self._actions.refresh_gps is None else self._actions.refresh_gps()
        except Exception as exc:
            logger.warning("GPS refresh failed on Setup screen: {}", exc)
            return False

        if self.context is not None:
            self.context.update_network_status(gps_has_fix=bool(coord))
        return bool(coord)

    def _get_state(self) -> PowerScreenState:
        """Return the prepared state for the current render."""

        try:
            return self._state_provider()
        except Exception:
            return PowerScreenState()

    def _get_snapshot(self) -> Optional["PowerSnapshot"]:
        """Return the latest power snapshot."""
        return self._get_state().snapshot

    def _get_status(self) -> dict[str, object]:
        """Return the latest app runtime/policy status."""
        return dict(self._get_state().status)

    def _build_battery_rows(self, *, snapshot: Optional["PowerSnapshot"]) -> list[tuple[str, str]]:
        """Build the power-focused page."""
        if snapshot is None:
            return [
                ("Source", "Unavailable"),
                ("Battery", "Unknown"),
                ("Charging", "Unknown"),
                ("RTC", "Unknown"),
                ("Alarm", "Unknown"),
            ]

        if not snapshot.available:
            error = snapshot.error or "Unavailable"
            return [
                ("Source", snapshot.source),
                ("Model", snapshot.device.model or "Unknown"),
                ("Status", "Offline"),
                ("Reason", self._truncate(error, 18)),
                ("RTC", self._format_datetime(snapshot.rtc.time)),
                ("Alarm", self._format_alarm(snapshot)),
            ]

        return [
            ("Model", snapshot.device.model or "Unknown"),
            ("Battery", self._format_battery(snapshot)),
            ("Charging", self._format_charging(snapshot)),
            ("External", self._format_external_power(snapshot)),
            ("Voltage", self._format_voltage(snapshot)),
            ("RTC", self._format_datetime(snapshot.rtc.time)),
            ("Alarm", self._format_alarm(snapshot)),
        ]

    def _build_runtime_rows(
        self,
        *,
        snapshot: Optional["PowerSnapshot"],
        status: dict[str, object],
    ) -> list[tuple[str, str]]:
        """Build the care/runtime page."""
        warning_percent = self._format_percent(status.get("warning_threshold_percent"))
        critical_percent = self._format_percent(status.get("critical_shutdown_percent"))
        delay_seconds = self._format_duration_short(status.get("shutdown_delay_seconds"))
        shutdown_value = "Ready"
        if status.get("shutdown_pending"):
            shutdown_value = f"In {self._format_duration_short(status.get('shutdown_in_seconds'))}"

        rows = [
            ("Uptime", self._format_duration_short(status.get("app_uptime_seconds"))),
            ("Screen", self._format_screen_state(status)),
            ("Idle", self._format_duration_short(status.get("screen_idle_seconds"))),
            ("Timeout", self._format_duration_short(status.get("screen_timeout_seconds"))),
            ("Warn/Crit", f"{warning_percent}/{critical_percent}"),
            (
                "Shutdown",
                shutdown_value if delay_seconds == "0s" else f"{shutdown_value} ({delay_seconds})",
            ),
            ("Watchdog", self._format_watchdog(status)),
        ]

        if snapshot is not None and snapshot.shutdown.safe_shutdown_level_percent is not None:
            rows[4] = (
                "Warn/Crit",
                f"{warning_percent}/{self._format_percent(snapshot.shutdown.safe_shutdown_level_percent)}",
            )
        return rows

    def _format_battery(self, snapshot: "PowerSnapshot") -> str:
        """Format battery percentage with a compact suffix."""
        level = snapshot.battery.level_percent
        if level is None:
            return "Unknown"
        suffix = " chg" if snapshot.battery.charging else ""
        return f"{round(level)}%{suffix}"

    def _format_charging(self, snapshot: "PowerSnapshot") -> str:
        """Format charging state."""
        charging = snapshot.battery.charging
        if charging is None:
            return "Unknown"
        return "Charging" if charging else "Idle"

    def _format_external_power(self, snapshot: "PowerSnapshot") -> str:
        """Format whether USB/external power is present."""
        plugged = snapshot.battery.power_plugged
        if plugged is None:
            return "Unknown"
        return "Plugged" if plugged else "Battery"

    def _format_voltage(self, snapshot: "PowerSnapshot") -> str:
        """Format voltage with optional temperature hint."""
        voltage = snapshot.battery.voltage_volts
        temperature = snapshot.battery.temperature_celsius
        if voltage is None and temperature is None:
            return "Unknown"
        if voltage is None:
            return f"{temperature:.1f} C"
        if temperature is None:
            return f"{voltage:.2f} V"
        return f"{voltage:.2f}V {temperature:.0f}C"

    def _format_alarm(self, snapshot: "PowerSnapshot") -> str:
        """Format the current RTC alarm state."""
        if snapshot.rtc.alarm_enabled is not True:
            return "Off"
        if snapshot.rtc.alarm_time is None:
            return "On"
        return snapshot.rtc.alarm_time.strftime("%H:%M")

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        """Format one datetime value for compact screen use."""
        if value is None:
            return "Unknown"
        return value.strftime("%m-%d %H:%M")

    @staticmethod
    def _format_duration_short(value: object) -> str:
        """Format short durations like 95 seconds -> 1m35s."""
        if value is None:
            return "0s"
        total_seconds = max(0, int(float(value)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h{minutes:02d}m"
        if minutes > 0:
            return f"{minutes}m{seconds:02d}s"
        return f"{seconds}s"

    @staticmethod
    def _format_percent(value: object) -> str:
        """Format a percentage-like value for screen use."""
        if value is None:
            return "--"
        return f"{int(round(float(value)))}%"

    @staticmethod
    def _format_watchdog(status: dict[str, object]) -> str:
        """Format the current watchdog state."""
        if not status.get("watchdog_enabled"):
            return "Off"
        if status.get("watchdog_feed_suppressed"):
            return "Paused"
        if status.get("watchdog_active"):
            return "Active"
        return "Ready"

    @staticmethod
    def _format_screen_state(status: dict[str, object]) -> str:
        """Format current display-awake plus cumulative screen-on time."""
        state = "Awake" if status.get("screen_awake") else "Sleep"
        screen_on = PowerScreen._format_duration_short(status.get("screen_on_seconds"))
        return f"{state} {screen_on}"

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate strings that would overflow narrow labels."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _instruction_text(self, page: PowerPage) -> str:
        """Return footer hints for the current page."""

        if self.is_one_button_mode():
            return "Tap page / Hold back"

        if not self.in_detail:
            return "A open | B back | X/Y move"

        if page.interactive:
            return "A change | B back | X/Y item | L/R page"
        return "A page | B back | X/Y page"

    def prefers_simple_one_button_navigation(self) -> bool:
        """Use fast page-to-page taps on Whisplay Setup screens."""
        return self.is_one_button_mode()

    def _active_pages(self) -> list[PowerPage]:
        """Return the current page list for navigation helpers."""

        return self.build_pages(state=self._get_state())

    def _active_page(self) -> PowerPage:
        """Return the current active page."""

        pages = self._active_pages()
        self.page_index %= len(pages)
        page = pages[self.page_index]
        if page.rows:
            self.selected_row %= len(page.rows)
        else:
            self.selected_row = 0
        return page

    def _is_voice_page(self) -> bool:
        """Return True when the interactive voice settings page is active."""

        return self.in_detail and self._active_page().interactive

    def _select_next_row(self) -> None:
        """Move to the next row inside an interactive page."""

        page = self._active_page()
        if not page.rows:
            return
        self.selected_row = (self.selected_row + 1) % len(page.rows)

    def _select_previous_row(self) -> None:
        """Move to the previous row inside an interactive page."""

        page = self._active_page()
        if not page.rows:
            return
        self.selected_row = (self.selected_row - 1) % len(page.rows)

    def _apply_voice_setting(self, direction: int = 1) -> None:
        """Toggle or adjust the selected voice setting."""

        if self.context is None:
            return

        row_index = self.selected_row
        if row_index == 0:
            self.context.configure_voice(commands_enabled=not self.context.voice.commands_enabled)
            return
        if row_index == 1:
            self.context.configure_voice(
                ai_requests_enabled=not self.context.voice.ai_requests_enabled
            )
            return
        if row_index == 2:
            self.context.configure_voice(
                screen_read_enabled=not self.context.voice.screen_read_enabled
            )
            return
        if row_index == 3:
            self._cycle_speaker_device(direction)
            return
        if row_index == 4:
            self._cycle_capture_device(direction)
            return
        if row_index == 5:
            self._apply_mic_state(not self.context.voice.mic_muted)
            return
        current = None
        if direction > 0 and self._actions.volume_up is not None:
            current = self._actions.volume_up(5)
        elif direction < 0 and self._actions.volume_down is not None:
            current = self._actions.volume_down(5)
        else:
            volume = self.context.voice.output_volume + (5 * direction)
            self.context.set_volume(max(0, min(100, volume)))
            return
        self._sync_context_output_volume(current)

    def _playback_device_options(self) -> list[str | None]:
        """Return selectable playback options, with None representing Auto."""

        return [None, *self._get_state().playback_devices]

    def _capture_device_options(self) -> list[str | None]:
        """Return selectable capture options, with None representing Auto."""

        return [None, *self._get_state().capture_devices]

    @staticmethod
    def _cycle_option(
        options: list[str | None],
        current: str | None,
        direction: int,
    ) -> str | None:
        if not options:
            return current
        try:
            index = options.index(current)
        except ValueError:
            index = 0
        next_index = (index + (1 if direction >= 0 else -1)) % len(options)
        return options[next_index]

    def _cycle_speaker_device(self, direction: int) -> None:
        if self.context is None:
            return
        next_device = self._cycle_option(
            self._playback_device_options(),
            self.context.voice.speaker_device_id,
            direction,
        )
        self.context.configure_voice(speaker_device_id=next_device)
        if self._actions.persist_speaker_device is not None:
            self._actions.persist_speaker_device(next_device)

    def _cycle_capture_device(self, direction: int) -> None:
        if self.context is None:
            return
        next_device = self._cycle_option(
            self._capture_device_options(),
            self.context.voice.capture_device_id,
            direction,
        )
        self.context.configure_voice(capture_device_id=next_device)
        if self._actions.persist_capture_device is not None:
            self._actions.persist_capture_device(next_device)

    def _next_page(self) -> None:
        """Advance to the next page with wraparound."""
        self.page_index = (self.page_index + 1) % len(self._active_pages())
        self.selected_row = 0

    def _previous_page(self) -> None:
        """Return to the previous page with wraparound."""
        self.page_index = (self.page_index - 1) % len(self._active_pages())
        self.selected_row = 0

    def on_advance(self, data=None) -> None:
        """Single-button tap cycles pages."""
        if self.is_one_button_mode():
            self._next_page()
            return
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            # Voice is an interactive list; wrap within the page instead of
            # "falling through" into Power/Time/Care.
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row >= len(page.rows) - 1:
                self.selected_row = 0
            else:
                self._select_next_row()
            return
        self._next_page()

    def on_select(self, data=None) -> None:
        """Open the selected page, or adjust interactive settings in detail mode."""
        if self.is_one_button_mode():
            self._next_page()
            return
        if not self.in_detail:
            self.in_detail = True
            self.selected_row = 0
            return
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        if self.is_one_button_mode():
            self.request_route("back")
            return
        if self.in_detail:
            self.in_detail = False
            self.selected_row = 0
            return
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Up goes to the previous page."""
        if not self.in_detail:
            self._previous_page()
            return
        if self._is_voice_page():
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row == 0:
                self.selected_row = len(page.rows) - 1
            else:
                self._select_previous_row()
            return
        self._previous_page()

    def on_down(self, data=None) -> None:
        """Down goes to the next page."""
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row >= len(page.rows) - 1:
                self.selected_row = 0
            else:
                self._select_next_row()
            return
        self._next_page()

    def on_left(self, data=None) -> None:
        """Left goes to the previous page."""
        if not self.in_detail:
            self._previous_page()
            return
        if self._is_voice_page():
            self._apply_voice_setting(-1)
            return
        self._previous_page()

    def on_right(self, data=None) -> None:
        """Right goes to the next page."""
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def _apply_mic_state(self, muted: bool) -> None:
        """Keep the cached voice mic state aligned with the live VoIP mute path when available."""

        if self.context is not None:
            self.context.set_mic_muted(muted)
        action = self._actions.mute if muted else self._actions.unmute
        if action is not None:
            action()

    def _sync_context_output_volume(self, volume: int | None) -> None:
        """Refresh cached volume state after routing through the real output path."""

        if volume is None or self.context is None:
            return
        self.context.cache_output_volume(volume)
