"""Live display wake/sleep policy and power overlay integration."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from yoyopod.core.events import ScreenChangedEvent, UserActivityEvent
from yoyopod.integrations.power import PowerAlert
from yoyopod.integrations.power.events import LowBatteryWarningRaised
from yoyopod.ui.screens.lvgl_status import sync_network_status

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class ScreenPowerService:
    """Own screen-power policy and the canonical power overlay implementation."""

    name = "power"
    priority = 100

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
        runtime = self.app.app_state_runtime
        if runtime is not None:
            runtime.sync_ui_state_for_screen(event.screen_name)
        self.mark_user_activity(now=time.monotonic(), render_on_wake=False)

    def queue_user_activity_event(self, action: Any, _data: Any | None = None) -> None:
        """Publish semantic user activity onto the main-thread bus."""
        action_name = getattr(action, "value", None)
        self.app.scheduler.run_on_main(
            lambda: self.app.bus.publish(UserActivityEvent(action_name=action_name))
        )

    def handle_user_activity_event(self, event: UserActivityEvent) -> None:
        """Wake the display and reset the inactivity timer on user activity."""
        logger.debug(f"User activity received: {event.action_name or 'unknown'}")
        handled_now = time.monotonic()
        self.app.note_handled_input(
            action_name=event.action_name,
            handled_at=handled_now,
        )
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
        """Render a simple fullscreen power-status overlay via LVGL."""
        if self.app.display is None:
            return
        ui_backend = self.app.display.get_ui_backend()
        binding = getattr(ui_backend, "binding", None) if ui_backend is not None else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False) or binding is None:
            logger.warning("Skipping power overlay because the LVGL backend is unavailable")
            return

        try:
            if hasattr(binding, "ask_destroy"):
                binding.ask_destroy()
        except Exception:
            logger.debug("Ignoring LVGL ask scene destroy failure before power overlay")

        sync_network_status(binding, self.app.context)
        binding.ask_build()
        binding.ask_sync(
            icon_key="battery" if "battery" in title.lower() else "care",
            title_text=title,
            subtitle_text=subtitle,
            footer="Power alert",
            voip_state=(1 if self.app.context is not None and self.app.context.voip.ready else 0),
            battery_percent=(
                max(0, min(100, int(self.app.context.power.battery_percent)))
                if self.app.context is not None
                else 100
            ),
            charging=(
                self.app.context.power.battery_charging if self.app.context is not None else False
            ),
            power_available=(
                self.app.context.power.available if self.app.context is not None else True
            ),
            accent=color,
        )
        ui_backend.force_refresh()

    def is_active(self, now: float) -> bool:
        """Return whether the power overlay should be active."""
        if self.app._pending_shutdown is not None:
            return True

        if self.app._power_alert is None:
            return False

        return now < self.app._power_alert.expires_at

    def render(self, now: float) -> None:
        """Render the current power overlay state when active."""
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
            return

        if self.app._power_alert is None:
            return

        self.render_power_overlay(
            self.app._power_alert.title,
            self.app._power_alert.subtitle,
            self.app._power_alert.color,
        )

    def on_deactivate(self, now: float) -> None:
        """Clear expired alerts and restore the visible screen when needed."""

        if self.app._power_alert is None or now < self.app._power_alert.expires_at:
            return

        self.app._power_alert = None
        if self.app.screen_manager is not None:
            self.app.screen_manager.refresh_current_screen()

    def update_power_overlays(self, now: float) -> bool:
        """Compatibility helper for callers still using the old power-overlay API."""
        if not self.is_active(now):
            self.on_deactivate(now)
            return False
        self.render(now)
        return True
