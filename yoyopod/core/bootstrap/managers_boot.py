"""Manager/service boot-time composition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class ManagersBoot:
    """Initialize manager-level runtime integrations."""

    def __init__(
        self,
        app: "YoyoPodApp",
        *,
        logger: Any,
        voip_config_cls: Any,
        voip_manager_cls: Any,
        music_config_cls: Any,
        mpv_backend_cls: Any,
        local_music_service_cls: Any,
        output_volume_controller_cls: Any,
        power_manager_cls: Any,
        network_manager_cls: Any,
        cloud_manager_cls: Any,
    ) -> None:
        self.app = app
        self.logger = logger
        self.voip_config_cls = voip_config_cls
        self.voip_manager_cls = voip_manager_cls
        self.music_config_cls = music_config_cls
        self.mpv_backend_cls = mpv_backend_cls
        self.local_music_service_cls = local_music_service_cls
        self.output_volume_controller_cls = output_volume_controller_cls
        self.power_manager_cls = power_manager_cls
        self.network_manager_cls = network_manager_cls
        self.cloud_manager_cls = cloud_manager_cls

    def init_managers(self) -> bool:
        """Initialize VoIP, music, power, network, and cloud managers."""
        from yoyopod.integrations.call import sync_context_voip_status

        self.logger.info("Initializing managers...")

        assert self.app.config_manager is not None
        config_manager = self.app.config_manager

        try:
            self.logger.info("  - VoIPManager")
            voip_config = self.voip_config_cls.from_config_manager(config_manager)
            self.app.voip_manager = self.voip_manager_cls(
                voip_config,
                people_directory=self.app.people_directory,
                event_scheduler=self.app.scheduler.run_on_main,
                background_iterate_enabled=True,
            )
            self.app._voip_iterate_interval_seconds = max(
                0.01,
                float(voip_config.iterate_interval_ms) / 1000.0,
            )
            if self.app.voip_manager.start():
                self.logger.info("    VoIP started successfully")
            else:
                self.logger.warning("    VoIP failed to start (music-only mode)")
            sync_context_voip_status(
                self.app.context,
                config_manager=config_manager,
                ready=False,
                running=self.app.voip_manager.running,
                registration_state=self.app.voip_manager.registration_state,
            )

            self.logger.info("  - MpvBackend")
            music_config = self.music_config_cls.from_config_manager(config_manager)
            self.app.music_backend = self.mpv_backend_cls(music_config)
            self.app.local_music_service = self.local_music_service_cls(
                self.app.music_backend,
                music_dir=music_config.music_dir,
                recent_store=self.app.recent_track_store,
            )
            if self.app.output_volume is None:
                self.app.output_volume = self.output_volume_controller_cls(self.app.music_backend)
            else:
                self.app.output_volume.attach_music_backend(self.app.music_backend)
            if self.app.audio_volume_controller is not None:
                self.app.audio_volume_controller.attach_music_backend(self.app.music_backend)
                self.app.audio_volume_controller.attach_output_volume(self.app.output_volume)
            if self.app.music_backend.start():
                self.logger.info("    Music backend started successfully")
            else:
                self.logger.warning("    Music backend failed to start (VoIP-only mode)")

            if self.app.audio_volume_controller is not None:
                self.app.audio_volume_controller.apply_default_music_volume()

            self.logger.info("  - PowerManager")
            self.app.power_manager = self.power_manager_cls.from_config_manager(config_manager)
            if self.app.power_manager.config.enabled:
                self.logger.info(
                    "    Poll interval: {:.1f}s",
                    self.app.power_manager.config.poll_interval_seconds,
                )
            else:
                self.logger.info("    Power backend disabled in config")

            self.logger.info("  - NetworkManager")
            self.app.network_manager = self.network_manager_cls.from_config_manager(
                config_manager,
                event_publisher=lambda event: self.app.scheduler.run_on_main(
                    lambda event_to_publish=event: self.app.bus.publish(event_to_publish)
                ),
            )
            if self.app.network_manager.config.enabled and not self.app.simulate:
                try:
                    self.app.network_manager.start()
                    self.app.network_events.sync_network_context_from_manager()
                except Exception as exc:
                    self.logger.error("Network manager start failed: {}", exc)
                    if self.app.context is not None:
                        self.app.context.update_network_status(
                            network_enabled=self.app.network_manager.config.enabled,
                            connection_type="none",
                            connected=False,
                            gps_has_fix=False,
                        )
            else:
                self.logger.info("    Network module disabled in config")
                if self.app.context is not None:
                    self.app.context.update_network_status(
                        network_enabled=self.app.network_manager.config.enabled,
                        connection_type="none",
                        connected=False,
                        gps_has_fix=False,
                    )

            self.logger.info("  - CloudManager")
            self.app.cloud_manager = self.cloud_manager_cls(
                app=self.app,
                config_manager=config_manager,
            )
            self.app.cloud_manager.prepare_boot()

            return True
        except Exception:
            self.logger.exception("Failed to initialize managers")
            return False
