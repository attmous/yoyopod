"""Boot-time composition helpers for the runtime layer."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.audio import (
    LocalMusicService,
    MpvBackend,
    MusicConfig,
    OutputVolumeController,
    RecentTrackHistoryStore,
)
from yoyopod.cloud import CloudManager
from yoyopod.communication import CallHistoryStore, VoIPConfig, VoIPManager
from yoyopod.config import ConfigManager
from yoyopod.device import AudioDeviceCatalog
from yoyopod.network import NetworkManager
from yoyopod.people import PeopleManager
from yoyopod.power import PowerManager
from yoyopod.ui.display import Display
from yoyopod.ui.display.contracts import (
    WhisplayProductionRenderContractError,
    build_whisplay_production_contract_message,
)
from yoyopod.ui.input import InteractionProfile, get_input_manager
from yoyopod.ui.lvgl_binding import LvglInputBridge
from yoyopod.ui.screens.manager import ScreenManager

from .components_boot import ComponentsBoot
from .config_boot import ConfigBoot
from .managers_boot import ManagersBoot
from .screens_boot import ScreensBoot
from .wiring_boot import WiringBoot

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp
    from yoyopod.coordinators import AppRuntimeState


class RuntimeBootService:
    """Own the boot-time composition of the application runtime."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self._config_boot = ConfigBoot(
            app,
            logger=logger,
            config_manager_cls=ConfigManager,
            people_manager_cls=PeopleManager,
            call_history_store_cls=CallHistoryStore,
            recent_track_history_store_cls=RecentTrackHistoryStore,
            audio_device_catalog_cls=AudioDeviceCatalog,
        )
        self._components_boot = ComponentsBoot(
            app,
            logger=logger,
            display_cls=Display,
            get_input_manager_fn=get_input_manager,
            screen_manager_cls=ScreenManager,
            refresh_talk_summary_fn=self.refresh_talk_summary,
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
        self._wiring_boot = WiringBoot(app, logger=logger)

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

            if not self.setup_screens():
                logger.error("Failed to setup screens")
                return False

            self.ensure_coordinators()
            assert self.app.coordinator_runtime is not None
            self.app.coordinator_runtime.set_ui_state(self.app._ui_state, trigger="initial_screen")
            self.bind_coordinator_events()
            self.setup_voip_callbacks()
            self.setup_music_callbacks()
            self.app.shutdown_service.register_power_shutdown_hooks()
            self.app.power_runtime.poll_status(force=True, now=time.monotonic())

            logger.info("YoyoPod setup complete")
            return True
        except Exception:
            logger.exception("Setup failed")
            return False

    def load_configuration(self) -> bool:
        return self._config_boot.load_configuration()

    def resolve_screen_timeout_seconds(self) -> float:
        return self.app.screen_power_service.resolve_screen_timeout_seconds()

    def resolve_active_brightness(self) -> float:
        return self.app.screen_power_service.resolve_active_brightness()

    def init_core_components(self) -> bool:
        return self._components_boot.init_core_components()

    def init_managers(self) -> bool:
        return self._managers_boot.init_managers()

    def setup_screens(self) -> bool:
        return self._screens_boot.setup_screens()

    def get_interaction_profile(self) -> InteractionProfile:
        return self._screens_boot.get_interaction_profile()

    def get_initial_screen_name(self) -> str:
        return self._screens_boot.get_initial_screen_name()

    def get_initial_ui_state(self) -> "AppRuntimeState":
        return self._screens_boot.get_initial_ui_state()

    def refresh_talk_summary(self) -> None:
        self._wiring_boot.refresh_talk_summary()

    def setup_voip_callbacks(self) -> None:
        self._wiring_boot.setup_voip_callbacks()

    def setup_music_callbacks(self) -> None:
        self._wiring_boot.setup_music_callbacks()

    def bind_coordinator_events(self) -> None:
        self._wiring_boot.bind_coordinator_events()

    def setup_event_subscriptions(self) -> None:
        """Backward-compatible alias for coordinator event binding."""
        self.bind_coordinator_events()

    def ensure_coordinators(self) -> None:
        self._wiring_boot.ensure_coordinators()


__all__ = ["RuntimeBootService"]
