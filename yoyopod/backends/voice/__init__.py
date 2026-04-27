"""Canonical voice backend adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.backends.voice.capture import (
        AudioCaptureBackend,
        NullAudioCaptureBackend,
        SubprocessAudioCaptureBackend,
    )
    from yoyopod.backends.voice.cloud_worker import (
        CloudWorkerSpeechToTextBackend,
        CloudWorkerTextToSpeechBackend,
    )
    from yoyopod.backends.voice.output import AlsaOutputPlayer
    from yoyopod.backends.voice.stt import (
        NullSpeechToTextBackend,
        SpeechToTextBackend,
        VoskSpeechToTextBackend,
    )
    from yoyopod.backends.voice.tts import (
        EspeakNgTextToSpeechBackend,
        NullTextToSpeechBackend,
        TextToSpeechBackend,
    )


_EXPORTS = {
    "AlsaOutputPlayer": ("yoyopod.backends.voice.output", "AlsaOutputPlayer"),
    "AudioCaptureBackend": ("yoyopod.backends.voice.capture", "AudioCaptureBackend"),
    "CloudWorkerSpeechToTextBackend": (
        "yoyopod.backends.voice.cloud_worker",
        "CloudWorkerSpeechToTextBackend",
    ),
    "CloudWorkerTextToSpeechBackend": (
        "yoyopod.backends.voice.cloud_worker",
        "CloudWorkerTextToSpeechBackend",
    ),
    "EspeakNgTextToSpeechBackend": (
        "yoyopod.backends.voice.tts",
        "EspeakNgTextToSpeechBackend",
    ),
    "NullAudioCaptureBackend": ("yoyopod.backends.voice.capture", "NullAudioCaptureBackend"),
    "NullSpeechToTextBackend": ("yoyopod.backends.voice.stt", "NullSpeechToTextBackend"),
    "NullTextToSpeechBackend": ("yoyopod.backends.voice.tts", "NullTextToSpeechBackend"),
    "SpeechToTextBackend": ("yoyopod.backends.voice.stt", "SpeechToTextBackend"),
    "SubprocessAudioCaptureBackend": (
        "yoyopod.backends.voice.capture",
        "SubprocessAudioCaptureBackend",
    ),
    "TextToSpeechBackend": ("yoyopod.backends.voice.tts", "TextToSpeechBackend"),
    "VoskSpeechToTextBackend": ("yoyopod.backends.voice.stt", "VoskSpeechToTextBackend"),
}


def __getattr__(name: str) -> Any:
    """Load backend exports lazily so the low-level voice modules stay acyclic."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = [
    "AlsaOutputPlayer",
    "AudioCaptureBackend",
    "CloudWorkerSpeechToTextBackend",
    "CloudWorkerTextToSpeechBackend",
    "EspeakNgTextToSpeechBackend",
    "NullAudioCaptureBackend",
    "NullSpeechToTextBackend",
    "NullTextToSpeechBackend",
    "SpeechToTextBackend",
    "SubprocessAudioCaptureBackend",
    "TextToSpeechBackend",
    "VoskSpeechToTextBackend",
]
