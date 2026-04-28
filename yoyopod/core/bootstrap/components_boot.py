"""Core display/input/context boot-time composition."""

from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from yoyopod.core.events import WorkerDomainStateChangedEvent, WorkerMessageReceivedEvent
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.voice.worker_client import VoiceWorkerClient

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp

_VOICE_WORKER_HEALTH_RETRY_DELAY_SECONDS = 2.0


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

    def _rust_ui_host_enabled(self) -> bool:
        settings = getattr(self.app, "app_settings", None)
        display = getattr(settings, "display", None)
        return bool(getattr(display, "rust_ui_enabled", False))

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

        configured_domain = str(getattr(worker_cfg, "domain", "voice")).strip() or "voice"
        if configured_domain != "voice":
            self.logger.warning(
                "Ignoring unsupported voice worker domain {!r}; voice protocol uses domain 'voice'",
                configured_domain,
            )
        domain = "voice"
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
        lifecycle_handler = _VoiceWorkerLifecycleHandler(
            client,
            domain=domain,
            logger=self.logger,
            scheduler=self.app.scheduler,
        )
        self.app.bus.subscribe(
            WorkerDomainStateChangedEvent,
            lifecycle_handler.handle,
        )
        self.app.worker_supervisor.register(
            domain,
            WorkerProcessConfig(
                name=domain,
                argv=list(getattr(worker_cfg, "argv", [])),
                cwd=None,
                env=worker_env,
            ),
        )
        started = self.app.worker_supervisor.start(domain)
        if not started:
            client.mark_unavailable("start_failed")
            self.app.voice_worker_client = None
            return False
        lifecycle_handler.schedule_health_probe()
        return True

    def init_core_components(self) -> bool:
        """Initialize display, context, orchestration models, input, and screen manager."""
        self.logger.info("Initializing core components...")

        try:
            assert self.app.app_settings is not None
            if not self._rust_ui_host_enabled():
                self._init_python_ui_hardware()
            else:
                self.app.screen_power_service.configure_screen_power(
                    initial_now=time.monotonic()
                )
            self._init_app_context()
            self._init_orchestration_models()
            if not self._rust_ui_host_enabled():
                self._init_python_input_and_screen_manager()
            else:
                self.logger.info("  - Rust UI Host owns display/input/screens")
            return True
        except Exception:
            self.logger.exception("Failed to initialize core components")
            return False

    def _init_python_ui_hardware(self) -> None:
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

    def _init_app_context(self) -> None:
        from yoyopod.core import AppContext
        from yoyopod.core.audio_volume import AudioVolumeController
        from yoyopod.integrations.call import sync_context_voip_status
        from yoyopod.ui.input import InteractionProfile

        self.logger.info("  - AppContext")
        self.app.context = AppContext()
        if self._rust_ui_host_enabled():
            self.app.context.interaction_profile = InteractionProfile.ONE_BUTTON
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

    def _init_orchestration_models(self) -> None:
        from yoyopod.integrations.call import CallFSM, CallInterruptionPolicy
        from yoyopod.integrations.music import MusicFSM

        self.logger.info("  - Orchestration Models")
        self.app.music_fsm = MusicFSM()
        self.app.call_fsm = CallFSM()
        self.app.call_interruption_policy = CallInterruptionPolicy()

    def _init_python_input_and_screen_manager(self) -> None:
        self.logger.info("  - InputManager")
        display = self.app.display
        if display is None:
            raise RuntimeError("Display must be initialized before Python input")
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
                self.app.input_manager.on_activity(self.app.runtime_loop.queue_lvgl_input_action)
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


def _voice_worker_env(worker_cfg: Any) -> dict[str, str]:
    """Return process env with config-derived cloud worker settings applied."""

    env = dict(os.environ)
    config_env = {
        "YOYOPOD_VOICE_WORKER_PROVIDER": getattr(worker_cfg, "provider", "mock"),
        "YOYOPOD_CLOUD_STT_MODEL": getattr(worker_cfg, "stt_model", ""),
        "YOYOPOD_CLOUD_STT_LANGUAGE": getattr(worker_cfg, "stt_language", ""),
        "YOYOPOD_CLOUD_STT_PROMPT": getattr(worker_cfg, "stt_prompt", ""),
        "YOYOPOD_CLOUD_TTS_MODEL": getattr(worker_cfg, "tts_model", ""),
        "YOYOPOD_CLOUD_TTS_VOICE": getattr(worker_cfg, "tts_voice", ""),
        "YOYOPOD_CLOUD_TTS_INSTRUCTIONS": getattr(worker_cfg, "tts_instructions", ""),
        "YOYOPOD_CLOUD_ASK_MODEL": getattr(worker_cfg, "ask_model", ""),
        "YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS": getattr(worker_cfg, "ask_timeout_seconds", ""),
        "YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS": getattr(
            worker_cfg,
            "ask_max_history_turns",
            "",
        ),
        "YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS": getattr(
            worker_cfg,
            "ask_max_response_chars",
            "",
        ),
        "YOYOPOD_CLOUD_ASK_INSTRUCTIONS": getattr(worker_cfg, "ask_instructions", ""),
    }
    for key, value in config_env.items():
        normalized = str(value).strip()
        if normalized:
            env[key] = normalized
    return env


class _VoiceWorkerLifecycleHandler:
    """Keep voice-worker client availability in sync with process lifecycle."""

    def __init__(
        self,
        client: VoiceWorkerClient,
        *,
        domain: str,
        logger: Any,
        scheduler: Any,
    ) -> None:
        self._client = client
        self._domain = domain
        self._logger = logger
        self._scheduler = scheduler
        self._health_probe_requested = False
        self._worker_running = True

    def handle(self, event: WorkerDomainStateChangedEvent) -> None:
        if event.domain != self._domain:
            return
        if event.state == "running":
            self._worker_running = True
            self.schedule_health_probe()
            return
        if event.state in {"degraded", "disabled", "stopped"}:
            self._worker_running = False
            self._health_probe_requested = False
            self._client.fail_pending_requests(event.reason or event.state)

    def schedule_health_probe(self) -> None:
        if not self._worker_running:
            return
        if self._health_probe_requested:
            return
        self._health_probe_requested = True
        _start_voice_worker_health_probe(
            self._client,
            logger=self._logger,
            scheduler=self._scheduler,
            on_complete=self._handle_health_probe_complete,
        )

    def _handle_health_probe_complete(self, succeeded: bool) -> None:
        self._health_probe_requested = False
        if succeeded or not self._worker_running:
            return
        self._schedule_health_probe_retry()

    def _schedule_health_probe_retry(self) -> None:
        def request_retry() -> None:
            post = getattr(self._scheduler, "post", None)
            if callable(post):
                post(self.schedule_health_probe)
            else:
                self._scheduler.run_on_main(self.schedule_health_probe)

        timer = threading.Timer(_VOICE_WORKER_HEALTH_RETRY_DELAY_SECONDS, request_retry)
        timer.daemon = True
        timer.start()


def _start_voice_worker_health_probe(
    client: VoiceWorkerClient,
    *,
    logger: Any,
    scheduler: Any,
    on_complete: Callable[[bool], None] | None = None,
) -> None:
    """Probe provider health off the main thread once the loop drains scheduled work."""

    def probe() -> None:
        succeeded = False
        try:
            result = client.health()
        except Exception as exc:
            logger.warning("Cloud voice worker health probe failed: {}", exc)
        else:
            succeeded = True
            logger.info("Cloud voice worker ready: provider={}", result.provider)
        finally:
            if on_complete is None:
                return

            def complete() -> None:
                on_complete(succeeded)

            post_complete = getattr(scheduler, "post", None)
            if callable(post_complete):
                post_complete(complete)
            else:
                scheduler.run_on_main(complete)

    def start_probe() -> None:
        threading.Thread(
            target=probe,
            daemon=True,
            name="VoiceWorkerHealthProbe",
        ).start()

    post = getattr(scheduler, "post", None)
    if callable(post):
        post(start_probe)
        return
    scheduler.run_on_main(start_probe)
