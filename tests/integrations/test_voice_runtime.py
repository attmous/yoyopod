"""Direct tests for the shared voice coordination seam."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

from yoyopod.core import AppContext
from yoyopod.integrations.voice import (
    VoiceCommandExecutor,
    VoiceCommandOutcome,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)
from yoyopod.integrations.voice import (
    VoiceCaptureResult,
    VoiceSettings,
    VoiceTranscript,
)


class _FakeContact:
    def __init__(self, name: str, sip_address: str, notes: str = "") -> None:
        self.name = name
        self.display_name = notes or name
        self.sip_address = sip_address
        self.notes = notes

    def preferred_call_target(
        self,
        *,
        gsm_enabled: bool = False,
    ) -> tuple[str | None, str]:
        if self.sip_address.strip():
            return "sip", self.sip_address.strip()
        return None, ""


class _FakeConfigManager:
    def __init__(self, contacts: list[_FakeContact]) -> None:
        self._contacts = contacts
        self._voice_settings = SimpleNamespace(
            assistant=SimpleNamespace(
                mode="local",
                commands_enabled=True,
                ai_requests_enabled=True,
                screen_read_enabled=False,
                stt_enabled=True,
                tts_enabled=True,
                stt_backend="dummy-stt",
                tts_backend="dummy-tts",
                vosk_model_path="models/custom-model",
                vosk_model_keep_loaded=False,
                sample_rate_hz=22050,
                record_seconds=6,
                tts_rate_wpm=180,
                tts_voice="en-us",
            ),
            audio=SimpleNamespace(
                speaker_device_id="",
                capture_device_id="",
            ),
            worker=SimpleNamespace(
                enabled=False,
                domain="voice",
                provider="mock",
                request_timeout_seconds=12.0,
                max_audio_seconds=30.0,
                stt_model="gpt-4o-mini-transcribe",
                tts_model="gpt-4o-mini-tts",
                tts_voice="alloy",
                tts_instructions="Speak clearly and briefly for a small handheld device.",
                local_feedback_enabled=True,
            ),
        )

    def get_contacts(self) -> list[_FakeContact]:
        return list(self._contacts)

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[_FakeContact]:
        return [
            contact for contact in self._contacts if contact.preferred_call_target(
                gsm_enabled=gsm_enabled
            )[0]
        ]

    def get_capture_device_id(self) -> str | None:
        return None

    def get_ring_output_device(self) -> str | None:
        return None

    def get_default_output_volume(self) -> int:
        return 61

    def get_voice_settings(self):
        return self._voice_settings


class _FakeVoipManager:
    def __init__(self) -> None:
        self.make_calls: list[tuple[str, str]] = []
        self.mute_calls = 0
        self.unmute_calls = 0

    def make_call(self, sip_address: str, contact_name: str = "") -> bool:
        self.make_calls.append((sip_address, contact_name))
        return True

    def mute(self) -> bool:
        self.mute_calls += 1
        return True

    def unmute(self) -> bool:
        self.unmute_calls += 1
        return True


class _FakeAudioVolumeController:
    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.set_calls: list[int] = []

    def set_output_volume(self, volume: int) -> bool:
        self.set_calls.append(volume)
        self.context.cache_output_volume(volume)
        return True


class _FakeVoiceService:
    def __init__(self, transcript: str) -> None:
        self.settings: VoiceSettings | None = None
        self.transcript = transcript
        self.capture_calls = 0
        self.speak_calls: list[str] = []
        self.release_calls = 0

    def capture_available(self) -> bool:
        return True

    def stt_available(self) -> bool:
        return True

    def tts_available(self) -> bool:
        return True

    def capture_audio(self, request) -> VoiceCaptureResult:
        self.capture_calls += 1
        with NamedTemporaryFile(
            prefix="voice-runtime-test-",
            suffix=".wav",
            delete=False,
        ) as handle:
            path = Path(handle.name)
        path.write_bytes(b"RIFF")
        return VoiceCaptureResult(audio_path=path, recorded=True)

    def transcribe(
        self,
        audio_path: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        return VoiceTranscript(text=self.transcript, confidence=0.91)

    def speak(self, text: str) -> bool:
        self.speak_calls.append(text)
        return True

    def release_resources(self) -> None:
        self.release_calls += 1


class _NoAudioVoiceService(_FakeVoiceService):
    def __init__(self) -> None:
        super().__init__("")

    def capture_audio(self, request) -> VoiceCaptureResult:
        self.capture_calls += 1
        return VoiceCaptureResult(audio_path=None, recorded=False)


class _FakeOutputPlayer:
    def play_wav(self, path: Path, **kwargs) -> None:
        return None


def _wait_until(predicate: Callable[[], bool], *, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    assert predicate()


def _build_executor(
    *,
    context: AppContext,
    config_manager: _FakeConfigManager | None = None,
    voip_manager: _FakeVoipManager | None = None,
    play_music_action=None,
) -> VoiceCommandExecutor:
    return VoiceCommandExecutor(
        context=context,
        config_manager=config_manager,
        people_directory=config_manager,
        voip_manager=voip_manager,
        volume_up_action=lambda step: 55,
        volume_down_action=lambda step: 45,
        mute_action=voip_manager.mute if voip_manager is not None else None,
        unmute_action=voip_manager.unmute if voip_manager is not None else None,
        play_music_action=play_music_action,
        screen_summary_provider=lambda: "You are on Ask. Say a direct command now.",
    )


def test_voice_command_executor_routes_call_and_updates_context() -> None:
    context = AppContext()
    voip_manager = _FakeVoipManager()
    executor = _build_executor(
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    outcome = executor.execute("call mom")

    assert outcome == VoiceCommandOutcome(
        "Calling",
        "Calling Mama.",
        auto_return=False,
    )
    assert context.talk.selected_contact_name == "Mama"
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]
    assert context.voice.last_transcript == "call mom"


def test_voice_command_executor_handles_local_device_actions() -> None:
    context = AppContext()
    voip_manager = _FakeVoipManager()
    executor = _build_executor(context=context, voip_manager=voip_manager)

    mute_outcome = executor.execute("mute mic")
    volume_outcome = executor.execute("volume up")

    assert mute_outcome.body == "Voice commands mic is muted."
    assert context.voice.mic_muted is True
    assert voip_manager.mute_calls == 1
    assert volume_outcome.body == "Volume is 55."
    assert context.voice.output_volume == 55


def test_voice_command_executor_volume_fallback_uses_app_context_audio_controller() -> None:
    context = AppContext()
    context.audio_volume_controller = _FakeAudioVolumeController(context)
    executor = VoiceCommandExecutor(
        context=context,
        screen_summary_provider=lambda: "screen",
    )

    outcome = executor.execute("volume up")

    assert outcome.body == "Volume is 55."
    assert context.audio_volume_controller.set_calls == [55]
    assert context.voice.output_volume == 55


def test_voice_runtime_coordinator_runs_capture_and_emits_route() -> None:
    context = AppContext()
    service = _FakeVoiceService("play music")
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_listening(async_capture=False)

    assert service.capture_calls == 1
    _wait_until(lambda: service.speak_calls == ["Starting local music."])
    assert service.speak_calls == ["Starting local music."]
    assert outcomes == [
        VoiceCommandOutcome(
            "Playing",
            "Starting local music.",
            route_name="shuffle_started",
        )
    ]
    assert context.voice.last_transcript == "play music"
    assert context.voice.last_spoken_text == "Starting local music."
    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "Playing"


def test_listening_cycle_uses_cloud_worker_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")
    outcomes: list[VoiceCommandOutcome] = []

    class _WorkerLikeVoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return True

        def tts_available(self) -> bool:
            return False

        def capture_audio(self, _request) -> VoiceCaptureResult:
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(
            self,
            path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            assert path == audio_path
            return VoiceTranscript(text="play music", confidence=1.0, is_final=True)

        def speak(self, _text: str) -> bool:
            return False

    class _CommandExecutor:
        def __init__(self) -> None:
            self.transcripts: list[str] = []

        def execute(self, transcript: str) -> VoiceCommandOutcome:
            self.transcripts.append(transcript)
            return VoiceCommandOutcome("Done", "play music", should_speak=False)

    command_executor = _CommandExecutor()
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=command_executor,
        voice_service_factory=lambda _settings: _WorkerLikeVoiceService(),
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_listening(async_capture=False)

    assert outcomes
    assert command_executor.transcripts == ["play music"]
    assert outcomes[-1] == VoiceCommandOutcome("Done", "play music", should_speak=False)
    assert coordinator._tts_thread is None
    assert not audio_path.exists()


def test_voice_runtime_coordinator_handles_disabled_voice_without_capture() -> None:
    context = AppContext()
    context.configure_voice(commands_enabled=False)
    service = _FakeVoiceService("volume up")
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
    )

    coordinator.begin_listening(async_capture=False)

    assert service.capture_calls == 0
    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "Voice Off"


def test_cloud_voice_unavailable_keeps_local_feedback_message() -> None:
    class _VoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return False

        def tts_available(self) -> bool:
            return False

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _VoiceService(),
        output_player=_FakeOutputPlayer(),
    )
    outcomes: list[VoiceCommandOutcome] = []
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_listening(async_capture=False)

    assert outcomes
    assert coordinator.state.headline == "Speech Offline"
    assert "Local controls still work" in coordinator.state.body


def test_cloud_voice_unavailable_uses_service_settings_snapshot() -> None:
    class _VoiceService:
        def __init__(self, settings: VoiceSettings) -> None:
            self.settings = settings

        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return False

        def tts_available(self) -> bool:
            return False

    settings_calls = 0
    service_settings: list[VoiceSettings] = []

    def settings_provider() -> VoiceSettings:
        nonlocal settings_calls
        settings_calls += 1
        return VoiceSettings(mode="cloud" if settings_calls == 1 else "local")

    def voice_service_factory(settings: VoiceSettings) -> _VoiceService:
        service_settings.append(settings)
        return _VoiceService(settings)

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=settings_provider,
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=voice_service_factory,
        output_player=_FakeOutputPlayer(),
    )

    coordinator.begin_listening(async_capture=False)

    assert settings_calls == 1
    assert service_settings == [VoiceSettings(mode="cloud")]
    assert coordinator.state.headline == "Speech Offline"
    assert "Cloud speech is unavailable" in coordinator.state.body


def test_runtime_cancel_reaches_in_flight_cloud_transcription(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"RIFF")
    transcribe_started = threading.Event()
    cancel_seen = threading.Event()
    outcomes: list[VoiceCommandOutcome] = []

    class _CancellableVoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return True

        def tts_available(self) -> bool:
            return False

        def capture_audio(self, _request) -> VoiceCaptureResult:
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(
            self,
            path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            assert path == audio_path
            assert cancel_event is not None
            transcribe_started.set()
            if cancel_event.wait(timeout=1.0):
                cancel_seen.set()
            return VoiceTranscript(text="play music", confidence=1.0, is_final=True)

        def speak(self, _text: str) -> bool:
            return False

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _CancellableVoiceService(),
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_listening(async_capture=True)
    assert transcribe_started.wait(timeout=1.0)
    coordinator.cancel()

    assert cancel_seen.wait(timeout=1.0)
    _wait_until(lambda: not audio_path.exists())
    assert outcomes == []


def test_voice_runtime_coordinator_ptt_no_audio_resolves_to_no_speech() -> None:
    context = AppContext()
    service = _NoAudioVoiceService()
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
    )

    coordinator.state.generation = 7
    coordinator.state.capture_in_flight = True
    coordinator.state.ptt_active = False
    coordinator._run_ptt_listening_cycle(
        service,
        7,
        None,
    )

    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "No Speech"
    assert context.voice.interaction.capture_in_flight is False


def test_voice_runtime_coordinator_releases_cached_service_when_settings_change(monkeypatch) -> None:
    """Replacing the cached service should drop backend-owned resources explicitly."""

    current_settings = VoiceSettings(vosk_model_keep_loaded=True)
    created_services: list[object] = []

    class _TrackingVoiceManager:
        def __init__(self, *, settings: VoiceSettings) -> None:
            self.settings = settings
            self.released = False
            created_services.append(self)

        def release_resources(self) -> None:
            self.released = True

    monkeypatch.setattr("yoyopod.integrations.voice.runtime.VoiceManager", _TrackingVoiceManager)
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: current_settings,
        ),
        command_executor=VoiceCommandExecutor(context=None),
    )

    first = coordinator._voice_service()
    current_settings = replace(current_settings, vosk_model_keep_loaded=False)
    second = coordinator._voice_service()

    assert len(created_services) == 2
    assert first is created_services[0]
    assert second is created_services[1]
    assert created_services[0].released is True
    assert created_services[1].released is False


def test_voice_settings_resolver_includes_cloud_worker_config() -> None:
    config_manager = _FakeConfigManager([])
    voice_cfg = config_manager.get_voice_settings()
    voice_cfg.assistant.mode = "cloud"
    voice_cfg.assistant.stt_backend = "cloud-worker"
    voice_cfg.assistant.tts_backend = "cloud-worker"
    voice_cfg.worker.enabled = True
    voice_cfg.worker.domain = "voice"
    voice_cfg.worker.provider = "openai"
    voice_cfg.worker.request_timeout_seconds = 8.5
    voice_cfg.worker.max_audio_seconds = 21.0
    voice_cfg.worker.stt_model = "test-transcribe"
    voice_cfg.worker.tts_model = "test-tts"
    voice_cfg.worker.tts_voice = "verse"
    voice_cfg.worker.tts_instructions = "Keep it tiny."
    voice_cfg.worker.local_feedback_enabled = False

    settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()

    assert settings.mode == "cloud"
    assert settings.stt_backend == "cloud-worker"
    assert settings.tts_backend == "cloud-worker"
    assert settings.cloud_worker_enabled is True
    assert settings.cloud_worker_domain == "voice"
    assert settings.cloud_worker_provider == "openai"
    assert settings.cloud_worker_request_timeout_seconds == 8.5
    assert settings.cloud_worker_max_audio_seconds == 21.0
    assert settings.cloud_worker_stt_model == "test-transcribe"
    assert settings.cloud_worker_tts_model == "test-tts"
    assert settings.cloud_worker_tts_voice == "verse"
    assert settings.cloud_worker_tts_instructions == "Keep it tiny."
    assert settings.local_feedback_enabled is False


def test_spoken_outcome_does_not_block_main_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    class _VoiceService:
        def speak(self, _text: str) -> bool:
            started.set()
            release.wait(timeout=2.0)
            return True

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _VoiceService(),
        output_player=_FakeOutputPlayer(),
    )

    started_at = time.monotonic()
    runtime._apply_outcome(VoiceCommandOutcome("Done", "Playing music", should_speak=True))
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert started.wait(timeout=1.0)
    release.set()


def test_spoken_outcome_failure_does_not_change_successful_command_outcome() -> None:
    class _VoiceService:
        def speak(self, _text: str) -> bool:
            return False

    runtime = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: _VoiceService(),
        output_player=_FakeOutputPlayer(),
    )

    runtime._apply_outcome(VoiceCommandOutcome("Done", "Playing music", should_speak=True))

    runtime._tts_queue.join()
    assert runtime.state.headline == "Done"
    assert runtime.state.body == "Playing music"


def test_voice_outcome_speaks_on_background_thread_and_returns_quickly() -> None:
    context = AppContext()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    thread_names: list[str] = []

    class _BlockingVoiceService:
        def speak(self, _text: str) -> bool:
            thread_names.append(threading.current_thread().name)
            started.set()
            release.wait(timeout=0.5)
            finished.set()
            return True

    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=VoiceCommandExecutor(context=context),
        voice_service_factory=lambda _settings: _BlockingVoiceService(),
        output_player=_FakeOutputPlayer(),
    )

    started_at = time.monotonic()
    coordinator._apply_outcome(VoiceCommandOutcome("Done", "Playing music", should_speak=True))
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert context.voice.last_spoken_text == "Playing music"
    assert started.wait(timeout=1.0)
    assert thread_names == ["VoiceRuntimeTTS"]
    release.set()
    assert finished.wait(timeout=1.0)


def test_voice_outcome_speech_is_serialized_without_overlap() -> None:
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    lock = threading.Lock()
    active_speakers = 0
    max_active_speakers = 0
    speak_calls: list[str] = []

    class _BlockingVoiceService:
        def speak(self, text: str) -> bool:
            nonlocal active_speakers, max_active_speakers
            with lock:
                active_speakers += 1
                max_active_speakers = max(max_active_speakers, active_speakers)
                speak_calls.append(text)
            try:
                if text == "First":
                    first_started.set()
                    first_release.wait(timeout=1.0)
                if text == "Second":
                    second_started.set()
                    second_finished.set()
                return True
            finally:
                with lock:
                    active_speakers -= 1

    service = _BlockingVoiceService()
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: service,
        output_player=_FakeOutputPlayer(),
    )

    coordinator._apply_outcome(VoiceCommandOutcome("One", "First", should_speak=True))
    assert first_started.wait(timeout=1.0)
    coordinator._apply_outcome(VoiceCommandOutcome("Two", "Second", should_speak=True))

    assert not second_started.wait(timeout=0.1)
    first_release.set()
    assert second_finished.wait(timeout=1.0)

    assert speak_calls == ["First", "Second"]
    assert max_active_speakers == 1
