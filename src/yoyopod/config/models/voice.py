"""Voice assistant and device configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class VoiceAssistantConfig:
    """Local voice-command and spoken-response policy."""

    commands_enabled: bool = config_value(default=True, env="YOYOPOD_VOICE_COMMANDS_ENABLED")
    ai_requests_enabled: bool = config_value(default=True, env="YOYOPOD_AI_REQUESTS_ENABLED")
    screen_read_enabled: bool = config_value(default=False, env="YOYOPOD_SCREEN_READ_ENABLED")
    stt_enabled: bool = config_value(default=True, env="YOYOPOD_STT_ENABLED")
    tts_enabled: bool = config_value(default=True, env="YOYOPOD_TTS_ENABLED")
    stt_backend: str = config_value(default="vosk", env="YOYOPOD_STT_BACKEND")
    tts_backend: str = config_value(default="espeak-ng", env="YOYOPOD_TTS_BACKEND")
    vosk_model_path: str = config_value(
        default="models/vosk-model-small-en-us",
        env="YOYOPOD_VOSK_MODEL_PATH",
    )
    vosk_model_keep_loaded: bool = config_value(
        default=True,
        env="YOYOPOD_VOSK_MODEL_KEEP_LOADED",
    )
    record_seconds: int = config_value(default=4, env="YOYOPOD_VOICE_RECORD_SECONDS")
    sample_rate_hz: int = config_value(default=16000, env="YOYOPOD_VOICE_SAMPLE_RATE_HZ")
    tts_rate_wpm: int = config_value(default=155, env="YOYOPOD_TTS_RATE_WPM")
    tts_voice: str = config_value(default="en", env="YOYOPOD_TTS_VOICE")


@dataclass(slots=True)
class VoiceAudioConfig:
    """Device-owned ALSA selectors consumed by the local voice domain."""

    speaker_device_id: str = config_value(default="", env="YOYOPOD_VOICE_SPEAKER_DEVICE")
    capture_device_id: str = config_value(default="", env="YOYOPOD_VOICE_CAPTURE_DEVICE")


@dataclass(slots=True)
class VoiceConfig:
    """Composed voice domain config built from voice and device layers."""

    assistant: VoiceAssistantConfig = config_value(default_factory=VoiceAssistantConfig)
    audio: VoiceAudioConfig = config_value(default_factory=VoiceAudioConfig)
