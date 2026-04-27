"""Cloud worker voice backend behavior."""

from __future__ import annotations

import tempfile
import threading
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict, Unpack

from pytest import MonkeyPatch

from yoyopod.backends.voice import (
    CloudWorkerSpeechToTextBackend,
    CloudWorkerTextToSpeechBackend,
)
from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)


class VoiceSettingsOverrides(TypedDict):
    """Typed overrides accepted by the cloud-settings helper."""

    stt_enabled: NotRequired[bool]
    tts_enabled: NotRequired[bool]
    stt_backend: NotRequired[str]
    tts_backend: NotRequired[str]
    speaker_device_id: NotRequired[str | None]
    sample_rate_hz: NotRequired[int]
    cloud_worker_enabled: NotRequired[bool]
    cloud_worker_max_audio_seconds: NotRequired[float]
    cloud_worker_stt_model: NotRequired[str]
    cloud_worker_tts_model: NotRequired[str]
    cloud_worker_tts_voice: NotRequired[str]
    cloud_worker_tts_instructions: NotRequired[str]


class FakeVoiceWorkerClient:
    """Small fake that records cloud-worker backend calls."""

    def __init__(
        self,
        *,
        transcript: VoiceWorkerTranscribeResult | None = None,
        speech: VoiceWorkerSpeakResult | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.transcript = transcript or VoiceWorkerTranscribeResult(
            text="turn up the music",
            confidence=0.82,
            is_final=True,
        )
        self.speech = speech or VoiceWorkerSpeakResult(
            audio_path=Path("worker-output.wav"),
            format="wav",
            sample_rate_hz=24000,
        )
        self.exc = exc
        self.available = True
        self.transcribe_calls: list[dict[str, Any]] = []
        self.speak_calls: list[dict[str, Any]] = []

    @property
    def is_available(self) -> bool:
        return self.available

    def transcribe(
        self,
        *,
        audio_path: Path,
        sample_rate_hz: int,
        language: str,
        model: str,
        max_audio_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerTranscribeResult:
        self.transcribe_calls.append(
            {
                "audio_path": audio_path,
                "sample_rate_hz": sample_rate_hz,
                "language": language,
                "model": model,
                "max_audio_seconds": max_audio_seconds,
                "cancel_event": cancel_event,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.transcript

    def speak(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        instructions: str,
        sample_rate_hz: int,
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerSpeakResult:
        self.speak_calls.append(
            {
                "text": text,
                "voice": voice,
                "model": model,
                "instructions": instructions,
                "sample_rate_hz": sample_rate_hz,
                "cancel_event": cancel_event,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.speech


class FakeWavPlayer:
    """Small fake that records playback calls."""

    def __init__(self, *, result: bool = True, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        audio_path: Path,
        *,
        device_id: str | None = None,
        timeout_seconds: float = 6.0,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self.calls.append(
            {
                "audio_path": audio_path,
                "device_id": device_id,
                "timeout_seconds": timeout_seconds,
                "cancel_event": cancel_event,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.result


def cloud_settings(**overrides: Unpack[VoiceSettingsOverrides]) -> VoiceSettings:
    defaults = VoiceSettings(
        stt_backend="cloud-worker",
        tts_backend="cloud-worker",
        cloud_worker_enabled=True,
        cloud_worker_max_audio_seconds=11.5,
        cloud_worker_stt_model="stt-test-model",
        cloud_worker_tts_model="tts-test-model",
        cloud_worker_tts_voice="verse",
        cloud_worker_tts_instructions="Short handheld response.",
        sample_rate_hz=22050,
    )
    return replace(defaults, **overrides)


def empty_final_transcript() -> VoiceTranscript:
    return VoiceTranscript(text="", confidence=0.0, is_final=True)


def test_stt_is_available_only_when_enabled_and_cloud_backend() -> None:
    backend = CloudWorkerSpeechToTextBackend(client=FakeVoiceWorkerClient())

    assert backend.is_available(cloud_settings())
    assert not backend.is_available(cloud_settings(stt_enabled=False))
    assert not backend.is_available(cloud_settings(stt_backend="vosk"))
    assert not backend.is_available(cloud_settings(cloud_worker_enabled=False))


def test_stt_is_unavailable_when_worker_health_is_down() -> None:
    client = FakeVoiceWorkerClient()
    client.available = False
    backend = CloudWorkerSpeechToTextBackend(client=client)

    assert not backend.is_available(cloud_settings())


def test_stt_transcribe_delegates_to_client_and_maps_transcript() -> None:
    client = FakeVoiceWorkerClient(
        transcript=VoiceWorkerTranscribeResult(
            text="play favorites",
            confidence=0.91,
            is_final=True,
        )
    )
    backend = CloudWorkerSpeechToTextBackend(client=client)
    audio_path = Path("input.wav")

    transcript = backend.transcribe(audio_path, cloud_settings())

    assert transcript == VoiceTranscript(text="play favorites", confidence=0.91, is_final=True)
    assert client.transcribe_calls == [
        {
            "audio_path": audio_path,
            "sample_rate_hz": 22050,
            "language": "en",
            "model": "stt-test-model",
            "max_audio_seconds": 11.5,
            "cancel_event": None,
        }
    ]


def test_stt_transcribe_passes_cancel_event_to_client() -> None:
    client = FakeVoiceWorkerClient()
    backend = CloudWorkerSpeechToTextBackend(client=client)
    cancel_event = threading.Event()

    backend.transcribe(Path("input.wav"), cloud_settings(), cancel_event=cancel_event)

    assert client.transcribe_calls[0]["cancel_event"] is cancel_event


def test_stt_unavailable_returns_empty_final_transcript_without_calling_client() -> None:
    client = FakeVoiceWorkerClient()
    backend = CloudWorkerSpeechToTextBackend(client=client)

    transcript = backend.transcribe(Path("input.wav"), cloud_settings(stt_enabled=False))

    assert transcript == empty_final_transcript()
    assert client.transcribe_calls == []


def test_stt_cloud_worker_disabled_returns_empty_final_transcript_without_calling_client() -> None:
    client = FakeVoiceWorkerClient()
    backend = CloudWorkerSpeechToTextBackend(client=client)

    transcript = backend.transcribe(
        Path("input.wav"),
        cloud_settings(cloud_worker_enabled=False),
    )

    assert transcript == empty_final_transcript()
    assert client.transcribe_calls == []


def test_stt_client_exception_returns_empty_final_transcript() -> None:
    client = FakeVoiceWorkerClient(exc=RuntimeError("worker unavailable"))
    backend = CloudWorkerSpeechToTextBackend(client=client)

    transcript = backend.transcribe(Path("input.wav"), cloud_settings())

    assert transcript == empty_final_transcript()
    assert len(client.transcribe_calls) == 1


def test_tts_is_available_only_when_enabled_and_cloud_backend() -> None:
    backend = CloudWorkerTextToSpeechBackend(
        client=FakeVoiceWorkerClient(),
        play_wav=FakeWavPlayer(),
    )

    assert backend.is_available(cloud_settings())
    assert not backend.is_available(cloud_settings(tts_enabled=False))
    assert not backend.is_available(cloud_settings(tts_backend="espeak-ng"))
    assert not backend.is_available(cloud_settings(cloud_worker_enabled=False))


def test_tts_is_unavailable_when_worker_health_is_down() -> None:
    client = FakeVoiceWorkerClient()
    client.available = False
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=FakeWavPlayer())

    assert not backend.is_available(cloud_settings())


def test_tts_speak_delegates_to_client_and_plays_returned_wav() -> None:
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=Path("answer.wav"),
            format="wav",
            sample_rate_hz=22050,
        )
    )
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert backend.speak("Hello from the cloud", cloud_settings())
    assert client.speak_calls == [
        {
            "text": "Hello from the cloud",
            "voice": "verse",
            "model": "tts-test-model",
            "instructions": "Short handheld response.",
            "sample_rate_hz": 22050,
            "cancel_event": None,
        }
    ]
    assert play_wav.calls == [
        {
            "audio_path": Path("answer.wav"),
            "device_id": None,
            "timeout_seconds": 6.0,
            "cancel_event": None,
        }
    ]


def test_tts_speak_passes_cancel_event_to_client_and_playback() -> None:
    cancel_event = threading.Event()
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=Path("answer.wav"),
            format="wav",
            sample_rate_hz=22050,
        )
    )
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert backend.speak("Hello from the cloud", cloud_settings(), cancel_event=cancel_event)
    assert client.speak_calls[0]["cancel_event"] is cancel_event
    assert play_wav.calls[0]["cancel_event"] is cancel_event


def test_tts_removes_worker_wav_after_successful_playback(tmp_path: Path) -> None:
    audio_path = tmp_path / "answer.wav"
    audio_path.write_bytes(b"RIFF")
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=22050,
        )
    )
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=FakeWavPlayer())

    assert backend.speak("Hello from the cloud", cloud_settings())
    assert not audio_path.exists()


def test_tts_removes_worker_wav_after_failed_playback(tmp_path: Path) -> None:
    audio_path = tmp_path / "answer.wav"
    audio_path.write_bytes(b"RIFF")
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=22050,
        )
    )
    backend = CloudWorkerTextToSpeechBackend(
        client=client,
        play_wav=FakeWavPlayer(result=False),
    )

    assert not backend.speak("Hello from the cloud", cloud_settings())
    assert not audio_path.exists()


def test_tts_empty_text_returns_false_without_calling_client() -> None:
    client = FakeVoiceWorkerClient()
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert not backend.speak("  ", cloud_settings())
    assert client.speak_calls == []
    assert play_wav.calls == []


def test_tts_cloud_worker_disabled_returns_false_without_calling_client() -> None:
    client = FakeVoiceWorkerClient()
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert not backend.speak("Hello", cloud_settings(cloud_worker_enabled=False))
    assert client.speak_calls == []
    assert play_wav.calls == []


def test_tts_client_exception_returns_false() -> None:
    client = FakeVoiceWorkerClient(exc=RuntimeError("worker unavailable"))
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert not backend.speak("Hello", cloud_settings())
    assert len(client.speak_calls) == 1
    assert play_wav.calls == []


def test_tts_playback_exception_returns_false_and_removes_worker_wav(tmp_path: Path) -> None:
    audio_path = tmp_path / "answer.wav"
    audio_path.write_bytes(b"RIFF")
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=22050,
        )
    )
    play_wav = FakeWavPlayer(exc=RuntimeError("playback failed"))
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert not backend.speak("Hello", cloud_settings())
    assert len(client.speak_calls) == 1
    assert len(play_wav.calls) == 1
    assert not audio_path.exists()


def test_tts_cleanup_does_not_raise_for_directory_output_path(tmp_path: Path) -> None:
    audio_path = tmp_path / "worker-output"
    audio_path.mkdir()
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=22050,
        )
    )
    backend = CloudWorkerTextToSpeechBackend(
        client=client,
        play_wav=FakeWavPlayer(result=False),
    )

    assert not backend.speak("Hello", cloud_settings())
    assert audio_path.exists()
    assert audio_path.is_dir()


def test_tts_does_not_delete_regular_wav_outside_worker_temp_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    worker_temp_dir = tmp_path / "worker-temp"
    worker_temp_dir.mkdir()
    outside_temp_dir = tmp_path / "outside-temp"
    outside_temp_dir.mkdir()
    audio_path = outside_temp_dir / "answer.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(worker_temp_dir))
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=22050,
        )
    )
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=FakeWavPlayer())

    assert backend.speak("Hello", cloud_settings())
    assert audio_path.exists()
    assert audio_path.is_file()


def test_tts_passes_configured_speaker_device_to_playback() -> None:
    client = FakeVoiceWorkerClient()
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert backend.speak("Hello", cloud_settings(speaker_device_id="plughw:CARD=Headset"))
    assert play_wav.calls[0]["device_id"] == "plughw:CARD=Headset"


def test_tts_playback_timeout_tracks_generated_wav_duration(tmp_path: Path) -> None:
    audio_path = tmp_path / "long-response.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * 9)
    client = FakeVoiceWorkerClient(
        speech=VoiceWorkerSpeakResult(
            audio_path=audio_path,
            format="wav",
            sample_rate_hz=16000,
        )
    )
    play_wav = FakeWavPlayer()
    backend = CloudWorkerTextToSpeechBackend(client=client, play_wav=play_wav)

    assert backend.speak("This is a longer response.", cloud_settings())
    assert play_wav.calls[0]["timeout_seconds"] == 11.0


def test_package_level_backend_exports_work() -> None:
    from yoyopod.backends import voice

    assert voice.CloudWorkerSpeechToTextBackend is CloudWorkerSpeechToTextBackend
    assert voice.CloudWorkerTextToSpeechBackend is CloudWorkerTextToSpeechBackend
