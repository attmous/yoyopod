"""Tests for the initial local voice interfaces."""

from __future__ import annotations

import io
import math
import struct
from pathlib import Path
import subprocess
import sys
import threading
import types

from yoyopod.voice.capture import SubprocessAudioCaptureBackend
from yoyopod.voice.commands import (
    VOICE_COMMAND_GRAMMAR,
    VoiceCommandIntent,
    match_voice_command,
)
from yoyopod.voice.models import VoiceCaptureRequest, VoiceSettings, VoiceTranscript
from yoyopod.voice.output import AlsaOutputPlayer
from yoyopod.voice.service import VoiceService
from yoyopod.voice.stt import VoskSpeechToTextBackend
from yoyopod.voice.tts import EspeakNgTextToSpeechBackend


class FakeSttBackend:
    """Simple STT double for service wiring tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, VoiceSettings]] = []
        self.clear_cache_calls = 0

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.stt_enabled

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        self.calls.append((audio_path, settings))
        return VoiceTranscript(text="call mom", confidence=0.91)

    def clear_cache(self) -> None:
        self.clear_cache_calls += 1


class FakeTtsBackend:
    """Simple TTS double for service wiring tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, VoiceSettings]] = []

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.tts_enabled

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        self.calls.append((text, settings))
        return True


class FakeCaptureBackend:
    """Simple capture double for end-to-end capture/transcribe tests."""

    def __init__(self, path: Path | None = None) -> None:
        self.calls: list[tuple[VoiceCaptureRequest, VoiceSettings]] = []
        self.path = path or Path("/tmp/captured.wav")

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.stt_enabled and not settings.mic_muted

    def capture(self, request: VoiceCaptureRequest, settings: VoiceSettings):
        from yoyopod.voice.models import VoiceCaptureResult

        self.calls.append((request, settings))
        return VoiceCaptureResult(audio_path=self.path, recorded=True)


def test_voice_command_grammar_contains_basic_templates() -> None:
    """The grammar table should declare the baseline fuzzy commands explicitly."""

    intents = {template.intent for template in VOICE_COMMAND_GRAMMAR}

    assert VoiceCommandIntent.CALL_CONTACT in intents
    assert VoiceCommandIntent.VOLUME_UP in intents
    assert VoiceCommandIntent.PLAY_MUSIC in intents


def test_match_voice_command_extracts_contact_name() -> None:
    """Call commands should retain the spoken contact label."""

    match = match_voice_command("call mom")

    assert match.intent is VoiceCommandIntent.CALL_CONTACT
    assert match.contact_name == "mom"
    assert match.is_command is True


def test_match_voice_command_handles_basic_device_actions() -> None:
    """Volume and mic commands should resolve deterministically."""

    assert match_voice_command("volume up").intent is VoiceCommandIntent.VOLUME_UP
    assert match_voice_command("mute microphone").intent is VoiceCommandIntent.MUTE_MIC
    assert match_voice_command("what time is it").intent is VoiceCommandIntent.UNKNOWN


def test_match_voice_command_accepts_fuzzy_basic_phrases() -> None:
    """The grammar layer should tolerate basic filler words and phrasing variants."""

    assert match_voice_command("please call mom").intent is VoiceCommandIntent.CALL_CONTACT
    assert match_voice_command("turn it up").intent is VoiceCommandIntent.VOLUME_UP
    assert match_voice_command("play some music").intent is VoiceCommandIntent.PLAY_MUSIC


def test_voice_service_uses_injected_backends() -> None:
    """The service should delegate STT/TTS work to the configured backends."""

    settings = VoiceSettings(screen_read_enabled=True, output_volume=72)
    stt_backend = FakeSttBackend()
    tts_backend = FakeTtsBackend()
    service = VoiceService(settings=settings, stt_backend=stt_backend, tts_backend=tts_backend)
    audio_path = Path("/tmp/sample.wav")

    transcript = service.transcribe(audio_path)
    command = service.match_command(transcript.text)
    spoken = service.speak("Calling mom")

    assert transcript.text == "call mom"
    assert stt_backend.calls == [(audio_path, settings)]
    assert command.intent is VoiceCommandIntent.CALL_CONTACT
    assert command.contact_name == "mom"
    assert spoken is True
    assert tts_backend.calls == [("Calling mom", settings)]


def test_voice_service_release_resources_clears_stt_backend_cache() -> None:
    """Replacing a voice service should clear any backend-owned STT cache."""

    stt_backend = FakeSttBackend()
    service = VoiceService(settings=VoiceSettings(), stt_backend=stt_backend)

    service.release_resources()

    assert stt_backend.clear_cache_calls == 1


def test_voice_capture_request_defaults_to_short_local_capture() -> None:
    """Capture requests should default to the local command-friendly timeout."""

    request = VoiceCaptureRequest(mode="voice_commands")

    assert request.audio_path is None
    assert request.timeout_seconds == 4.0


def test_voice_service_can_capture_then_transcribe() -> None:
    """The service should record then transcribe when a capture backend is provided."""

    settings = VoiceSettings()
    capture_backend = FakeCaptureBackend()
    stt_backend = FakeSttBackend()
    service = VoiceService(
        settings=settings, capture_backend=capture_backend, stt_backend=stt_backend
    )

    transcript = service.capture_and_transcribe(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=3.0)
    )

    assert transcript.text == "call mom"
    assert capture_backend.calls[0][0].mode == "voice_commands"
    assert stt_backend.calls == [(Path("/tmp/captured.wav"), settings)]


def test_voice_service_cleans_up_captured_temp_file_after_transcribe(tmp_path) -> None:
    """Service-level capture helpers should not leak temporary recordings."""

    audio_path = tmp_path / "captured.wav"
    audio_path.write_bytes(b"RIFF")
    service = VoiceService(
        settings=VoiceSettings(),
        capture_backend=FakeCaptureBackend(path=audio_path),
        stt_backend=FakeSttBackend(),
    )

    transcript = service.capture_and_transcribe(VoiceCaptureRequest(mode="voice_commands"))

    assert transcript.text == "call mom"
    assert not audio_path.exists()


def _make_pcm(amplitude: int, chunks: int, chunk_frames: int = 1280) -> bytes:
    """Build raw 16-bit mono PCM with the given constant amplitude."""
    frame = struct.pack("<h", amplitude) * chunk_frames
    return frame * chunks


class _FakePopen:
    """Minimal Popen double that feeds pre-built PCM from stdout."""

    def __init__(self, args: list[str], data: bytes = b"", returncode: int = 0) -> None:
        self.args = args
        self.returncode = returncode
        self.stdout = io.BytesIO(data)
        self.stderr = io.BytesIO(b"")

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


class _CountingStdout(io.BytesIO):
    """BytesIO variant that tracks how many capture reads occurred."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_calls = 0

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        return super().read(size)


class _CountingPopen(_FakePopen):
    """Popen double with read-call accounting for timeout tests."""

    def __init__(self, args: list[str], data: bytes = b"", returncode: int = 0) -> None:
        super().__init__(args, data=data, returncode=returncode)
        self.stdout = _CountingStdout(data)


class _SelectableStdout:
    """Pipe-like stdout double that can be polled with select()."""

    def fileno(self) -> int:
        return 42


class _SelectablePopen:
    """Popen double for idle-pipe cancellation tests."""

    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.returncode = 0
        self.stdout = _SelectableStdout()
        self.stderr = io.BytesIO(b"")
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


def test_subprocess_audio_capture_backend_builds_arecord_command(monkeypatch) -> None:
    """Capture should invoke arecord in raw streaming mode on the correct device."""

    popen_calls: list[list[str]] = []
    # 3 silent + 4 speech (≥ _SPEECH_CONFIRM_CHUNKS=2) + 6 silent chunks
    pcm = (
        _make_pcm(100, 3)  # silence  (below _SPEECH_RMS_THRESHOLD)
        + _make_pcm(800, 4)  # speech   (≥ _SPEECH_CONFIRM_CHUNKS consecutive)
        + _make_pcm(100, 6)  # silence  (triggers stop after _SILENCE_AFTER_SPEECH_MS)
    )

    def fake_popen(args: list[str], **_kwargs) -> _FakePopen:
        popen_calls.append(args)
        return _FakePopen(args, data=pcm)

    monkeypatch.setattr(
        "yoyopod.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.Popen", fake_popen)

    backend = SubprocessAudioCaptureBackend()
    result = backend.capture(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=4.0), VoiceSettings()
    )

    assert result.recorded is True
    assert result.audio_path is not None and result.audio_path.exists()
    # Command must be raw-stream mode ending with "-"
    assert popen_calls[0][:4] == ["arecord", "-t", "raw", "-f"]
    assert popen_calls[0][-1] == "-"


def test_subprocess_audio_capture_backend_falls_back_to_discovered_device(monkeypatch) -> None:
    """Configured capture-device names should map to the right discovered ALSA route first."""

    pcm = _make_pcm(100, 3) + _make_pcm(800, 4) + _make_pcm(100, 6)
    popen_calls: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs) -> _FakePopen:
        popen_calls.append(args)
        if "-D" in args and args[args.index("-D") + 1] == "plughw:CARD=wm8960soundcard,DEV=0":
            return _FakePopen(args, data=pcm, returncode=0)
        return _FakePopen(args, data=b"", returncode=1)

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if args == ["arecord", "-L"]:
            return subprocess.CompletedProcess(
                args,
                0,
                "hw:CARD=SE,DEV=0\nplughw:CARD=wm8960soundcard,DEV=0\nhw:CARD=wm8960soundcard,DEV=0\n",
                "",
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(
        "yoyopod.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.Popen", fake_popen)

    backend = SubprocessAudioCaptureBackend()
    result = backend.capture(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=2.0),
        VoiceSettings(capture_device_id="ALSA: wm8960-soundcard"),
    )

    assert result.recorded is True
    assert popen_calls[0][popen_calls[0].index("-D") + 1] == "plughw:CARD=wm8960soundcard,DEV=0"


def test_subprocess_audio_capture_backend_falls_back_when_preferred_device_breaks(
    monkeypatch,
) -> None:
    """A stale preferred device should not block fallback to the configured/discovered route."""

    pcm = _make_pcm(100, 3) + _make_pcm(800, 4) + _make_pcm(100, 6)
    popen_calls: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs) -> _FakePopen:
        popen_calls.append(args)
        if "-D" in args and args[args.index("-D") + 1] == "plughw:CARD=wm8960soundcard,DEV=0":
            return _FakePopen(args, data=pcm, returncode=0)
        return _FakePopen(args, data=b"", returncode=1)

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if args == ["arecord", "-L"]:
            return subprocess.CompletedProcess(args, 0, "plughw:CARD=wm8960soundcard,DEV=0\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(
        "yoyopod.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.Popen", fake_popen)

    backend = SubprocessAudioCaptureBackend()
    backend._preferred_device = "plughw:CARD=old,DEV=0"

    result = backend.capture(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=2.0),
        VoiceSettings(capture_device_id="ALSA: wm8960-soundcard"),
    )

    assert result.recorded is True
    assert popen_calls[0][popen_calls[0].index("-D") + 1] == "plughw:CARD=old,DEV=0"
    assert popen_calls[1][popen_calls[1].index("-D") + 1] == "plughw:CARD=wm8960soundcard,DEV=0"


def test_subprocess_audio_capture_backend_hard_timeout_stays_within_requested_window(
    monkeypatch,
) -> None:
    """Once speech starts, capture should not add the full pre-speech window on top."""

    popens: list[_CountingPopen] = []
    pcm = _make_pcm(800, 200)

    def fake_popen(args: list[str], **_kwargs) -> _CountingPopen:
        proc = _CountingPopen(args, data=pcm)
        popens.append(proc)
        return proc

    monkeypatch.setattr(
        "yoyopod.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.Popen", fake_popen)

    backend = SubprocessAudioCaptureBackend()
    result = backend.capture(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=4.0), VoiceSettings()
    )

    assert result.recorded is True
    assert popens[0].stdout.read_calls <= math.ceil((4.0 + 1.0) * 1000 / 80)


def test_subprocess_audio_capture_backend_ptt_cancel_interrupts_idle_pipe(monkeypatch) -> None:
    """PTT release should stop capture even if arecord is not yielding bytes yet."""

    cancel_event = threading.Event()
    popens: list[_SelectablePopen] = []
    os_read_calls = 0

    def fake_popen(args: list[str], **_kwargs) -> _SelectablePopen:
        proc = _SelectablePopen(args)
        popens.append(proc)
        return proc

    def fake_select(_readers, _writers, _errors, _timeout=None):
        cancel_event.set()
        return [], [], []

    def fake_os_read(_fd: int, _size: int) -> bytes:
        nonlocal os_read_calls
        os_read_calls += 1
        return b""

    monkeypatch.setattr(
        "yoyopod.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.voice.capture.subprocess.Popen", fake_popen)
    monkeypatch.setattr("yoyopod.voice.capture.select.select", fake_select)
    monkeypatch.setattr("yoyopod.voice.capture.os.read", fake_os_read)

    backend = SubprocessAudioCaptureBackend()
    result = backend.capture(
        VoiceCaptureRequest(
            mode="voice_commands_ptt",
            timeout_seconds=2.0,
            cancel_event=cancel_event,
        ),
        VoiceSettings(),
    )

    assert result.recorded is False
    assert result.audio_path is None
    assert popens[0].terminated is True
    assert os_read_calls == 0


def test_espeak_backend_builds_expected_command(monkeypatch) -> None:
    """TTS should invoke espeak-ng with the configured rate and voice."""

    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["espeak-ng", "-w"]:
            Path(args[2]).write_bytes(b"RIFF")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "yoyopod.voice.tts.shutil.which",
        lambda binary: "/usr/bin/espeak-ng" if binary == "espeak-ng" else None,
    )
    monkeypatch.setattr("yoyopod.voice.tts.subprocess.run", fake_run)

    backend = EspeakNgTextToSpeechBackend()
    playback_calls: list[Path] = []
    monkeypatch.setattr(
        backend.output_player,
        "play_wav",
        lambda path, timeout_seconds=10.0: playback_calls.append(path) or True,
    )

    assert backend.speak("Calling mama", VoiceSettings(tts_rate_wpm=170, tts_voice="en-us")) is True
    assert calls[0][:6] == ["espeak-ng", "-w", calls[0][2], "-s", "170", "-v"]
    assert calls[0][6:] == ["en-us", "Calling mama"]
    assert playback_calls == [Path(calls[0][2])]


def test_alsa_output_player_prefers_usb_card_routes(monkeypatch, tmp_path) -> None:
    """Playback should prefer discovered non-HDMI ALSA devices."""

    calls: list[list[str]] = []
    audio_path = tmp_path / "tone.wav"
    audio_path.write_bytes(b"RIFF")

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["aplay", "-L"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "default:CARD=vc4hdmi\n"
                    "plughw:CARD=SE,DEV=0\n"
                    "default:CARD=SE\n"
                    "sysdefault:CARD=SE\n"
                ),
                stderr="",
            )
        if args[:4] == ["aplay", "-q", "-D", "plughw:CARD=SE,DEV=0"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="bad")

    monkeypatch.setattr(
        "yoyopod.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )
    monkeypatch.setattr("yoyopod.voice.output.subprocess.run", fake_run)

    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path) is True
    assert calls[1][:4] == ["aplay", "-q", "-D", "plughw:CARD=SE,DEV=0"]


def test_vosk_backend_requires_module_and_model(tmp_path, monkeypatch) -> None:
    """Vosk availability should stay false until both module and model are present."""

    monkeypatch.setattr("yoyopod.voice.stt.importlib.util.find_spec", lambda name: None)
    backend = VoskSpeechToTextBackend()

    assert (
        backend.is_available(VoiceSettings(vosk_model_path=str(tmp_path / "missing-model")))
        is False
    )


def test_vosk_backend_keeps_model_cache_per_instance() -> None:
    """One backend instance should not leak cached models into another."""

    first = VoskSpeechToTextBackend()
    second = VoskSpeechToTextBackend()

    first._model_cache["/tmp/model-a"] = object()

    assert second._model_cache == {}


def test_vosk_backend_can_clear_cached_models() -> None:
    """The backend should offer an explicit cache reset hook."""

    backend = VoskSpeechToTextBackend()
    backend._model_cache["/tmp/model-a"] = object()

    backend.clear_cache()

    assert backend._model_cache == {}


def test_vosk_backend_replaces_stale_cached_model_when_path_changes(tmp_path) -> None:
    """Retained-model mode should cap the cache to one loaded model path."""

    load_calls: list[str] = []

    class FakeModel:
        def __init__(self, model_path: str) -> None:
            load_calls.append(model_path)

    original_vosk = sys.modules.get("vosk")
    vosk_module = types.ModuleType("vosk")
    vosk_module.Model = FakeModel
    sys.modules["vosk"] = vosk_module
    try:
        backend = VoskSpeechToTextBackend()
        first_path = str(tmp_path / "model-a")
        second_path = str(tmp_path / "model-b")

        first_model = backend._load_model(VoiceSettings(vosk_model_path=first_path))
        second_model = backend._load_model(VoiceSettings(vosk_model_path=second_path))
    finally:
        if original_vosk is None:
            sys.modules.pop("vosk", None)
        else:
            sys.modules["vosk"] = original_vosk

    assert load_calls == [first_path, second_path]
    assert list(backend._model_cache) == [second_path]
    assert backend._model_cache[second_path] is second_model
    assert first_model is not second_model


def test_vosk_backend_can_disable_model_retention(tmp_path) -> None:
    """Best-effort low-memory mode should avoid retaining a loaded model reference."""

    load_calls: list[str] = []

    class FakeModel:
        def __init__(self, model_path: str) -> None:
            load_calls.append(model_path)

    original_vosk = sys.modules.get("vosk")
    vosk_module = types.ModuleType("vosk")
    vosk_module.Model = FakeModel
    sys.modules["vosk"] = vosk_module
    try:
        backend = VoskSpeechToTextBackend()
        model_path = str(tmp_path / "model-a")
        first_model = backend._load_model(
            VoiceSettings(
                vosk_model_path=model_path,
                vosk_model_keep_loaded=False,
            )
        )
        second_model = backend._load_model(
            VoiceSettings(
                vosk_model_path=model_path,
                vosk_model_keep_loaded=False,
            )
        )
    finally:
        if original_vosk is None:
            sys.modules.pop("vosk", None)
        else:
            sys.modules["vosk"] = original_vosk

    assert load_calls == [model_path, model_path]
    assert backend._model_cache == {}
    assert first_model is not second_model
