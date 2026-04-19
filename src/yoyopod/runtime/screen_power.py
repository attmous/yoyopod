"""Screen wake/sleep, runtime metrics, and power overlay helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from yoyopod.events import ScreenChangedEvent, UserActivityEvent
from yoyopod.power import LowBatteryWarningRaised
from yoyopod.runtime.models import PowerAlert

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class ScreenPowerService:
    """Own screen-power policy and lightweight power overlay rendering."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def resolve_screen_timeout_seconds(self) -> float:
        """Resolve the effective inactivity timeout used to sleep the screen."""
        if self.app.app_settings is None:
            return 0.0

        display_timeout = max(
            0.0,
            float(self.app.app_settings.display.backlight_timeout_seconds),
        )
        if display_timeout > 0.0:
            return display_timeout

        return max(0.0, float(self.app.app_settings.ui.screen_timeout_seconds))

    def resolve_active_brightness(self) -> float:
        """Resolve the active display brightness as a normalized 0.0-1.0 value."""
        if self.app.app_settings is None:
            return 1.0

        brightness = max(0, min(100, int(self.app.app_settings.display.brightness)))
        return brightness / 100.0

    def configure_screen_power(self, initial_now: float | None = None) -> None:
        """Initialize screen timeout and usage tracking state."""
        now = time.monotonic() if initial_now is None else initial_now
        self.app._app_started_at = now
        self.app._last_user_activity_at = now
        self.app._screen_on_started_at = now
        self.app._screen_on_accumulated_seconds = 0.0
        self.app._screen_awake = True

        if self.app.display is not None:
            self.app.display.set_backlight(self.app._active_brightness)

        self.update_screen_runtime_metrics(now)

    def handle_screen_changed_event(self, event: ScreenChangedEvent) -> None:
        """Apply queued screen-change state sync on the coordinator thread."""
        self.app._sync_screen_changed(event.screen_name)
        self.mark_user_activity(now=time.monotonic(), render_on_wake=False)

    def queue_user_activity_event(self, action: Any, _data: Any | None = None) -> None:
        """Publish semantic user activity onto the main-thread event bus."""
        action_name = getattr(action, "value", None)
        self.app.event_bus.publish(UserActivityEvent(action_name=action_name))

    def handle_user_activity_event(self, event: UserActivityEvent) -> None:
        """Wake the display and reset the inactivity timer on user activity."""
        logger.debug(f"User activity received: {event.action_name or 'unknown'}")
        handled_now = time.monotonic()
        self.app._last_input_handled_at = handled_now
        self.app._last_input_handled_action_name = event.action_name
        self.mark_user_activity(
            now=handled_now,
            render_on_wake=event.action_name is not None,
        )

    def handle_low_battery_warning_event(self, event: LowBatteryWarningRaised) -> None:
        """Show a temporary low-battery alert when the warning threshold is crossed."""
        logger.warning(
            "Low battery warning: {:.1f}% remaining (threshold {:.1f}%)",
            event.battery_percent,
            event.threshold_percent,
        )
        self.set_power_alert(
            title="Low Battery",
            subtitle=f"{event.battery_percent:.0f}% remaining",
            color=self.app.display.COLOR_YELLOW if self.app.display is not None else (255, 255, 0),
            duration_seconds=4.0,
        )

    def mark_user_activity(
        self,
        *,
        now: float | None = None,
        render_on_wake: bool,
    ) -> None:
        """Reset inactivity tracking and wake the screen when needed."""
        activity_now = time.monotonic() if now is None else now
        self.app._last_user_activity_at = activity_now
        if self.app._screen_awake:
            self.update_screen_runtime_metrics(activity_now)
            return

        self.wake_screen(activity_now, render_current=render_on_wake)

    def wake_screen(self, now: float, *, render_current: bool) -> None:
        """Restore active brightness and optionally re-render the current screen."""
        if self.app._screen_awake:
            self.update_screen_runtime_metrics(now)
            return

        self.app._screen_awake = True
        self.app._screen_on_started_at = now
        if self.app.display is not None:
            self.app.display.set_backlight(self.app._active_brightness)

        if render_current and self.app.screen_manager is not None:
            self.app.screen_manager.refresh_current_screen()

        if self.app._lvgl_backend is not None and self.app._lvgl_backend.initialized:
            self.app._lvgl_backend.force_refresh()

        self.update_screen_runtime_metrics(now)

        if self.app.cloud_manager is not None:
            # Wake both the config-poll path and MQTT liveness path on screen wake.
            self.app.cloud_manager.request_immediate_poll()
            self.app.cloud_manager.publish_heartbeat()

        logger.debug("Screen woke from inactivity")

    def sleep_screen(self, now: float) -> None:
        """Turn off the display backlight and retain cumulative screen-on time."""
        if not self.app._screen_awake:
            self.update_screen_runtime_metrics(now)
            return

        if self.app._screen_on_started_at is not None:
            self.app._screen_on_accumulated_seconds += max(
                0.0,
                now - self.app._screen_on_started_at,
            )
        self.app._screen_on_started_at = None
        self.app._screen_awake = False
        if self.app.display is not None:
            self.app.display.set_backlight(0.0)
        self.update_screen_runtime_metrics(now)
        logger.info("Screen slept after inactivity timeout")

    def update_screen_runtime_metrics(self, now: float) -> None:
        """Refresh app uptime and screen usage metrics in the shared context."""
        screen_on_seconds = self.app._screen_on_accumulated_seconds
        if self.app._screen_awake and self.app._screen_on_started_at is not None:
            screen_on_seconds += max(0.0, now - self.app._screen_on_started_at)

        idle_seconds = max(0.0, now - self.app._last_user_activity_at)
        app_uptime_seconds = max(0.0, now - self.app._app_started_at)

        if self.app.context is not None:
            self.app.context.update_screen_runtime(
                screen_awake=self.app._screen_awake,
                app_uptime_seconds=app_uptime_seconds,
                screen_on_seconds=screen_on_seconds,
                idle_seconds=idle_seconds,
            )

    def update_screen_power(self, now: float) -> None:
        """Apply inactivity-based screen timeout policy and refresh runtime metrics."""
        if self.app._pending_shutdown is not None or self.app._power_alert is not None:
            self.wake_screen(now, render_current=False)
            return

        self.update_screen_runtime_metrics(now)
        if self.app._screen_timeout_seconds <= 0 or not self.app._screen_awake:
            return

        if now - self.app._last_user_activity_at < self.app._screen_timeout_seconds:
            return

        self.sleep_screen(now)

    def set_power_alert(
        self,
        *,
        title: str,
        subtitle: str,
        color: tuple[int, int, int],
        duration_seconds: float,
    ) -> None:
        """Queue a short-lived fullscreen power alert overlay."""
        self.wake_screen(time.monotonic(), render_current=False)
        self.app._power_alert = PowerAlert(
            title=title,
            subtitle=subtitle,
            color=color,
            expires_at=time.monotonic() + max(0.0, duration_seconds),
        )

    def render_power_overlay(
        self,
        title: str,
        subtitle: str,
        color: tuple[int, int, int],
    ) -> None:
        """Render a simple fullscreen power-status overlay."""
        if self.app.display is None:
            return

        self.app.display.clear(self.app.display.COLOR_BLACK)
        title_size = 24
        subtitle_size = 14
        title_width, title_height = self.app.display.get_text_size(title, title_size)
        subtitle_width, _ = self.app.display.get_text_size(subtitle, subtitle_size)
        title_x = (self.app.display.WIDTH - title_width) // 2
        subtitle_x = (self.app.display.WIDTH - subtitle_width) // 2
        title_y = max(
            self.app.display.STATUS_BAR_HEIGHT + 30,
            (self.app.display.HEIGHT // 2) - 30,
        )
        subtitle_y = title_y + title_height + 18

        self.app.display.text(title, title_x, title_y, color=color, font_size=title_size)
        self.app.display.text(
            subtitle,
            subtitle_x,
            subtitle_y,
            color=self.app.display.COLOR_WHITE,
            font_size=subtitle_size,
        )
        self.app.display.update()

    def update_power_overlays(self, now: float) -> bool:
        """Render pending power overlays and return True when one is active."""
        if self.app._pending_shutdown is not None:
            seconds_remaining = max(0, int(self.app._pending_shutdown.execute_at - now + 0.999))
            subtitle = "Saving state and powering off"
            if seconds_remaining > 0:
                subtitle = f"Shutdown in {seconds_remaining}s"
            self.render_power_overlay(
                "Critical Battery",
                subtitle,
                self.app.display.COLOR_RED if self.app.display is not None else (255, 0, 0),
            )
            return True

        if self.app._power_alert is None:
            return False

        if now >= self.app._power_alert.expires_at:
            self.app._power_alert = None
            if self.app.screen_manager is not None:
                self.app.screen_manager.refresh_current_screen()
            return False

        self.render_power_overlay(
            self.app._power_alert.title,
            self.app._power_alert.subtitle,
            self.app._power_alert.color,
        )
        return True
