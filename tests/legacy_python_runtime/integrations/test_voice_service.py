"""Tests for the initial local voice interfaces."""

from __future__ import annotations

import io
import math
import struct
from pathlib import Path
import subprocess
import threading
import time

import pytest

import yoyopod.backends.voice.output as voice_output
import yoyopod.backends.voice as voice_backends
from yoyopod.backends.voice import (
    AlsaOutputPlayer,
    EspeakNgTextToSpeechBackend,
    SubprocessAudioCaptureBackend,
)
from yoyopod.integrations.voice import (
    VOICE_COMMAND_GRAMMAR,
    VoiceCaptureRequest,
    VoiceCommandIntent,
    VoiceService,
    VoiceSettings,
    VoiceTranscript,
    match_voice_command,
)


class FakeSttBackend:
    """Simple STT double for service wiring tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, VoiceSettings]] = []
        self.clear_cache_calls = 0

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.stt_enabled

    def transcribe(
        self,
        audio_path: Path,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        self.calls.append((audio_path, settings))
        return VoiceTranscript(text="call mom", confidence=0.91)

    def clear_cache(self) -> None:
        self.clear_cache_calls += 1


class FakeTtsBackend:
    """Simple TTS double for service wiring tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, VoiceSettings, threading.Event | None]] = []

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.tts_enabled

    def speak(
        self,
        text: str,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self.calls.append((text, settings, cancel_event))
        return True


class FakeCaptureBackend:
    """Simple capture double for end-to-end capture/transcribe tests."""

    def __init__(self, path: Path | None = None) -> None:
        self.calls: list[tuple[VoiceCaptureRequest, VoiceSettings]] = []
        self.path = path or Path("/tmp/captured.wav")

    def is_available(self, settings: VoiceSettings) -> bool:
        return settings.stt_enabled and not settings.mic_muted

    def capture(self, request: VoiceCaptureRequest, settings: VoiceSettings):
        from yoyopod.integrations.voice import VoiceCaptureResult

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


@pytest.mark.parametrize(
    ("phrase", "expected_contact_name"),
    [
        ("call mama", "mama"),
        ("call mommy", "mommy"),
        ("call my mama", "mama"),
        ("please call my mom", "mom"),
        ("ring mama", "mama"),
        ("phone mom", "mom"),
        ("call daddy", "daddy"),
        ("call papa", "papa"),
        ("ring papa", "papa"),
    ],
)
def test_match_voice_command_handles_family_call_variations(
    phrase: str, expected_contact_name: str
) -> None:
    """Family call variants should resolve to a contact-bearing call command."""

    match = match_voice_command(phrase)

    assert match.intent is VoiceCommandIntent.CALL_CONTACT
    assert match.contact_name == expected_contact_name


@pytest.mark.parametrize(
    "phrase",
    [
        "Kual mama?",
        "\uace0 \ub9c8\ub9c8",
        "\u06a9\u0648\u0644 \u0645\u0627\u0645\u0627",
        "\u06a9\u0648 \u0645\u0627\u0645\u0627",
    ],
)
def test_match_voice_command_handles_observed_stt_noise_for_call_mama(phrase: str) -> None:
    """Observed ASR variants of "call mama" should still resolve to the call command."""

    match = match_voice_command(phrase)

    assert match.intent is VoiceCommandIntent.CALL_CONTACT
    assert match.contact_name == "mama"


@pytest.mark.parametrize(
    ("phrase", "expected_intent"),
    [
        ("play a song", VoiceCommandIntent.PLAY_MUSIC),
        ("play songs", VoiceCommandIntent.PLAY_MUSIC),
        ("put on music", VoiceCommandIntent.PLAY_MUSIC),
        ("start songs", VoiceCommandIntent.PLAY_MUSIC),
        ("play kids music", VoiceCommandIntent.PLAY_MUSIC),
        ("play", VoiceCommandIntent.PLAY_MUSIC),
        ("\u63a8,\u97f3\u4e50", VoiceCommandIntent.PLAY_MUSIC),
        ("louder", VoiceCommandIntent.VOLUME_UP),
        ("make it louder", VoiceCommandIntent.VOLUME_UP),
        ("too quiet", VoiceCommandIntent.VOLUME_UP),
        ("quieter", VoiceCommandIntent.VOLUME_DOWN),
        ("make it quieter", VoiceCommandIntent.VOLUME_DOWN),
        ("too loud", VoiceCommandIntent.VOLUME_DOWN),
    ],
)
def test_match_voice_command_handles_music_and_volume_variations(
    phrase: str, expected_intent: VoiceCommandIntent
) -> None:
    """Common kid-friendly music and volume phrasings should match fixed commands."""

    assert match_voice_command(phrase).intent is expected_intent


@pytest.mark.parametrize(
    ("phrase", "expected_intent"),
    [
        ("read this", VoiceCommandIntent.READ_SCREEN),
        ("what is on the screen", VoiceCommandIntent.READ_SCREEN),
        ("tell me what is on the screen", VoiceCommandIntent.READ_SCREEN),
        ("turn off the mic", VoiceCommandIntent.MUTE_MIC),
        ("turn off microphone", VoiceCommandIntent.MUTE_MIC),
        ("turn off the microphone", VoiceCommandIntent.MUTE_MIC),
        ("mute the mic", VoiceCommandIntent.MUTE_MIC),
        ("mute the microphone", VoiceCommandIntent.MUTE_MIC),
        ("turn on the mic", VoiceCommandIntent.UNMUTE_MIC),
        ("turn on microphone", VoiceCommandIntent.UNMUTE_MIC),
        ("turn on the microphone", VoiceCommandIntent.UNMUTE_MIC),
        ("unmute the mic", VoiceCommandIntent.UNMUTE_MIC),
        ("unmute the microphone", VoiceCommandIntent.UNMUTE_MIC),
    ],
)
def test_match_voice_command_handles_screen_and_mic_variations(
    phrase: str, expected_intent: VoiceCommandIntent
) -> None:
    """Screen reading and mic state phrases should match existing intents."""

    assert match_voice_command(phrase).intent is expected_intent


@pytest.mark.parametrize(
    "phrase",
    [
        "loud",
        "quiet",
        "not louder",
        "not quieter",
        "not make it louder",
        "do not make it louder",
        "not make it quieter",
        "do not make it quieter",
        "make it not louder",
        "turn volume not up",
        "volume not down",
        "not too loud",
        "it is not too quiet",
        "read this book",
        "read this message",
        "read this contact",
        "turn on the music",
        "turn off the music",
        "turn on the light",
        "turn off the light",
        "mute music",
        "unmute music",
        "play a game",
        "put on jacket",
        "put on shoes",
        "put on headphones",
        "do not call mom",
        "don't call mom",
        "never call dad",
        "can't call mom",
        "cannot call mom",
        "won't call mom",
        "do n't call mom",
        "can t call mom",
        "do nt call mom",
        "do n t call mom",
        "don t call mom",
        "won t call mom",
        "please don t call mom",
        "call not mom",
    ],
)
def test_match_voice_command_rejects_nearby_non_commands(phrase: str) -> None:
    """Short command phrases should not match negations or object-reading requests."""

    assert match_voice_command(phrase).intent is VoiceCommandIntent.UNKNOWN


@pytest.mark.parametrize(
    ("phrase", "expected_intent"),
    [
        ("read this please", VoiceCommandIntent.READ_SCREEN),
        ("play a song please", VoiceCommandIntent.PLAY_MUSIC),
        ("turn off the mic please", VoiceCommandIntent.MUTE_MIC),
        ("turn on microphone now", VoiceCommandIntent.UNMUTE_MIC),
    ],
)
def test_match_voice_command_accepts_polite_exact_trigger_suffixes(
    phrase: str, expected_intent: VoiceCommandIntent
) -> None:
    """Exact triggers should allow harmless polite suffixes."""

    assert match_voice_command(phrase).intent is expected_intent


@pytest.mark.parametrize("template", VOICE_COMMAND_GRAMMAR)
def test_voice_command_grammar_examples_match_template_intents(template) -> None:
    """Each declared example should be executable by the deterministic matcher."""

    for example in template.examples:
        assert match_voice_command(example).intent is template.intent


@pytest.mark.parametrize("template", VOICE_COMMAND_GRAMMAR)
def test_voice_command_exact_trigger_phrases_are_declared_triggers(template) -> None:
    """Exact-match trigger declarations should stay tied to real trigger phrases."""

    assert set(template.exact_trigger_phrases) <= set(template.trigger_phrases)


def test_match_voice_command_handles_basic_device_actions() -> None:
    """Volume and mic commands should resolve deterministically."""

    assert match_voice_command("volume up").intent is VoiceCommandIntent.VOLUME_UP
    assert match_voice_command("mute microphone").intent is VoiceCommandIntent.MUTE_MIC
    assert match_voice_command("what time is it").intent is VoiceCommandIntent.UNKNOWN


def test_match_voice_command_handles_cloud_stt_script_transliterated_controls() -> None:
    """Cloud STT can return English command words in Arabic/Persian script."""

    assert match_voice_command("وولیوم اپ").intent is VoiceCommandIntent.VOLUME_UP
    assert match_voice_command("پلی موزیک").intent is VoiceCommandIntent.PLAY_MUSIC


def test_match_voice_command_accepts_fuzzy_basic_phrases() -> None:
    """The grammar layer should tolerate basic filler words and phrasing variants."""

    assert match_voice_command("please call mom").intent is VoiceCommandIntent.CALL_CONTACT
    assert match_voice_command("turn it up").intent is VoiceCommandIntent.VOLUME_UP
    assert match_voice_command("play some music").intent is VoiceCommandIntent.PLAY_MUSIC


def test_match_voice_command_accepts_injected_grammar() -> None:
    """Callers should be able to match against dictionary-derived grammar."""

    from yoyopod.integrations.voice.commands import VoiceCommandTemplate

    grammar = (
        VoiceCommandTemplate(
            intent=VoiceCommandIntent.VOLUME_UP,
            trigger_phrases=("boost sound",),
            examples=("boost sound",),
            fuzzy_threshold=0.9,
        ),
    )

    assert (
        match_voice_command("boost sound", grammar=grammar).intent is VoiceCommandIntent.VOLUME_UP
    )
    assert match_voice_command("volume up", grammar=grammar).intent is VoiceCommandIntent.UNKNOWN


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
    assert tts_backend.calls == [("Calling mom", settings, None)]


def test_voice_backend_exports_do_not_include_retired_offline_stt_backend() -> None:
    """The public voice backend surface should not expose the retired offline STT backend."""

    retired_backend_name = "Vo" + "skSpeechToTextBackend"
    assert retired_backend_name not in voice_backends.__all__
    with pytest.raises(AttributeError):
        getattr(voice_backends, retired_backend_name)


def test_voice_service_passes_cancel_event_to_tts_backend() -> None:
    """Service-level TTS should propagate cancellation to concrete backends."""

    settings = VoiceSettings()
    tts_backend = FakeTtsBackend()
    service = VoiceService(settings=settings, tts_backend=tts_backend)
    cancel_event = threading.Event()

    assert service.speak("A long answer", cancel_event=cancel_event) is True
    assert tts_backend.calls == [("A long answer", settings, cancel_event)]


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
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.backends.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)

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
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)

    backend = SubprocessAudioCaptureBackend()
    result = backend.capture(
        VoiceCaptureRequest(mode="voice_commands", timeout_seconds=2.0),
        VoiceSettings(capture_device_id="ALSA: wm8960-soundcard"),
    )

    assert result.recorded is True
    assert popen_calls[0][popen_calls[0].index("-D") + 1] == "plughw:CARD=wm8960soundcard,DEV=0"


def test_subprocess_audio_capture_backend_respects_configured_card_before_capture_facade(
    monkeypatch,
) -> None:
    """Configured card labels should be tried before generic capture facade routes."""

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
                (
                    "default\n"
                    "playback\n"
                    "capture\n"
                    "array\n"
                    "plughw:CARD=wm8960soundcard,DEV=0\n"
                    "hw:CARD=wm8960soundcard,DEV=0\n"
                ),
                "",
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)

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
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)

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
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.backends.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)

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
        "yoyopod.backends.voice.capture.shutil.which",
        lambda b: "/usr/bin/arecord" if b == "arecord" else None,
    )
    monkeypatch.setattr(
        "yoyopod.backends.voice.capture.subprocess.run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr("yoyopod.backends.voice.capture.subprocess.Popen", fake_popen)
    monkeypatch.setattr("yoyopod.backends.voice.capture.select.select", fake_select)
    monkeypatch.setattr("yoyopod.backends.voice.capture.os.read", fake_os_read)

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
        "yoyopod.backends.voice.tts.shutil.which",
        lambda binary: "/usr/bin/espeak-ng" if binary == "espeak-ng" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.tts.subprocess.run", fake_run)

    backend = EspeakNgTextToSpeechBackend()
    playback_calls: list[Path] = []
    monkeypatch.setattr(
        backend.output_player,
        "play_wav",
        lambda path, timeout_seconds=10.0: playback_calls.append(path) or True,
    )

    settings = VoiceSettings(tts_backend="espeak-ng", tts_rate_wpm=170, tts_voice="en-us")

    assert backend.speak("Calling mama", settings) is True
    assert calls[0][:6] == ["espeak-ng", "-w", calls[0][2], "-s", "170", "-v"]
    assert calls[0][6:] == ["en-us", "Calling mama"]
    assert playback_calls == [Path(calls[0][2])]


def test_espeak_backend_passes_cancel_event_to_playback(monkeypatch) -> None:
    """Rendered local TTS playback should remain cancellable."""

    cancel_event = threading.Event()

    class _SuccessfulEspeakPopen:
        def __init__(self, args: list[str], **_kwargs) -> None:
            self.args = args
            self.returncode = 0
            Path(args[2]).write_bytes(b"RIFF")

        def poll(self) -> int | None:
            return self.returncode

        def communicate(self) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(
        "yoyopod.backends.voice.tts.shutil.which",
        lambda binary: "/usr/bin/espeak-ng" if binary == "espeak-ng" else None,
    )
    monkeypatch.setattr(
        "yoyopod.backends.voice.tts.subprocess.Popen",
        lambda args, **kwargs: _SuccessfulEspeakPopen(args, **kwargs),
    )

    backend = EspeakNgTextToSpeechBackend()
    playback_cancel_events: list[threading.Event | None] = []
    monkeypatch.setattr(
        backend.output_player,
        "play_wav",
        lambda path, timeout_seconds=10.0, cancel_event=None: playback_cancel_events.append(
            cancel_event
        )
        or True,
    )

    assert (
        backend.speak(
            "Calling mama",
            VoiceSettings(tts_backend="espeak-ng"),
            cancel_event=cancel_event,
        )
        is True
    )
    assert playback_cancel_events == [cancel_event]


def test_espeak_backend_cancel_event_terminates_active_render(monkeypatch) -> None:
    """Cancellable local TTS should stop an active espeak-ng render process."""

    cancel_event = threading.Event()
    popens: list[object] = []

    class _BlockingEspeakPopen:
        def __init__(self, args: list[str], **_kwargs) -> None:
            self.args = args
            self.returncode: int | None = None
            self.terminated = False
            self.killed = False
            self.poll_calls = 0

        def poll(self) -> int | None:
            self.poll_calls += 1
            if self.poll_calls == 1:
                cancel_event.set()
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode if self.returncode is not None else 0

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def communicate(self) -> tuple[str, str]:
            return "", ""

    def fake_popen(args: list[str], **kwargs) -> _BlockingEspeakPopen:
        proc = _BlockingEspeakPopen(args, **kwargs)
        popens.append(proc)
        return proc

    monkeypatch.setattr(
        "yoyopod.backends.voice.tts.shutil.which",
        lambda binary: "/usr/bin/espeak-ng" if binary == "espeak-ng" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.tts.subprocess.Popen", fake_popen)

    backend = EspeakNgTextToSpeechBackend()

    assert (
        backend.speak(
            "Calling mama",
            VoiceSettings(tts_backend="espeak-ng"),
            cancel_event=cancel_event,
        )
        is False
    )
    assert len(popens) == 1
    assert popens[0].args[:2] == ["espeak-ng", "-w"]
    assert popens[0].terminated is True


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
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.run", fake_run)

    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path) is True
    assert calls[1][:4] == ["aplay", "-q", "-D", "plughw:CARD=SE,DEV=0"]


def test_alsa_output_player_respects_configured_card_before_playback_facade(
    monkeypatch, tmp_path
) -> None:
    """Configured card labels should be tried before generic playback facade routes."""

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
                    "default\n"
                    "playback\n"
                    "capture\n"
                    "dmixed\n"
                    "plughw:CARD=wm8960soundcard,DEV=0\n"
                    "sysdefault:CARD=wm8960soundcard\n"
                ),
                stderr="",
            )
        if args[:4] == ["aplay", "-q", "-D", "plughw:CARD=wm8960soundcard,DEV=0"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="busy")

    monkeypatch.setattr(
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.run", fake_run)

    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path, device_id="ALSA: wm8960-soundcard") is True
    assert calls[1][:4] == ["aplay", "-q", "-D", "plughw:CARD=wm8960soundcard,DEV=0"]


def test_alsa_output_player_can_skip_when_playback_lock_is_busy(monkeypatch, tmp_path) -> None:
    """Local feedback should be able to avoid blocking behind an active TTS playback."""

    audio_path = tmp_path / "tone.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )

    assert voice_output._PLAYBACK_LOCK.acquire(blocking=False)
    try:
        player = AlsaOutputPlayer()
        started_at = time.monotonic()

        assert player.play_wav(audio_path, block_if_busy=False) is False
        assert time.monotonic() - started_at < 0.1
    finally:
        voice_output._PLAYBACK_LOCK.release()


def test_alsa_output_player_tries_next_route_after_playback_timeout(monkeypatch, tmp_path) -> None:
    """A timeout on one ALSA route should not block a later configured fallback."""

    calls: list[list[str]] = []
    audio_path = tmp_path / "tone.wav"
    audio_path.write_bytes(b"RIFF")

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["aplay", "-L"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="playback\nplughw:CARD=wm8960soundcard,DEV=0\n",
                stderr="",
            )
        if args[:4] == ["aplay", "-q", "-D", "playback"]:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        if args[:4] == ["aplay", "-q", "-D", "plughw:CARD=wm8960soundcard,DEV=0"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="bad")

    monkeypatch.setattr(
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.run", fake_run)

    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path, device_id="playback", timeout_seconds=0.01) is True
    assert calls == [
        ["aplay", "-L"],
        ["aplay", "-q", "-D", "playback", str(audio_path)],
        ["aplay", "-q", "-D", "plughw:CARD=wm8960soundcard,DEV=0", str(audio_path)],
    ]


def test_alsa_output_player_cancel_event_terminates_active_aplay(
    monkeypatch,
    tmp_path,
) -> None:
    """Cancellable playback should stop an active aplay process promptly."""

    audio_path = tmp_path / "tone.wav"
    audio_path.write_bytes(b"RIFF")
    cancel_event = threading.Event()
    popens: list[object] = []

    class _BlockingAplayPopen:
        def __init__(self, args: list[str], **_kwargs) -> None:
            self.args = args
            self.returncode: int | None = None
            self.terminated = False
            self.killed = False
            self.stdout = b""
            self.stderr = b""
            self.poll_calls = 0

        def poll(self) -> int | None:
            self.poll_calls += 1
            if self.poll_calls == 1:
                cancel_event.set()
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode if self.returncode is not None else 0

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def communicate(self) -> tuple[str, str]:
            return "", ""

    def fake_popen(args: list[str], **kwargs) -> _BlockingAplayPopen:
        proc = _BlockingAplayPopen(args, **kwargs)
        popens.append(proc)
        return proc

    def fake_run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        assert args == ["aplay", "-L"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="playback\n", stderr="")

    monkeypatch.setattr(
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )
    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.run", fake_run)
    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.Popen", fake_popen)

    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path, device_id="playback", cancel_event=cancel_event) is False
    assert len(popens) == 1
    assert popens[0].args == ["aplay", "-q", "-D", "playback", str(audio_path)]
    assert popens[0].terminated is True
    assert popens[0].killed is False


def test_alsa_output_player_pre_cancel_skips_device_scan(monkeypatch, tmp_path) -> None:
    """Already-cancelled playback should not block on ALSA device discovery."""

    audio_path = tmp_path / "tone.wav"
    audio_path.write_bytes(b"RIFF")
    cancel_event = threading.Event()
    cancel_event.set()

    monkeypatch.setattr(
        "yoyopod.backends.voice.output.shutil.which",
        lambda binary: "/usr/bin/aplay" if binary == "aplay" else None,
    )

    scan_calls: list[list[str]] = []

    def fake_scan(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        scan_calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="playback\n", stderr="")

    monkeypatch.setattr("yoyopod.backends.voice.output.subprocess.run", fake_scan)
    player = AlsaOutputPlayer()

    assert player.play_wav(audio_path, cancel_event=cancel_event) is False
    assert scan_calls == []
