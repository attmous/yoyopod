"""Resolve voice settings and expose coordinator command outcomes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable

from yoyopod.integrations.voice import VoiceSettings

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.config import ConfigManager


@dataclass(slots=True, frozen=True)
class VoiceCommandOutcome:
    """Result returned by the shared voice command executor."""

    headline: str
    body: str
    should_speak: bool = True
    route_name: str | None = None
    auto_return: bool = True


class VoiceSettingsResolver:
    """Resolve current voice settings from the app runtime and config layer."""

    def __init__(
        self,
        *,
        context: "AppContext | None",
        config_manager: "ConfigManager | None" = None,
        settings_provider: Callable[[], VoiceSettings] | None = None,
    ) -> None:
        self._context = context
        self._config_manager = config_manager
        self._settings_provider = settings_provider

    def current(self) -> VoiceSettings:
        """Return the latest runtime voice settings."""

        if self._settings_provider is not None:
            return self._settings_provider()
        defaults = self.defaults()
        if self._context is None:
            return defaults

        voice = self._context.voice
        capture_device_id = (
            voice.capture_device_id
            if voice.capture_device_id is not None
            else defaults.capture_device_id
        )
        speaker_device_id = (
            voice.speaker_device_id
            if voice.speaker_device_id is not None
            else defaults.speaker_device_id
        )
        return replace(
            defaults,
            commands_enabled=voice.commands_enabled,
            ai_requests_enabled=voice.ai_requests_enabled,
            screen_read_enabled=voice.screen_read_enabled,
            stt_enabled=voice.stt_enabled,
            tts_enabled=voice.tts_enabled,
            mic_muted=voice.mic_muted,
            output_volume=voice.output_volume,
            capture_device_id=capture_device_id,
            speaker_device_id=speaker_device_id,
        )

    def defaults(self) -> VoiceSettings:
        """Return configured voice defaults when no provider is supplied."""

        capture_device_id = None
        speaker_device_id = None
        assistant_cfg = None
        worker_cfg = None
        if self._config_manager is not None:
            voice_cfg = getattr(self._config_manager, "get_voice_settings", lambda: None)()
            if voice_cfg is not None:
                assistant_cfg = getattr(voice_cfg, "assistant", None)
                worker_cfg = getattr(voice_cfg, "worker", None)
                audio_cfg = getattr(voice_cfg, "audio", None)
                if audio_cfg is not None:
                    capture_device_id = getattr(audio_cfg, "capture_device_id", "").strip() or None
                    speaker_device_id = getattr(audio_cfg, "speaker_device_id", "").strip() or None

            legacy_app_settings = getattr(self._config_manager, "get_app_settings", None)
            legacy_voice_cfg = None
            if callable(legacy_app_settings):
                app_settings = legacy_app_settings()
                legacy_voice_cfg = getattr(app_settings, "voice", None)
                if assistant_cfg is None:
                    assistant_cfg = legacy_voice_cfg
                if legacy_voice_cfg is not None:
                    if capture_device_id is None:
                        capture_device_id = (
                            getattr(legacy_voice_cfg, "capture_device_id", "").strip() or None
                        )
                    if speaker_device_id is None:
                        speaker_device_id = (
                            getattr(legacy_voice_cfg, "speaker_device_id", "").strip() or None
                        )

            if capture_device_id is None:
                capture_device_id = getattr(
                    self._config_manager, "get_capture_device_id", lambda: None
                )()
            if speaker_device_id is None:
                speaker_device_id = getattr(
                    self._config_manager,
                    "get_voice_speaker_device_id",
                    lambda: None,
                )()
            if speaker_device_id is None:
                speaker_device_id = getattr(
                    self._config_manager,
                    "get_ring_output_device",
                    lambda: None,
                )()

        defaults = VoiceSettings(
            capture_device_id=capture_device_id,
            speaker_device_id=speaker_device_id or None,
        )
        if self._config_manager is None:
            return defaults
        if assistant_cfg is None:
            return defaults

        get_default_output_volume = getattr(self._config_manager, "get_default_output_volume", None)
        output_volume = defaults.output_volume
        if callable(get_default_output_volume):
            output_volume = int(get_default_output_volume())

        return VoiceSettings(
            mode=getattr(assistant_cfg, "mode", defaults.mode),
            commands_enabled=getattr(assistant_cfg, "commands_enabled", defaults.commands_enabled),
            ai_requests_enabled=getattr(
                assistant_cfg,
                "ai_requests_enabled",
                defaults.ai_requests_enabled,
            ),
            screen_read_enabled=getattr(
                assistant_cfg,
                "screen_read_enabled",
                defaults.screen_read_enabled,
            ),
            stt_enabled=getattr(assistant_cfg, "stt_enabled", defaults.stt_enabled),
            tts_enabled=getattr(assistant_cfg, "tts_enabled", defaults.tts_enabled),
            output_volume=output_volume,
            stt_backend=getattr(assistant_cfg, "stt_backend", defaults.stt_backend),
            tts_backend=getattr(assistant_cfg, "tts_backend", defaults.tts_backend),
            vosk_model_path=getattr(
                assistant_cfg,
                "vosk_model_path",
                defaults.vosk_model_path,
            ),
            vosk_model_keep_loaded=getattr(
                assistant_cfg,
                "vosk_model_keep_loaded",
                defaults.vosk_model_keep_loaded,
            ),
            speaker_device_id=speaker_device_id,
            capture_device_id=capture_device_id,
            sample_rate_hz=getattr(assistant_cfg, "sample_rate_hz", defaults.sample_rate_hz),
            record_seconds=getattr(assistant_cfg, "record_seconds", defaults.record_seconds),
            tts_rate_wpm=getattr(assistant_cfg, "tts_rate_wpm", defaults.tts_rate_wpm),
            tts_voice=getattr(assistant_cfg, "tts_voice", defaults.tts_voice),
            cloud_worker_enabled=getattr(
                worker_cfg,
                "enabled",
                defaults.cloud_worker_enabled,
            ),
            cloud_worker_domain=getattr(
                worker_cfg,
                "domain",
                defaults.cloud_worker_domain,
            ),
            cloud_worker_provider=getattr(
                worker_cfg,
                "provider",
                defaults.cloud_worker_provider,
            ),
            cloud_worker_request_timeout_seconds=getattr(
                worker_cfg,
                "request_timeout_seconds",
                defaults.cloud_worker_request_timeout_seconds,
            ),
            cloud_worker_max_audio_seconds=getattr(
                worker_cfg,
                "max_audio_seconds",
                defaults.cloud_worker_max_audio_seconds,
            ),
            cloud_worker_stt_model=getattr(
                worker_cfg,
                "stt_model",
                defaults.cloud_worker_stt_model,
            ),
            cloud_worker_tts_model=getattr(
                worker_cfg,
                "tts_model",
                defaults.cloud_worker_tts_model,
            ),
            cloud_worker_tts_voice=getattr(
                worker_cfg,
                "tts_voice",
                defaults.cloud_worker_tts_voice,
            ),
            cloud_worker_tts_instructions=getattr(
                worker_cfg,
                "tts_instructions",
                defaults.cloud_worker_tts_instructions,
            ),
            cloud_worker_ask_model=getattr(
                worker_cfg,
                "ask_model",
                defaults.cloud_worker_ask_model,
            ),
            cloud_worker_ask_timeout_seconds=getattr(
                worker_cfg,
                "ask_timeout_seconds",
                defaults.cloud_worker_ask_timeout_seconds,
            ),
            cloud_worker_ask_max_history_turns=getattr(
                worker_cfg,
                "ask_max_history_turns",
                defaults.cloud_worker_ask_max_history_turns,
            ),
            cloud_worker_ask_max_response_chars=getattr(
                worker_cfg,
                "ask_max_response_chars",
                defaults.cloud_worker_ask_max_response_chars,
            ),
            cloud_worker_ask_instructions=getattr(
                worker_cfg,
                "ask_instructions",
                defaults.cloud_worker_ask_instructions,
            ),
            local_feedback_enabled=getattr(
                worker_cfg,
                "local_feedback_enabled",
                defaults.local_feedback_enabled,
            ),
        )
