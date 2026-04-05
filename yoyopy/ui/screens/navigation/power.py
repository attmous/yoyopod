"""Setup screen for power, runtime, and device care."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import INK, MUTED, SETUP, SURFACE, render_footer, render_header, rounded_panel, text_fit

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.power import PowerManager, PowerSnapshot


@dataclass(frozen=True, slots=True)
class PowerPage:
    """One setup page made of compact rows."""

    title: str
    rows: list[tuple[str, str]]


class PowerScreen(Screen):
    """Compact Setup screen for power and device care state."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        power_manager: Optional["PowerManager"] = None,
        status_provider: Optional[Callable[[], dict[str, object]]] = None,
    ) -> None:
        super().__init__(display, context, "PowerStatus")
        self.power_manager = power_manager
        self.status_provider = status_provider or (lambda: {})
        self.page_index = 0

    def render(self) -> None:
        """Render the active Setup page."""
        snapshot = self._get_snapshot()
        status = self._get_status()
        pages = self.build_pages(snapshot=snapshot, status=status)
        self.page_index %= len(pages)
        active_page = pages[self.page_index]
        page_text = f"{self.page_index + 1}/{len(pages)}"

        content_top = render_header(
            self.display,
            self.context,
            mode="setup",
            title="Setup",
            subtitle="Power, sleep, and device care.",
            icon="setup",
            page_text=page_text,
            show_time=False,
        )

        panel_top = content_top + 8
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=24,
        )

        pill_width, _ = self.display.get_text_size(active_page.title.upper(), 10)
        rounded_panel(
            self.display,
            22,
            panel_top + 10,
            22 + pill_width + 18,
            panel_top + 32,
            fill=SETUP.accent_dim,
            outline=None,
            radius=12,
        )
        self.display.text(active_page.title.upper(), 31, panel_top + 16, color=SETUP.accent, font_size=10)

        row_y = panel_top + 46
        row_gap = 24 if self.display.is_portrait() else 22
        for label, value in active_page.rows:
            label_text = text_fit(self.display, label, 90, 11)
            value_text = text_fit(self.display, value, self.display.WIDTH - 120, 12)
            self.display.text(label_text, 22, row_y, color=MUTED, font_size=11)
            value_width, _ = self.display.get_text_size(value_text, 12)
            self.display.text(value_text, self.display.WIDTH - value_width - 22, row_y, color=INK, font_size=12)
            row_y += row_gap

        help_text = "Tap page | Double page | Hold back" if self.is_one_button_mode() else "A page | B back | X/Y page"
        render_footer(self.display, help_text, mode="setup")
        self.display.update()

    def build_pages(
        self,
        *,
        snapshot: Optional["PowerSnapshot"],
        status: dict[str, object],
    ) -> list[PowerPage]:
        """Build compact setup pages for rendering and tests."""
        return [
            PowerPage(title="Power", rows=self._build_battery_rows(snapshot=snapshot)),
            PowerPage(title="Care", rows=self._build_runtime_rows(snapshot=snapshot, status=status)),
        ]

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
            ("Shutdown", shutdown_value if delay_seconds == "0s" else f"{shutdown_value} ({delay_seconds})"),
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

    def _next_page(self) -> None:
        """Advance to the next page with wraparound."""
        self.page_index = (self.page_index + 1) % 2

    def _previous_page(self) -> None:
        """Return to the previous page with wraparound."""
        self.page_index = (self.page_index - 1) % 2

    def on_advance(self, data=None) -> None:
        """Single-button tap cycles pages."""
        self._next_page()

    def on_select(self, data=None) -> None:
        """Select also cycles pages."""
        self._next_page()

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Up goes to the previous page."""
        self._previous_page()

    def on_down(self, data=None) -> None:
        """Down goes to the next page."""
        self._next_page()

    def on_left(self, data=None) -> None:
        """Left goes to the previous page."""
        self._previous_page()

    def on_right(self, data=None) -> None:
        """Right goes to the next page."""
        self._next_page()
