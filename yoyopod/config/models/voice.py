"""Voice assistant and device configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value

DEFAULT_CLOUD_ASK_INSTRUCTIONS = (
    "You are YoYoPod's friendly Ask helper for a child using a small handheld audio device. "
    "Answer in simple language a child can understand. Keep answers to 1-3 short sentences "
    "unless the child asks for a story. Be warm, calm, and encouraging. Do not use scary "
    "detail. Do not ask for private information. For medical, legal, safety, emergency, or "
    "adult topics, give a brief safe answer and say to ask a grown-up. If you are unsure, "
    "say so simply. Do not claim to browse the internet or know live facts."
)
DEFAULT_CLOUD_TTS_INSTRUCTIONS = (
    "Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. "
    "Avoid scary emphasis."
)


@dataclass(slots=True)
class VoiceAssistantConfig:
    """Local voice-command and spoken-response policy."""

    mode: str = config_value(default="local", env="YOYOPOD_VOICE_MODE")
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
class VoiceWorkerConfig:
    """Cloud voice worker process and model policy."""

    enabled: bool = config_value(default=False, env="YOYOPOD_VOICE_WORKER_ENABLED")
    domain: str = config_value(default="voice", env="YOYOPOD_VOICE_WORKER_DOMAIN")
    provider: str = config_value(default="mock", env="YOYOPOD_VOICE_WORKER_PROVIDER")
    argv: list[str] = config_value(
        default_factory=lambda: ["workers/voice/go/build/yoyopod-voice-worker"],
        env="YOYOPOD_VOICE_WORKER_ARGV",
    )
    request_timeout_seconds: float = config_value(
        default=12.0,
        env="YOYOPOD_VOICE_WORKER_TIMEOUT_SECONDS",
    )
    max_audio_seconds: float = config_value(
        default=30.0,
        env="YOYOPOD_VOICE_WORKER_MAX_AUDIO_SECONDS",
    )
    stt_model: str = config_value(
        default="gpt-4o-mini-transcribe",
        env="YOYOPOD_CLOUD_STT_MODEL",
    )
    tts_model: str = config_value(default="gpt-4o-mini-tts", env="YOYOPOD_CLOUD_TTS_MODEL")
    tts_voice: str = config_value(default="coral", env="YOYOPOD_CLOUD_TTS_VOICE")
    tts_instructions: str = config_value(
        default=DEFAULT_CLOUD_TTS_INSTRUCTIONS,
        env="YOYOPOD_CLOUD_TTS_INSTRUCTIONS",
    )
    ask_model: str = config_value(default="gpt-4.1-mini", env="YOYOPOD_CLOUD_ASK_MODEL")
    ask_timeout_seconds: float = config_value(
        default=12.0,
        env="YOYOPOD_CLOUD_ASK_TIMEOUT_SECONDS",
    )
    ask_max_history_turns: int = config_value(
        default=4,
        env="YOYOPOD_CLOUD_ASK_MAX_HISTORY_TURNS",
    )
    ask_max_response_chars: int = config_value(
        default=480,
        env="YOYOPOD_CLOUD_ASK_MAX_RESPONSE_CHARS",
    )
    ask_instructions: str = config_value(
        default=DEFAULT_CLOUD_ASK_INSTRUCTIONS,
        env="YOYOPOD_CLOUD_ASK_INSTRUCTIONS",
    )
    local_feedback_enabled: bool = config_value(
        default=True,
        env="YOYOPOD_VOICE_LOCAL_FEEDBACK_ENABLED",
    )


@dataclass(slots=True)
class VoiceConfig:
    """Composed voice domain config built from voice and device layers."""

    assistant: VoiceAssistantConfig = config_value(default_factory=VoiceAssistantConfig)
    audio: VoiceAudioConfig = config_value(default_factory=VoiceAudioConfig)
    worker: VoiceWorkerConfig = config_value(default_factory=VoiceWorkerConfig)
