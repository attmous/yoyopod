"""Setup screen for power, runtime, and device care."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.system.lvgl import LvglPowerView
from yoyopy.ui.screens.theme import (
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
    from yoyopy.app_context import AppContext
    from yoyopy.power import PowerManager, PowerSnapshot
    from yoyopy.ui.screens import ScreenView


@dataclass(frozen=True, slots=True)
class PowerPage:
    """One setup page made of compact rows."""

    title: str
    rows: list[tuple[str, str]]
    interactive: bool = False


class PowerScreen(Screen):
    """Compact Setup screen for power and device care state."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        power_manager: Optional["PowerManager"] = None,
        network_manager: Optional[object] = None,
        status_provider: Optional[Callable[[], dict[str, object]]] = None,
        volume_up_action: Optional[Callable[[int], int | None]] = None,
        volume_down_action: Optional[Callable[[int], int | None]] = None,
        mute_action: Optional[Callable[[], bool]] = None,
        unmute_action: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(display, context, "PowerStatus")
        self.power_manager = power_manager
        self.network_manager = network_manager
        self.status_provider = status_provider or (lambda: {})
        self.volume_up_action = volume_up_action
        self.volume_down_action = volume_down_action
        self.mute_action = mute_action
        self.unmute_action = unmute_action
        self.page_index = 0
        self.selected_row = 0
        self._lvgl_view: "ScreenView | None" = None
        self._last_gps_query_at = 0.0
        self._gps_refresh_interval_seconds = 2.0

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
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

        snapshot = self._get_snapshot()
        status = self._get_status()
        pages = self._build_pages_for_display(snapshot=snapshot, status=status)
        self.page_index %= len(pages)
        active_page = pages[self.page_index]
        visible_rows, visible_selected_index = self._visible_rows_for_page(active_page)
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
        draw_icon(
            self.display,
            self._page_icon_key(active_page.title),
            halo_left + 10,
            halo_top + 10,
            24,
            (225, 228, 234),
        )

        title_y = halo_top + halo_size + 8
        title_width, _ = self.display.get_text_size(active_page.title, 18)
        self.display.text(
            active_page.title,
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

        row_y = title_y + 18
        row_height = 20
        row_gap = 4
        max_row_bottom = self.display.HEIGHT - 60
        for row_index, (label, value) in enumerate(visible_rows):
            row_bottom = row_y + row_height
            if row_bottom > max_row_bottom:
                break
            is_selected = visible_selected_index is not None and row_index == visible_selected_index
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

    def _visible_rows_for_page(
        self,
        page: PowerPage,
        *,
        max_rows: int = 4,
    ) -> tuple[list[tuple[str, str]], int | None]:
        """Return the visible row window plus the selected index inside it."""

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
        snapshot: Optional["PowerSnapshot"],
        status: dict[str, object],
    ) -> list[PowerPage]:
        """Build compact setup pages for rendering and tests."""
        battery_rows = self._build_battery_rows(snapshot=snapshot)
        runtime_rows = self._build_runtime_rows(snapshot=snapshot, status=status)

        pages = [
            PowerPage(title="Power", rows=battery_rows[:4]),
        ]
        if self.network_manager is not None and self.network_manager.config.enabled:
            pages.append(PowerPage(title="Network", rows=self._build_network_rows()))
            pages.append(PowerPage(title="GPS", rows=self._build_gps_rows()))
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
        snapshot: Optional["PowerSnapshot"],
        status: dict[str, object],
    ) -> list[PowerPage]:
        """Build pages and opportunistically refresh GPS when the GPS page is active."""

        pages = self.build_pages(snapshot=snapshot, status=status)
        if not pages:
            return pages

        self.page_index %= len(pages)
        active_page = pages[self.page_index]
        if active_page.title != "GPS":
            return pages

        if self._maybe_refresh_gps_page():
            pages = self.build_pages(snapshot=snapshot, status=status)
        return pages

    def _build_voice_rows(self, *, summary_mode: bool = False) -> list[tuple[str, str]]:
        """Build the voice-related settings page."""

        if self.context is None:
            rows = [
                ("Voice Cmds", "Unknown"),
                ("AI Requests", "Unknown"),
                ("Screen Read", "Unknown"),
                ("Mic", "Unknown"),
                ("Volume", "--"),
            ]
            return rows[:4] if summary_mode else rows

        voice = self.context.voice
        rows = [
            ("Voice Cmds", "On" if voice.commands_enabled else "Off"),
            ("AI Requests", "On" if voice.ai_requests_enabled else "Off"),
            ("Screen Read", "On" if voice.screen_read_enabled else "Off"),
            ("Mic", "Muted" if voice.mic_muted else "Live"),
            ("Volume", f"{voice.output_volume}%"),
        ]
        if summary_mode:
            return [
                rows[0],
                rows[1],
                rows[3],
                rows[4],
            ]
        return rows

    def _build_network_rows(self) -> list[tuple[str, str]]:
        """Build the cellular network status page."""
        if self.network_manager is None or not self.network_manager.config.enabled:
            return [("Status", "Disabled")]
        state = self.network_manager.modem_state
        from yoyopy.network.models import ModemPhase

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

    def _build_gps_rows(self) -> list[tuple[str, str]]:
        """Build the GPS status page."""
        if self.network_manager is None or not self.network_manager.config.enabled:
            return [
                ("Fix", "Disabled"),
                ("Lat", "--"),
                ("Lng", "--"),
                ("Alt", "--"),
                ("Speed", "--"),
            ]
        if not self.network_manager.config.gps_enabled:
            return [
                ("Fix", "Disabled"),
                ("Lat", "--"),
                ("Lng", "--"),
                ("Alt", "--"),
                ("Speed", "--"),
            ]
        state = self.network_manager.modem_state
        from yoyopy.network.models import ModemPhase

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

    def _maybe_refresh_gps_page(self) -> bool:
        """Query GPS when the user is actively viewing the GPS page."""

        if self.network_manager is None or not self.network_manager.config.enabled:
            return False
        if not self.network_manager.config.gps_enabled:
            return False

        query_gps = getattr(self.network_manager, "query_gps", None)
        if not callable(query_gps):
            return False

        now = time.monotonic()
        if now - self._last_gps_query_at < self._gps_refresh_interval_seconds:
            return False

        self._last_gps_query_at = now
        try:
            coord = query_gps()
        except Exception as exc:
            logger.warning("GPS refresh failed on Setup screen: {}", exc)
            return False

        if self.context is not None:
            self.context.update_network_status(gps_has_fix=coord is not None)
        return coord is not None

    def _get_snapshot(self) -> Optional["PowerSnapshot"]:
        """Return the latest power snapshot."""
        if self.power_manager is None:
            return None
        return self.power_manager.get_snapshot()

    def _get_status(self) -> dict[str, object]:
        """Return the latest app runtime/policy status."""
        try:
            return self.status_provider()
        except Exception:
            return {}

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

        if page.interactive:
            if self.is_one_button_mode():
                return "Tap next / 2x change / Hold back"
            return "A change | B back | X/Y item | L/R page"
        return "Tap page / Hold back" if self.is_one_button_mode() else "A page | B back | X/Y page"

    def prefers_simple_one_button_navigation(self) -> bool:
        """Use fast page-to-page taps on Whisplay Setup screens."""
        return self.is_one_button_mode()

    def _active_pages(self) -> list[PowerPage]:
        """Return the current page list for navigation helpers."""

        return self.build_pages(snapshot=self._get_snapshot(), status=self._get_status())

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

        return self._active_page().interactive

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
            self._apply_mic_state(not self.context.voice.mic_muted)
            return
        current = None
        if direction > 0 and self.volume_up_action is not None:
            current = self.volume_up_action(5)
        elif direction < 0 and self.volume_down_action is not None:
            current = self.volume_down_action(5)
        else:
            volume = self.context.voice.output_volume + (5 * direction)
            self.context.set_volume(max(0, min(100, volume)))
            return
        self._sync_context_output_volume(current)

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
        if self._is_voice_page():
            if self.is_one_button_mode():
                page = self._active_page()
                if self.selected_row >= len(page.rows) - 1:
                    self._next_page()
                else:
                    self._select_next_row()
                return
            self._select_next_row()
            return
        self._next_page()

    def on_select(self, data=None) -> None:
        """Select also cycles pages."""
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Up goes to the previous page."""
        if self._is_voice_page():
            self._select_previous_row()
            return
        self._previous_page()

    def on_down(self, data=None) -> None:
        """Down goes to the next page."""
        if self._is_voice_page():
            self._select_next_row()
            return
        self._next_page()

    def on_left(self, data=None) -> None:
        """Left goes to the previous page."""
        if self._is_voice_page():
            self._apply_voice_setting(-1)
            return
        self._previous_page()

    def on_right(self, data=None) -> None:
        """Right goes to the next page."""
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def _apply_mic_state(self, muted: bool) -> None:
        """Keep the cached voice mic state aligned with the live VoIP mute path when available."""

        if self.context is not None:
            self.context.set_mic_muted(muted)
        action = self.mute_action if muted else self.unmute_action
        if action is not None:
            action()

    def _sync_context_output_volume(self, volume: int | None) -> None:
        """Refresh cached volume state after routing through the real output path."""

        if volume is None or self.context is None:
            return
        self.context.playback.volume = volume
        self.context.voice.output_volume = volume
