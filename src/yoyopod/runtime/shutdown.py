"""Shutdown countdowns, hooks, and runtime cleanup helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.power import GracefulShutdownCancelled, GracefulShutdownRequested
from yoyopod.runtime.models import PendingShutdown

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class ShutdownLifecycleService:
    """Own graceful shutdown countdowns and runtime cleanup."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def handle_graceful_shutdown_requested_event(
        self,
        event: GracefulShutdownRequested,
    ) -> None:
        """Start a delayed graceful shutdown countdown for critical battery."""
        if self.app._pending_shutdown is not None:
            return

        requested_at = time.monotonic()
        self.app._pending_shutdown = PendingShutdown(
            reason=event.reason,
            requested_at=requested_at,
            execute_at=requested_at + max(0.0, event.delay_seconds),
            battery_percent=event.snapshot.battery.level_percent,
        )
        self.app.screen_power_service.wake_screen(requested_at, render_current=False)
        logger.warning(
            "Critical battery detected; shutdown in {:.1f}s",
            event.delay_seconds,
        )

    def handle_graceful_shutdown_cancelled_event(
        self,
        event: GracefulShutdownCancelled,
    ) -> None:
        """Cancel a pending battery-triggered shutdown when power returns."""
        if self.app._pending_shutdown is None:
            return

        logger.info(f"Graceful shutdown cancelled ({event.reason})")
        self.app._pending_shutdown = None
        self.app.screen_power_service.set_power_alert(
            title="Power Restored",
            subtitle="Shutdown cancelled",
            color=self.app.display.COLOR_GREEN if self.app.display is not None else (0, 255, 0),
            duration_seconds=3.0,
        )

    def register_power_shutdown_hooks(self) -> None:
        """Register built-in shutdown hooks once the power manager is available."""
        if self.app.power_manager is None or self.app._power_hooks_registered:
            return

        self.app.power_manager.register_shutdown_hook(
            "save_shutdown_state",
            self.save_shutdown_state,
        )
        self.app._power_hooks_registered = True

    def save_shutdown_state(self) -> None:
        """Persist a small runtime snapshot before graceful poweroff."""
        if self.app.power_manager is None:
            return

        snapshot_path = Path(self.app.power_manager.config.shutdown_state_file)
        if not snapshot_path.is_absolute():
            snapshot_path = Path.cwd() / snapshot_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        current_screen = None
        if (
            self.app.screen_manager is not None
            and self.app.screen_manager.get_current_screen() is not None
        ):
            current_screen_obj = self.app.screen_manager.get_current_screen()
            if current_screen_obj is not None:
                current_screen = current_screen_obj.route_name

        current_track = None
        if self.app.context is not None:
            track = self.app.context.get_current_track()
        else:
            track = None
        if track is not None:
            current_track = {
                "title": track.name,
                "artist": track.get_artist_string(),
            }

        payload = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "state": (
                self.app.coordinator_runtime.get_state_name()
                if self.app.coordinator_runtime
                else None
            ),
            "current_screen": current_screen,
            "battery_percent": (
                self.app.context.power.battery_percent if self.app.context else None
            ),
            "battery_charging": (
                self.app.context.power.battery_charging if self.app.context else None
            ),
            "external_power": self.app.context.power.external_power if self.app.context else None,
            "voip_registered": self.app.voip_registered,
            "music_available": (
                self.app.music_backend.is_connected if self.app.music_backend else False
            ),
            "app_uptime_seconds": (
                self.app.context.screen.app_uptime_seconds if self.app.context else 0
            ),
            "screen_on_seconds": self.app.context.screen.on_seconds if self.app.context else 0,
            "screen_awake": self.app.context.screen.awake if self.app.context else True,
            "screen_idle_seconds": self.app.context.screen.idle_seconds if self.app.context else 0,
            "playback": {
                "is_playing": (
                    self.app.context.media.playback.is_playing if self.app.context else False
                ),
                "is_paused": (
                    self.app.context.media.playback.is_paused if self.app.context else False
                ),
                "volume": self.app.context.media.playback.volume if self.app.context else None,
            },
            "track": current_track,
        }

        snapshot_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Saved shutdown state to {snapshot_path}")

    def process_pending_shutdown(self, now: float) -> None:
        """Execute a delayed shutdown when its grace period expires."""
        if self.app._pending_shutdown is None or now < self.app._pending_shutdown.execute_at:
            return

        self.execute_pending_shutdown()

    def execute_pending_shutdown(self) -> None:
        """Run graceful-shutdown hooks, stop the app, and request system poweroff."""
        if self.app._shutdown_completed:
            return

        self.app.power_runtime.suppress_watchdog_feeding("pending system poweroff")
        self.app.screen_power_service.render_power_overlay(
            "Powering Off",
            "Saving state...",
            self.app.display.COLOR_RED if self.app.display is not None else (255, 0, 0),
        )

        if self.app.power_manager is not None:
            failed_hooks = self.app.power_manager.run_shutdown_hooks()
            if failed_hooks:
                logger.warning(f"Shutdown hooks failed: {', '.join(failed_hooks)}")

        self.app.stop(disable_watchdog=False)

        if self.app.power_manager is not None:
            self.app.power_manager.request_system_shutdown()

        self.app._shutdown_completed = True

    def stop(self, disable_watchdog: bool = True) -> None:
        """Clean up and stop the application."""
        if self.app._stopped:
            return

        logger.info("Stopping YoyoPod...")
        self.app._stopping = True

        if disable_watchdog:
            self.app.power_runtime.disable_watchdog()

        self.app.boot_service.ensure_coordinators()
        assert self.app.call_coordinator is not None
        self.app.call_coordinator.cleanup()

        if self.app.network_manager is not None:
            try:
                logger.info("  - Stopping network manager")
                self.app.network_manager.stop()
            except Exception as exc:
                logger.error("Network manager cleanup failed: {}", exc)

        if self.app.voip_manager:
            logger.info("  - Stopping VoIP manager")
            self.app.voip_manager.stop(notify_events=False)

        if self.app.music_backend:
            logger.info("  - Stopping music backend")
            stop = getattr(self.app.music_backend, "stop", None)
            if stop is not None:
                stop()
            else:
                stop_polling = getattr(self.app.music_backend, "stop_polling", None)
                cleanup = getattr(self.app.music_backend, "cleanup", None)
                if stop_polling is not None:
                    stop_polling()
                if cleanup is not None:
                    cleanup()

        if self.app.cloud_manager is not None:
            logger.info("  - Stopping cloud manager")
            self.app.cloud_manager.stop()

        if self.app.input_manager:
            logger.info("  - Stopping input manager")
            self.app.input_manager.stop()

        pending_actions = self.app.runtime_loop.process_pending_main_thread_actions()
        if pending_actions:
            logger.info(f"  - Processed {pending_actions} queued app events during shutdown")

        if self.app.display:
            logger.info("  - Clearing display")
            self.app.display.set_backlight(self.app._active_brightness)
            self.app.display.clear(self.app.display.COLOR_BLACK)
            self.app.display.text(
                "Goodbye!",
                70,
                120,
                color=self.app.display.COLOR_CYAN,
                font_size=20,
            )
            self.app.display.update()
            time.sleep(1)
            self.app.display.cleanup()

        logger.info("YoyoPod stopped")
        self.app._stopped = True
