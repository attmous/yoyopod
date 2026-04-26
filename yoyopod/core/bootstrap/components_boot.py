"""Core display/input/context boot-time composition."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.voice.worker_client import VoiceWorkerClient

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class ComponentsBoot:
    """Initialize core non-manager runtime components."""

    def __init__(
        self,
        app: "YoyoPodApp",
        *,
        logger: Any,
        display_cls: Any,
        get_input_manager_fn: Any,
        screen_manager_cls: Any,
        lvgl_input_bridge_cls: Any,
        contract_error_cls: Any,
        build_contract_message_fn: Any,
    ) -> None:
        self.app = app
        self.logger = logger
        self.display_cls = display_cls
        self.get_input_manager_fn = get_input_manager_fn
        self.screen_manager_cls = screen_manager_cls
        self.lvgl_input_bridge_cls = lvgl_input_bridge_cls
        self.contract_error_cls = contract_error_cls
        self.build_contract_message_fn = build_contract_message_fn

    def _whisplay_production_contract_required(self, *, requested_renderer: str) -> bool:
        """Return True for the narrow post-construction LVGL-init failure case."""

        if self.app.simulate:
            return False
        if self.app.display is None:
            return False
        adapter = self.app.display.get_adapter()
        return (
            getattr(adapter, "DISPLAY_TYPE", None) == "whisplay"
            and requested_renderer.strip().lower() == "lvgl"
        )

    def _default_music_volume(self) -> int:
        """Return the configured startup output volume for music playback."""

        media_cfg = getattr(self.app, "media_settings", None)
        raw_volume = media_cfg.music.default_volume if media_cfg is not None else 100
        return max(0, min(100, int(raw_volume)))

    @staticmethod
    def _lvgl_runtime_required_message() -> str:
        """Return the canonical LVGL-only startup failure guidance."""

        return (
            "LVGL backend initialization failed during startup. "
            "YoYoPod has no non-LVGL fallback for Whisplay, Pimoroni, or simulation. "
            "Build the native shim with `yoyopod build simulation` "
            "(or `yoyopod build ensure-native`) and try again."
        )

    def setup_voice_worker(self) -> bool:
        """Register and start the cloud voice worker when configured."""

        if self.app.config_manager is None:
            return False

        voice_cfg = self.app.config_manager.get_voice_settings()
        assistant_cfg = getattr(voice_cfg, "assistant", None)
        worker_cfg = getattr(voice_cfg, "worker", None)
        if getattr(assistant_cfg, "mode", "local") != "cloud":
            return False
        if not bool(getattr(worker_cfg, "enabled", False)):
            return False
        if getattr(self.app, "voice_worker_client", None) is not None:
            return False

        domain = str(getattr(worker_cfg, "domain", "voice"))
        timeout_seconds = float(getattr(worker_cfg, "request_timeout_seconds", 12.0))
        worker_env = _voice_worker_env(worker_cfg)
        client = VoiceWorkerClient(
            scheduler=self.app.scheduler,
            worker_supervisor=self.app.worker_supervisor,
            domain=domain,
            request_timeout_seconds=timeout_seconds,
        )
        self.app.voice_worker_client = client
        self.app.bus.subscribe(WorkerMessageReceivedEvent, client.handle_worker_message)
        self.app.worker_supervisor.register(
            domain,
            WorkerProcessConfig(
                name=domain,
                argv=list(getattr(worker_cfg, "argv", [])),
                cwd=None,
                env=worker_env,
            ),
        )
        return self.app.worker_supervisor.start(domain)

    def init_core_components(self) -> bool:
        """Initialize display, context, orchestration models, input, and screen manager."""
        from yoyopod.core import AppContext
        from yoyopod.core.audio_volume import AudioVolumeController
        from yoyopod.integrations.call import (
            CallFSM,
            CallInterruptionPolicy,
            sync_context_voip_status,
        )
        from yoyopod.integrations.music import MusicFSM

        self.logger.info("Initializing core components...")

        try:
            assert self.app.app_settings is not None
            self.logger.info("  - Display")
            display_hardware = (
                self.app.app_settings.display.hardware if self.app.app_settings else "auto"
            )
            whisplay_renderer = (
                self.app.app_settings.display.whisplay_renderer
                if self.app.app_settings is not None
                else "lvgl"
            )
            self.logger.info(f"    Hardware: {display_hardware}")
            self.logger.info(f"    Whisplay renderer: {whisplay_renderer}")
            self.app.display = self.display_cls(
                hardware=display_hardware,
                simulate=self.app.simulate,
                whisplay_renderer=whisplay_renderer,
                whisplay_lvgl_buffer_lines=self.app.app_settings.display.lvgl_buffer_lines,
            )
            display = self.app.display
            self.logger.info(f"    Dimensions: {display.WIDTH}x{display.HEIGHT}")
            self.logger.info(f"    Orientation: {display.ORIENTATION}")
            self.app._lvgl_backend = display.get_ui_backend()
            if self.app._lvgl_backend is not None and self.app._lvgl_backend.initialize():
                display.refresh_backend_kind()
                self.app.runtime_loop.last_lvgl_pump_at = time.monotonic()
            else:
                self.app._lvgl_backend = None
                display.refresh_backend_kind()
                error_message = "Whisplay LVGL backend initialization failed during startup"
                if self._whisplay_production_contract_required(
                    requested_renderer=whisplay_renderer,
                ):
                    raise self.contract_error_cls(self.build_contract_message_fn(error_message))
                raise RuntimeError(self._lvgl_runtime_required_message())
            self.logger.info(f"    Active UI backend: {display.backend_kind}")
            self.app.screen_power_service.configure_screen_power(initial_now=time.monotonic())

            self.logger.info("  - AppContext")
            self.app.context = AppContext()
            audio_volume_controller = AudioVolumeController(
                context=self.app.context,
                default_music_volume_provider=self._default_music_volume,
                output_volume=getattr(self.app, "output_volume", None),
                music_backend=getattr(self.app, "music_backend", None),
            )
            setattr(self.app, "audio_volume_controller", audio_volume_controller)
            self.app.context.audio_volume_controller = audio_volume_controller
            sync_context_voip_status(
                self.app.context,
                config_manager=self.app.config_manager,
                ready=False,
                running=False,
                registration_state="none",
            )
            if self.app.context is not None and self.app.config_manager is not None:
                voice_cfg = self.app.config_manager.get_voice_settings()
                speaker_device_id = voice_cfg.audio.speaker_device_id.strip() or None
                capture_device_id = voice_cfg.audio.capture_device_id.strip() or None
                self.app.context.configure_voice(
                    commands_enabled=voice_cfg.assistant.commands_enabled,
                    ai_requests_enabled=voice_cfg.assistant.ai_requests_enabled,
                    screen_read_enabled=voice_cfg.assistant.screen_read_enabled,
                    stt_enabled=voice_cfg.assistant.stt_enabled,
                    tts_enabled=voice_cfg.assistant.tts_enabled,
                    speaker_device_id=speaker_device_id,
                    capture_device_id=capture_device_id,
                )
                self.app.voice_note_events.sync_talk_summary_context()
                self.setup_voice_worker()
            self.app.screen_power_service.update_screen_runtime_metrics(time.monotonic())

            self.logger.info("  - Orchestration Models")
            self.app.music_fsm = MusicFSM()
            self.app.call_fsm = CallFSM()
            self.app.call_interruption_policy = CallInterruptionPolicy()

            self.logger.info("  - InputManager")
            self.app.input_manager = self.get_input_manager_fn(
                display_adapter=display.get_adapter(),
                input_settings=self.app.app_settings.input,
                simulate=self.app.simulate,
            )
            if self.app.input_manager:
                self.app.context.interaction_profile = self.app.input_manager.interaction_profile
                self.app.input_manager.on_activity(self.app.note_input_activity)
                self.app.input_manager.on_activity(
                    self.app.screen_power_service.queue_user_activity_event
                )
                if self.app._lvgl_backend is not None:
                    self.app._lvgl_input_bridge = self.lvgl_input_bridge_cls(self.app._lvgl_backend)
                    self.app.input_manager.on_activity(
                        self.app.runtime_loop.queue_lvgl_input_action
                    )
                self.app.input_manager.start()
                self.logger.info("    Input system initialized")
            else:
                self.logger.info("    No input hardware available")

            self.logger.info("  - ScreenManager")
            self.app.screen_manager = self.screen_manager_cls(
                display,
                self.app.input_manager,
                action_scheduler=self.app.scheduler.run_on_main,
                on_action_handled=self.app.note_handled_input,
                on_visible_refresh=self.app.note_visible_refresh,
                is_screen_visible=lambda: self.app._screen_awake,
            )
            return True
        except Exception:
            self.logger.exception("Failed to initialize core components")
            return False


def _voice_worker_env(worker_cfg: Any) -> dict[str, str]:
    """Return process env with config-derived cloud worker settings applied."""

    env = dict(os.environ)
    config_env = {
        "YOYOPOD_VOICE_WORKER_PROVIDER": getattr(worker_cfg, "provider", "mock"),
        "YOYOPOD_CLOUD_STT_MODEL": getattr(worker_cfg, "stt_model", ""),
        "YOYOPOD_CLOUD_TTS_MODEL": getattr(worker_cfg, "tts_model", ""),
        "YOYOPOD_CLOUD_TTS_VOICE": getattr(worker_cfg, "tts_voice", ""),
        "YOYOPOD_CLOUD_TTS_INSTRUCTIONS": getattr(worker_cfg, "tts_instructions", ""),
    }
    for key, value in config_env.items():
        normalized = str(value).strip()
        if normalized:
            env[key] = normalized
    return env
