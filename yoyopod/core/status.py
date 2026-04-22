"""Runtime snapshot builders and status services for the frozen core."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class RuntimeMetricsStore:
    """Track small runtime markers that status and diagnostics need to read."""

    def __init__(self) -> None:
        self.last_input_activity_at = 0.0
        self.last_input_activity_action_name: str | None = None
        self.last_input_handled_at = 0.0
        self.last_input_handled_action_name: str | None = None
        self.last_responsiveness_capture_at = 0.0
        self.last_responsiveness_capture_reason: str | None = None
        self.last_responsiveness_capture_scope: str | None = None
        self.last_responsiveness_capture_summary: str | None = None
        self.last_responsiveness_capture_artifacts: dict[str, str] = {}

    def note_input_activity(
        self,
        action: object,
        _data: Any | None = None,
        *,
        captured_at: float | None = None,
    ) -> None:
        """Record raw or semantic input activity before the coordinator drains it."""

        self.last_input_activity_at = time.monotonic() if captured_at is None else captured_at
        self.last_input_activity_action_name = getattr(action, "value", None)

    def note_handled_input(
        self,
        *,
        action_name: str | None,
        handled_at: float,
    ) -> None:
        """Record semantic user activity after the coordinator handles it."""

        self.last_input_handled_at = handled_at
        self.last_input_handled_action_name = action_name

    def record_responsiveness_capture(
        self,
        *,
        captured_at: float,
        reason: str,
        suspected_scope: str,
        summary: str,
        artifacts: dict[str, str] | None = None,
    ) -> None:
        """Persist the latest automatic hang-evidence capture metadata."""

        self.last_responsiveness_capture_at = captured_at
        self.last_responsiveness_capture_reason = reason
        self.last_responsiveness_capture_scope = suspected_scope
        self.last_responsiveness_capture_summary = summary
        self.last_responsiveness_capture_artifacts = dict(artifacts or {})


class RuntimeStatusService:
    """Assemble the current runtime status snapshot for diagnostics and UI queries."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def get_status(self, *, refresh_output_volume: bool = False) -> dict[str, Any]:
        """Return the current application status."""

        monotonic_now = time.monotonic()
        runtime_metrics = self.app.runtime_metrics
        pending_shutdown_in_seconds = None
        if self.app._pending_shutdown is not None:
            pending_shutdown_in_seconds = max(
                0.0,
                self.app._pending_shutdown.execute_at - monotonic_now,
            )

        assert self.app.app_state_runtime is not None
        assert self.app.call_interruption_policy is not None
        current_screen = (
            self.app.screen_manager.get_current_screen()
            if self.app.screen_manager is not None
            else None
        )
        power_snapshot = (
            self.app.power_manager.get_snapshot() if self.app.power_manager is not None else None
        )

        return {
            "state": self.app.app_state_runtime.get_state_name(),
            "voip_registered": self.app.voip_registered,
            "music_was_playing": self.app.call_interruption_policy.music_interrupted_by_call,
            "auto_resume": self.app.auto_resume_after_call,
            "voip_available": (
                self.app.voip_manager is not None and self.app.voip_manager.running
            ),
            "music_available": (
                self.app.music_backend is not None and self.app.music_backend.is_connected
            ),
            "volume": (
                self.app.audio_volume_controller.get_output_volume(
                    refresh_system=refresh_output_volume
                )
                if self.app.audio_volume_controller is not None
                else (
                    self.app.context.media.playback.volume
                    if self.app.context is not None
                    else None
                )
            ),
            "power_available": power_snapshot.available if power_snapshot is not None else False,
            "current_screen": getattr(current_screen, "route_name", None),
            "screen_stack_depth": (
                len(self.app.screen_manager.screen_stack)
                if self.app.screen_manager is not None
                else 0
            ),
            "input_manager_running": (
                self.app.input_manager.running if self.app.input_manager is not None else False
            ),
            "pending_scheduler_tasks": self.app.runtime_loop.pending_main_thread_callback_count(),
            "pending_bus_events": self.app.bus.pending_count(),
            "input_activity_age_seconds": (
                max(0.0, monotonic_now - runtime_metrics.last_input_activity_at)
                if runtime_metrics.last_input_activity_at > 0.0
                else None
            ),
            "last_input_action": runtime_metrics.last_input_activity_action_name,
            "handled_input_activity_age_seconds": (
                max(0.0, monotonic_now - runtime_metrics.last_input_handled_at)
                if runtime_metrics.last_input_handled_at > 0.0
                else None
            ),
            "last_handled_input_action": runtime_metrics.last_input_handled_action_name,
            "battery_percent": self.app.context.power.battery_percent if self.app.context else None,
            "battery_charging": (
                self.app.context.power.battery_charging if self.app.context else None
            ),
            "external_power": self.app.context.power.external_power if self.app.context else None,
            "missed_calls": self.app.context.talk.missed_calls if self.app.context else 0,
            "recent_calls": self.app.context.talk.recent_calls if self.app.context else [],
            "screen_awake": (
                self.app.context.screen.awake if self.app.context else self.app._screen_awake
            ),
            "screen_idle_seconds": (
                self.app.context.screen.idle_seconds if self.app.context else None
            ),
            "screen_on_seconds": (
                self.app.context.screen.on_seconds if self.app.context else None
            ),
            "app_uptime_seconds": (
                self.app.context.screen.app_uptime_seconds if self.app.context else None
            ),
            "shutdown_pending": self.app._pending_shutdown is not None,
            "shutdown_reason": (
                self.app._pending_shutdown.reason if self.app._pending_shutdown else None
            ),
            "shutdown_in_seconds": pending_shutdown_in_seconds,
            "shutdown_completed": self.app._shutdown_completed,
            "warning_threshold_percent": (
                self.app.power_manager.config.low_battery_warning_percent
                if self.app.power_manager is not None
                else None
            ),
            "critical_shutdown_percent": (
                self.app.power_manager.config.critical_shutdown_percent
                if self.app.power_manager is not None
                else None
            ),
            "shutdown_delay_seconds": (
                self.app.power_manager.config.shutdown_delay_seconds
                if self.app.power_manager is not None
                else None
            ),
            "screen_timeout_seconds": self.app._screen_timeout_seconds,
            "display_backend": (
                getattr(self.app.display, "backend_kind", "unavailable")
                if self.app.display is not None
                else "unknown"
            ),
            "lvgl_initialized": bool(
                self.app._lvgl_backend is not None and self.app._lvgl_backend.initialized
            ),
            "lvgl_pump_age_seconds": (
                max(0.0, monotonic_now - self.app._last_lvgl_pump_at)
                if self.app._last_lvgl_pump_at > 0.0
                else None
            ),
            "loop_heartbeat_age_seconds": (
                max(0.0, monotonic_now - self.app._last_loop_heartbeat_at)
                if self.app._last_loop_heartbeat_at > 0.0
                else None
            ),
            "next_voip_iterate_in_seconds": (
                max(0.0, self.app._next_voip_iterate_at - monotonic_now)
                if (
                    self.app.voip_manager is not None
                    and self.app.voip_manager.running
                    and self.app._next_voip_iterate_at > 0.0
                )
                else None
            ),
            "power_model": power_snapshot.device.model if power_snapshot is not None else None,
            "power_error": power_snapshot.error if power_snapshot is not None else None,
            "power_voltage_volts": (
                power_snapshot.battery.voltage_volts if power_snapshot is not None else None
            ),
            "power_temperature_celsius": (
                power_snapshot.battery.temperature_celsius
                if power_snapshot is not None
                else None
            ),
            "rtc_time": power_snapshot.rtc.time if power_snapshot is not None else None,
            "rtc_alarm_enabled": (
                power_snapshot.rtc.alarm_enabled if power_snapshot is not None else None
            ),
            "rtc_alarm_time": (
                power_snapshot.rtc.alarm_time if power_snapshot is not None else None
            ),
            "watchdog_enabled": (
                self.app.power_manager.config.watchdog_enabled
                if self.app.power_manager is not None
                else False
            ),
            "watchdog_active": self.app._watchdog_active,
            "watchdog_feed_in_flight": self.app._watchdog_feed_in_flight,
            "watchdog_feed_suppressed": self.app._watchdog_feed_suppressed,
            "watchdog_timeout_seconds": (
                self.app.power_manager.config.watchdog_timeout_seconds
                if self.app.power_manager is not None
                else None
            ),
            "watchdog_feed_interval_seconds": (
                self.app.power_manager.config.watchdog_feed_interval_seconds
                if self.app.power_manager is not None
                else None
            ),
            "power_refresh_in_flight": self.app._power_refresh_in_flight,
            "responsiveness_watchdog_enabled": bool(
                getattr(
                    getattr(self.app.app_settings, "diagnostics", None),
                    "responsiveness_watchdog_enabled",
                    False,
                )
            ),
            "responsiveness_capture_dir": (
                getattr(
                    getattr(self.app.app_settings, "diagnostics", None),
                    "responsiveness_capture_dir",
                    None,
                )
            ),
            "responsiveness_last_capture_age_seconds": (
                max(0.0, monotonic_now - runtime_metrics.last_responsiveness_capture_at)
                if runtime_metrics.last_responsiveness_capture_at > 0.0
                else None
            ),
            "responsiveness_last_capture_reason": (
                runtime_metrics.last_responsiveness_capture_reason
            ),
            "responsiveness_last_capture_scope": runtime_metrics.last_responsiveness_capture_scope,
            "responsiveness_last_capture_summary": (
                runtime_metrics.last_responsiveness_capture_summary
            ),
            "responsiveness_last_capture_artifacts": dict(
                runtime_metrics.last_responsiveness_capture_artifacts
            ),
            **self.app.runtime_loop.timing_snapshot(now=monotonic_now),
        }


def build_runtime_status(app: Any) -> dict[str, object]:
    """Return the core scaffold runtime snapshot without persistence metadata."""

    return {
        "states": {
            entity: {
                "value": _jsonify(value.value),
                "attrs": _jsonify(dict(value.attrs)),
                "last_changed_at": value.last_changed_at,
            }
            for entity, value in sorted(app.states.all().items())
        },
        "subscriptions": app.bus.subscription_counts(),
        "services": [f"{domain}.{service}" for domain, service in app.services.registered()],
        "tick_stats_last_100": app.tick_stats_snapshot(),
    }


def _jsonify(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonify(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


__all__ = ["RuntimeMetricsStore", "RuntimeStatusService", "build_runtime_status"]
