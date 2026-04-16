"""Local voice-command and spoken-response interfaces."""

from yoyopod.voice.capture import (
    AudioCaptureBackend,
    NullAudioCaptureBackend,
    SubprocessAudioCaptureBackend,
)
from yoyopod.voice.commands import (
    VOICE_COMMAND_GRAMMAR,
    VoiceCommandIntent,
    VoiceCommandMatch,
    VoiceCommandTemplate,
    match_voice_command,
)
from yoyopod.voice.models import (
    VoiceCaptureRequest,
    VoiceCaptureResult,
    VoiceSettings,
    VoiceTranscript,
)
from yoyopod.voice.output import AlsaOutputPlayer
from yoyopod.voice.service import VoiceService
from yoyopod.voice.stt import NullSpeechToTextBackend, SpeechToTextBackend, VoskSpeechToTextBackend
from yoyopod.voice.tts import (
    EspeakNgTextToSpeechBackend,
    NullTextToSpeechBackend,
    TextToSpeechBackend,
)

__all__ = [
    "AudioCaptureBackend",
    "AlsaOutputPlayer",
    "EspeakNgTextToSpeechBackend",
    "NullAudioCaptureBackend",
    "NullSpeechToTextBackend",
    "NullTextToSpeechBackend",
    "SpeechToTextBackend",
    "SubprocessAudioCaptureBackend",
    "TextToSpeechBackend",
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceCommandIntent",
    "VoiceCommandMatch",
    "VoiceCommandTemplate",
    "VoiceService",
    "VoiceSettings",
    "VoiceTranscript",
    "VoskSpeechToTextBackend",
    "VOICE_COMMAND_GRAMMAR",
    "match_voice_command",
]
