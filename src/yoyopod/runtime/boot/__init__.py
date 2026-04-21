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
from yoyopod.config import ConfigManager
from yoyopod.device import AudioDeviceCatalog
from yoyopod.integrations.call import CallHistoryStore, VoIPConfig, VoIPManager
from yoyopod.integrations.cloud.manager import CloudManager
from yoyopod.integrations.contacts.directory import PeopleManager
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

from .components_boot import ComponentsBoot
from .config_boot import ConfigBoot
from .coordinators_boot import CoordinatorsBoot
from .managers_boot import ManagersBoot
from .screens_boot import ScreensBoot

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


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
        self._coordinators_boot = CoordinatorsBoot(app)

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

    def init_core_components(self) -> bool:
        return self._components_boot.init_core_components()

    def init_managers(self) -> bool:
        return self._managers_boot.init_managers()

    def setup_screens(self) -> bool:
        return self._screens_boot.setup_screens()

    def get_initial_screen_name(self) -> str:
        return self._screens_boot.get_initial_screen_name()

    def setup_voip_callbacks(self) -> None:
        """Register VoIP event callbacks."""

        logger.info("Setting up VoIP callbacks...")

        if not self.app.voip_manager:
            logger.warning("  VoIPManager not available, skipping callbacks")
            return

        call_coordinator = self.app.call_coordinator
        if call_coordinator is None:
            logger.warning("  CallCoordinator not available, skipping VoIP callbacks")
            return

        self.app.voip_manager.on_incoming_call(call_coordinator.handle_incoming_call)
        self.app.voip_manager.on_call_state_change(
            call_coordinator.handle_call_state_change
        )
        self.app.voip_manager.on_registration_change(
            call_coordinator.handle_registration_change
        )
        self.app.voip_manager.on_availability_change(
            call_coordinator.handle_availability_change
        )
        self.app.voip_manager.on_message_summary_change(
            self.app.voice_note_events.handle_voice_note_summary_changed
        )
        self.app.voip_manager.on_message_received(
            self.app.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_delivery_change(
            self.app.voice_note_events.handle_voice_note_activity_changed
        )
        self.app.voip_manager.on_message_failure(
            self.app.voice_note_events.handle_voice_note_failure
        )
        self.app.voice_note_events.sync_talk_summary_context()
        self.app.voice_note_events.sync_active_voice_note_context()
        logger.info("  VoIP callbacks registered")

    def setup_music_callbacks(self) -> None:
        """Register music event callbacks."""

        logger.info("Setting up music callbacks...")

        if not self.app.music_backend:
            logger.warning("  MusicBackend not available, skipping callbacks")
            return

        playback_coordinator = self.app.playback_coordinator
        if playback_coordinator is None:
            logger.warning("  PlaybackCoordinator not available, skipping music callbacks")
            return

        self.app.music_backend.on_track_change(playback_coordinator.handle_track_change)
        self.app.music_backend.on_playback_state_change(
            playback_coordinator.handle_playback_state_change
        )
        if self.app.audio_volume_controller is not None:
            self.app.music_backend.on_connection_change(
                self.app.audio_volume_controller.sync_output_volume_on_music_connect
            )
        self.app.music_backend.on_connection_change(
            playback_coordinator.handle_availability_change
        )
        logger.info("  Music callbacks registered")

    def bind_coordinator_events(self) -> None:
        """Bind coordinator-level event handlers to the EventBus."""

        logger.info("Setting up event subscriptions...")
        call_coordinator = self.app.call_coordinator
        playback_coordinator = self.app.playback_coordinator
        power_coordinator = self.app.power_coordinator
        if (
            call_coordinator is None
            or playback_coordinator is None
            or power_coordinator is None
        ):
            logger.warning("  Coordinators not available, skipping event subscriptions")
            return

        call_coordinator.bind(self.app.event_bus)
        playback_coordinator.bind(self.app.event_bus)
        power_coordinator.bind(self.app.event_bus)
        logger.info("  Event subscriptions registered")

    def setup_event_subscriptions(self) -> None:
        """Backward-compatible alias for coordinator event binding."""
        self.ensure_coordinators()
        self.bind_coordinator_events()

    def ensure_coordinators(self) -> None:
        """Build coordinator helpers around the initialized runtime."""
        self._coordinators_boot.ensure_coordinators()


__all__ = ["RuntimeBootService"]
