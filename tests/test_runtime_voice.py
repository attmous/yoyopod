"""Direct tests for the shared runtime-owned voice orchestration seam."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

from yoyopod.app_context import AppContext
from yoyopod.runtime.voice import (
    VoiceCommandExecutor,
    VoiceCommandOutcome,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)
from yoyopod.voice import VoiceCaptureResult, VoiceSettings, VoiceTranscript


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
            )
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

    def transcribe(self, audio_path: Path) -> VoiceTranscript:
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
    assert context.talk_contact_name == "Mama"
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

    class _TrackingVoiceService:
        def __init__(self, *, settings: VoiceSettings) -> None:
            self.settings = settings
            self.released = False
            created_services.append(self)

        def release_resources(self) -> None:
            self.released = True

    monkeypatch.setattr("yoyopod.runtime.voice.VoiceService", _TrackingVoiceService)
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
