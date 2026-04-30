"""Configuration loading and baseline boot-time defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class ConfigBoot:
    """Handle configuration and static runtime resource initialization."""

    def __init__(
        self,
        app: "YoyoPodApp",
        *,
        logger: Any,
        config_manager_cls: Any,
        people_manager_cls: Any,
        recent_track_history_store_cls: Any,
        audio_device_catalog_cls: Any,
    ) -> None:
        self.app = app
        self.logger = logger
        self.config_manager_cls = config_manager_cls
        self.people_manager_cls = people_manager_cls
        self.recent_track_history_store_cls = recent_track_history_store_cls
        self.audio_device_catalog_cls = audio_device_catalog_cls

    def load_configuration(self) -> bool:
        """Load YoYoPod configuration."""
        self.logger.info("Loading configuration...")

        try:
            self.app.config_manager = self.config_manager_cls(config_dir=self.app.config_dir)
            self.app.app_settings = self.app.config_manager.get_app_settings()
            self.app.media_settings = self.app.config_manager.get_media_settings()
            self.app.people_directory = self.people_manager_cls.from_config_manager(
                self.app.config_manager
            )
            self.app.call_history_store = None
            self.app.recent_track_store = self.recent_track_history_store_cls(
                self.app.config_manager.resolve_runtime_path(
                    self.app.config_manager.get_recent_tracks_file()
                )
            )
            self.app.audio_device_catalog = self.audio_device_catalog_cls()
            self.app.audio_device_catalog.refresh_async()

            if self.app.config_manager.app_config_loaded:
                self.logger.info(
                    "Loaded composed app configuration from canonical config topology under {}",
                    self.app.config_manager.config_dir,
                )
            else:
                self.logger.info("Using default application configuration")

            if self.app.media_settings is not None:
                self.app.auto_resume_after_call = (
                    self.app.media_settings.music.auto_resume_after_call
                )
            self.app._screen_timeout_seconds = (
                self.app.screen_power_service.resolve_screen_timeout_seconds()
            )
            self.app._active_brightness = self.app.screen_power_service.resolve_active_brightness()
            self.logger.info(f"  Auto-resume after call: {self.app.auto_resume_after_call}")
            self.logger.info(f"  Screen timeout: {self.app._screen_timeout_seconds:.1f}s")
            self.logger.info(f"  Active brightness: {self.app._active_brightness:.2f}")
            return True
        except Exception:
            self.logger.exception("Failed to load configuration")
            return False
