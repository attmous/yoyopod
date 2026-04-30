"""Boot-time composition helpers for the core application layer."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.backends.music import MpvBackend, MusicConfig
from yoyopod.config import ConfigManager
from yoyopod.core.audio_volume import OutputVolumeController
from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.core.hardware import AudioDeviceCatalog
from yoyopod.integrations.call import VoIPConfig, VoIPManager
from yoyopod.integrations.cloud.manager import CloudManager
from yoyopod.integrations.contacts.directory import PeopleManager
from yoyopod.integrations.music import LocalMusicService, RecentTrackHistoryStore
from yoyopod.integrations.network import NetworkManager
from yoyopod.integrations.power import PowerManager
from yoyopod.ui.display import Display
from yoyopod.ui.display.contracts import (
    WhisplayProductionRenderContractError,
    build_whisplay_production_contract_message,
)
from yoyopod.ui.input import get_input_manager
from yoyopod.ui.lvgl_binding import LvglInputBridge
from yoyopod.ui.screens.manager import ScreenManager

from .callbacks_boot import CallbacksBoot
from .components_boot import ComponentsBoot
from .config_boot import ConfigBoot
from .managers_boot import ManagersBoot
from .runtime_helpers_boot import RuntimeHelpersBoot
from .screens_boot import ScreensBoot

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class RuntimeBootService:
    """Own boot-time composition for the canonical application object."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self._config_boot = ConfigBoot(
            app,
            logger=logger,
            config_manager_cls=ConfigManager,
            people_manager_cls=PeopleManager,
            recent_track_history_store_cls=RecentTrackHistoryStore,
            audio_device_catalog_cls=AudioDeviceCatalog,
        )
        self._components_boot = ComponentsBoot(
            app,
            logger=logger,
            display_cls=Display,
            get_input_manager_fn=get_input_manager,
            screen_manager_cls=ScreenManager,
            lvgl_input_bridge_cls=LvglInputBridge,
            contract_error_cls=WhisplayProductionRenderContractError,
            build_contract_message_fn=build_whisplay_production_contract_message,
        )
        self._managers_boot = ManagersBoot(
            app,
            logger=logger,
            voip_config_cls=VoIPConfig,
            voip_manager_cls=VoIPManager,
            music_config_cls=MusicConfig,
            mpv_backend_cls=MpvBackend,
            local_music_service_cls=LocalMusicService,
            output_volume_controller_cls=OutputVolumeController,
            power_manager_cls=PowerManager,
            network_manager_cls=NetworkManager,
            cloud_manager_cls=CloudManager,
        )
        self._screens_boot = ScreensBoot(app, logger=logger)
        self._runtime_helpers_boot = RuntimeHelpersBoot(app)
        self._callbacks_boot = CallbacksBoot(app, logger=logger)

    def setup(self) -> bool:
        """Initialize all components and register callbacks."""
        try:
            if not self.load_configuration():
                logger.error("Failed to load configuration")
                return False

            if not self.init_core_components():
                logger.error("Failed to initialize core components")
                return False

            if not self.init_managers():
                logger.error("Failed to initialize managers")
                return False

            if not self.rust_ui_host_enabled():
                if not self.setup_screens():
                    logger.error("Failed to setup screens")
                    return False
            else:
                logger.info("Skipping Python screen construction because Rust UI Host is enabled")
                self.setup_screenless_voice_runtime()

            self.ensure_runtime_helpers()
            self.setup_voip_callbacks()
            self.setup_music_callbacks()
            if self.rust_ui_host_enabled() and not self.setup_rust_ui_host():
                return False
            self.app.shutdown_service.register_power_shutdown_hooks()
            self.app.power_runtime.poll_status(force=True, now=time.monotonic())

            logger.info("YoYoPod setup complete")
            return True
        except Exception:
            logger.exception("Setup failed")
            return False

    def load_configuration(self) -> bool:
        return self._config_boot.load_configuration()

    def init_core_components(self) -> bool:
        return self._components_boot.init_core_components()

    def init_managers(self) -> bool:
        return self._managers_boot.init_managers()

    def setup_screens(self) -> bool:
        return self._screens_boot.setup_screens()

    def rust_ui_host_enabled(self) -> bool:
        settings = getattr(self.app, "app_settings", None)
        display = getattr(settings, "display", None)
        return bool(getattr(display, "rust_ui_enabled", False))

    def setup_screenless_voice_runtime(self) -> None:
        self._screens_boot.setup_screenless_voice_runtime()

    def setup_rust_ui_host(self) -> bool:
        from yoyopod.ui.rust_host import RustUiFacade

        assert self.app.app_settings is not None
        worker_path = self.app.app_settings.display.rust_ui_worker_path
        facade = RustUiFacade(self.app, worker_domain="ui")
        self.app.rust_ui_host = facade
        self.app.bus.subscribe(WorkerMessageReceivedEvent, facade.handle_worker_message)
        started = facade.start_worker(worker_path, hardware="whisplay")
        if not started:
            logger.error("Failed to start Rust UI Host")
            return False
        facade.send_backlight(brightness=self.app._active_brightness)
        facade.send_snapshot()
        return True

    def get_initial_screen_name(self) -> str:
        return self._screens_boot.get_initial_screen_name()

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""
        self._callbacks_boot.setup_voip_callbacks()

    def setup_music_callbacks(self) -> None:
        """Register music event callbacks."""
        self._callbacks_boot.setup_music_callbacks()

    def setup_event_subscriptions(self) -> None:
        """Backward-compatible alias for runtime-helper setup."""
        self.ensure_runtime_helpers()

    def ensure_runtime_helpers(self) -> None:
        """Build runtime helper objects around the initialized runtime."""
        self._runtime_helpers_boot.ensure_runtime_helpers()


__all__ = ["RuntimeBootService"]
