"""Direct tests for the shared voice coordination seam."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import yaml

from yoyopod.core import AppContext
from yoyopod.integrations.contacts.models import contacts_from_mapping
from yoyopod.integrations.voice import (
    AskConversationState,
    VoiceCommandExecutor,
    VoiceCommandOutcome,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
)
from yoyopod.integrations.voice import (
    VoiceCaptureResult,
    VoiceSettings,
    VoiceTranscript,
)

ASK_INSTRUCTIONS = (
    "You are YoYoPod's friendly Ask helper for a child using a small handheld audio device. "
    "Answer in simple language a child can understand. Keep answers to 1-3 short sentences "
    "unless the child asks for a story. Be warm, calm, and encouraging. Do not use scary "
    "detail. Do not ask for private information. For medical, legal, safety, emergency, or "
    "adult topics, give a brief safe answer and say to ask a grown-up. If you are unsure, "
    "say so simply. Do not claim to browse the internet or know live facts."
)
TTS_INSTRUCTIONS = (
    "Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. "
    "Avoid scary emphasis."
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
                sample_rate_hz=22050,
                record_seconds=6,
                tts_rate_wpm=180,
                tts_voice="en-us",
                activation_prefixes=["yoyo", "hey yoyo"],
                command_dictionary_path="data/voice/commands.yaml",
                command_routing=SimpleNamespace(
                    mode="command_first",
                    ask_fallback_enabled=True,
                    fallback_min_command_confidence=0.82,
                ),
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
                tts_voice="coral",
                tts_instructions=TTS_INSTRUCTIONS,
                ask_model="gpt-4.1-mini",
                ask_timeout_seconds=12.0,
                ask_max_history_turns=4,
                ask_max_response_chars=480,
                ask_instructions=ASK_INSTRUCTIONS,
                local_feedback_enabled=True,
            ),
        )

    def get_contacts(self) -> list[_FakeContact]:
        return list(self._contacts)

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[_FakeContact]:
        return [
            contact
            for contact in self._contacts
            if contact.preferred_call_target(gsm_enabled=gsm_enabled)[0]
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

    def speak(
        self,
        text: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        self.speak_calls.append(text)
        return True

    def release_resources(self) -> None:
        self.release_calls += 1


class _MemoryTraceStore:
    def __init__(self) -> None:
        self.entries = []

    def append(self, entry) -> None:
        self.entries.append(entry)


class _SequenceVoiceService(_FakeVoiceService):
    def __init__(self, transcripts: list[str]) -> None:
        super().__init__("")
        self._transcripts = transcripts

    def transcribe(
        self,
        audio_path: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        return VoiceTranscript(text=self._transcripts.pop(0), confidence=0.91)


class _NoAudioVoiceService(_FakeVoiceService):
    def __init__(self) -> None:
        super().__init__("")

    def capture_audio(self, request) -> VoiceCaptureResult:
        self.capture_calls += 1
        return VoiceCaptureResult(audio_path=None, recorded=False)


class _FakeOutputPlayer:
    def play_wav(self, path: Path, **kwargs) -> None:
        return None


class _FakeMusicBackend:
    def __init__(self, playback_state: str = "playing", *, connected: bool = True) -> None:
        self._playback_state = playback_state
        self.is_connected = connected
        self.pause_calls = 0
        self.play_calls = 0
        self.pause_result = True
        self.play_result = True

    def get_playback_state(self) -> str:
        return self._playback_state

    def pause(self) -> bool:
        self.pause_calls += 1
        if not self.pause_result:
            return False
        self._playback_state = "paused"
        return True

    def play(self) -> bool:
        self.play_calls += 1
        if not self.play_result:
            return False
        self._playback_state = "playing"
        return True


class _FakeAskClient:
    def __init__(self, answers: list[str] | None = None, *, available: bool = True) -> None:
        self.is_available = available
        self.answers = answers or ["answer"]
        self.ask_calls: list[dict[str, object]] = []

    def ask(
        self,
        *,
        question: str,
        history: list[VoiceWorkerAskTurn],
        model: str,
        instructions: str,
        max_output_chars: int,
        cancel_event: threading.Event | None = None,
        timeout_seconds: float | None = None,
    ) -> VoiceWorkerAskResult:
        self.ask_calls.append(
            {
                "question": question,
                "history": history,
                "model": model,
                "instructions": instructions,
                "max_output_chars": max_output_chars,
                "cancel_event": cancel_event,
                "timeout_seconds": timeout_seconds,
            }
        )
        return VoiceWorkerAskResult(answer=self.answers.pop(0), model=model)


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


def test_ask_conversation_keeps_bounded_history() -> None:
    state = AskConversationState(max_turns=2, max_text_chars=12)

    state.append(" first question ", " first answer ")
    state.append("Second\n\nQuestion with extra words", "Second   Answer   with   extra")
    state.append("Third Question", "Third Answer")

    assert state._turns == [
        ("Second Quest", "Second Answe"),
        ("Third Questi", "Third Answer"),
    ]
    assert state.history_for_worker() == [
        VoiceWorkerAskTurn(role="user", text="Second Quest"),
        VoiceWorkerAskTurn(role="assistant", text="Second Answe"),
        VoiceWorkerAskTurn(role="user", text="Third Questi"),
        VoiceWorkerAskTurn(role="assistant", text="Third Answer"),
    ]

    state.reset()

    assert state._turns == []
    assert state.history_for_worker() == []


def test_ask_conversation_clamps_non_positive_history_limits() -> None:
    state = AskConversationState(max_turns=0, max_text_chars=0)

    state.append("Alpha", "Bravo")
    state.append("Charlie", "Delta")

    assert state._turns == [("C", "D")]
    assert state.history_for_worker() == [
        VoiceWorkerAskTurn(role="user", text="C"),
        VoiceWorkerAskTurn(role="assistant", text="D"),
    ]

    negative_text_state = AskConversationState(max_text_chars=-2)

    negative_text_state.append("Echo", "Foxtrot")

    assert negative_text_state._turns == [("E", "F")]


def test_ask_conversation_detects_exit_phrases() -> None:
    state = AskConversationState()

    assert state.is_exit_request("  EXIT   ASK  ")
    assert state.is_exit_request("go back")
    assert state.is_exit_request("stop asking")
    assert state.is_exit_request("stop ask")
    assert state.is_exit_request("leave ask")
    assert state.is_exit_request("close ask")
    assert AskConversationState(max_text_chars=3).is_exit_request("go back")
    assert not state.is_exit_request("ask about space")
    assert not state.is_exit_request("please go back home")


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


def test_voice_command_executor_uses_contact_aliases() -> None:
    context = AppContext()
    voip_manager = _FakeVoipManager()
    contact = _FakeContact("Hagar", "sip:mama@example.com", notes="Mama")
    contact.aliases = ["banana phone"]
    executor = _build_executor(
        context=context,
        config_manager=_FakeConfigManager([contact]),
        voip_manager=voip_manager,
    )

    outcome = executor.execute("call banana phone")

    assert outcome == VoiceCommandOutcome(
        "Calling",
        "Calling Mama.",
        auto_return=False,
    )
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]


def test_contacts_from_mapping_ignores_missing_or_invalid_aliases() -> None:
    contacts, _speed_dial = contacts_from_mapping(
        {
            "contacts": [
                {"name": "Absent", "sip_address": "sip:absent@example.com"},
                {
                    "name": "Empty",
                    "sip_address": "sip:empty@example.com",
                    "aliases": [],
                },
                {
                    "name": "Null",
                    "sip_address": "sip:null@example.com",
                    "aliases": None,
                },
                {
                    "name": "Scalar",
                    "sip_address": "sip:scalar@example.com",
                    "aliases": "banana phone",
                },
                {
                    "name": "Mapping",
                    "sip_address": "sip:mapping@example.com",
                    "aliases": {"short": "map"},
                },
            ]
        }
    )

    assert [contact.aliases for contact in contacts] == [[], [], [], [], []]


def test_contacts_from_mapping_strips_blank_aliases() -> None:
    contacts, _speed_dial = contacts_from_mapping(
        {
            "contacts": [
                {
                    "name": "Hagar",
                    "sip_address": "sip:mama@example.com",
                    "aliases": [" banana phone ", "", "   ", "hags"],
                },
            ]
        }
    )

    assert contacts[0].aliases == ["banana phone", "hags"]


def test_voice_command_executor_handles_local_device_actions() -> None:
    context = AppContext()
    context.settings["max_volume"] = 55
    voip_manager = _FakeVoipManager()
    executor = _build_executor(context=context, voip_manager=voip_manager)

    mute_outcome = executor.execute("mute mic")
    volume_outcome = executor.execute("volume up")

    assert mute_outcome.body == "Voice commands mic is muted."
    assert context.voice.mic_muted is True
    assert voip_manager.mute_calls == 1
    assert volume_outcome.body == "Volume is 10 out of 10."
    assert context.voice.output_volume == 55


def test_voice_command_executor_confirms_likely_call_before_dialing() -> None:
    context = AppContext()
    voip_manager = _FakeVoipManager()
    executor = _build_executor(
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    prompt = executor.execute("mama please call")

    assert prompt == VoiceCommandOutcome(
        "Confirm Call",
        "Did you want to call Mama? Say yes or no.",
        auto_return=False,
    )
    assert voip_manager.make_calls == []

    outcome = executor.execute("yes")

    assert outcome == VoiceCommandOutcome(
        "Calling",
        "Calling Mama.",
        auto_return=False,
    )
    assert voip_manager.make_calls == [("sip:mama@example.com", "Mama")]


def test_voice_command_executor_cancels_pending_call_confirmation() -> None:
    context = AppContext()
    voip_manager = _FakeVoipManager()
    executor = _build_executor(
        context=context,
        config_manager=_FakeConfigManager(
            [_FakeContact("Hagar", "sip:mama@example.com", notes="Mama")]
        ),
        voip_manager=voip_manager,
    )

    prompt = executor.execute("mama call")
    outcome = executor.execute("no")

    assert prompt.headline == "Confirm Call"
    assert outcome == VoiceCommandOutcome("Cancelled", "Okay, I will not call Mama.")
    assert voip_manager.make_calls == []


def test_voice_command_executor_respects_screen_read_toggle_with_provider() -> None:
    context = AppContext()

    provider_calls = 0

    def screen_summary_provider() -> str:
        nonlocal provider_calls
        provider_calls += 1
        return "Mode-aware Ask summary."

    executor = VoiceCommandExecutor(
        context=context,
        screen_summary_provider=screen_summary_provider,
    )

    disabled_outcome = executor.execute("read screen")

    assert provider_calls == 0
    assert disabled_outcome == VoiceCommandOutcome(
        "Screen Read",
        "Screen read is off. Turn it on in Setup to auto-read screens.",
    )

    context.configure_voice(screen_read_enabled=True)

    enabled_outcome = executor.execute("read screen")

    assert provider_calls == 1
    assert enabled_outcome == VoiceCommandOutcome(
        "Screen Read",
        "Mode-aware Ask summary.",
    )


def test_voice_command_executor_volume_fallback_uses_app_context_audio_controller() -> None:
    context = AppContext()
    context.settings["max_volume"] = 55
    context.audio_volume_controller = _FakeAudioVolumeController(context)
    executor = VoiceCommandExecutor(
        context=context,
        screen_summary_provider=lambda: "screen",
    )

    outcome = executor.execute("volume up")

    assert outcome.body == "Volume is 10 out of 10."
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
    assert service.speak_calls == []
    assert outcomes == [
        VoiceCommandOutcome(
            "Playing",
            "Starting local music.",
            should_speak=False,
            route_name="shuffle_started",
        )
    ]
    assert context.voice.last_transcript == "play music"
    assert context.voice.last_spoken_text == ""
    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "Playing"


def test_begin_ask_runs_command_before_ask_fallback() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo play music")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Playing",
        "Starting local music.",
        should_speak=False,
        route_name="shuffle_started",
    )
    assert context.voice.last_transcript == "play music"


def test_begin_ask_runs_local_command_without_ask_client() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo play music")
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=None,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert service.capture_calls == 1
    assert outcomes[-1] == VoiceCommandOutcome(
        "Playing",
        "Starting local music.",
        should_speak=False,
        route_name="shuffle_started",
    )
    assert context.voice.last_transcript == "play music"


def test_begin_ask_runs_local_command_when_ai_disabled() -> None:
    context = AppContext()
    context.configure_voice(ai_requests_enabled=False)
    service = _FakeVoiceService("hey yoyo play music")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                ai_requests_enabled=False,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert service.capture_calls == 1
    assert outcomes[-1] == VoiceCommandOutcome(
        "Playing",
        "Starting local music.",
        should_speak=False,
        route_name="shuffle_started",
    )
    assert context.voice.last_transcript == "play music"


def test_begin_ask_falls_back_to_ask_for_non_command() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo why is the sky blue")
    ask_client = _FakeAskClient(["Because sunlight scatters in the air."])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls[0]["question"] == "why is the sky blue"
    assert outcomes[-1] == VoiceCommandOutcome(
        "Answer",
        "Because sunlight scatters in the air.",
        auto_return=False,
    )


def test_begin_ask_traces_command_turn() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo play music")
    trace_store = _MemoryTraceStore()
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                voice_trace_enabled=True,
                voice_trace_include_transcripts=True,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=_FakeAskClient(["unused"]),
        trace_store_factory=lambda settings: trace_store,
    )

    coordinator.begin_ask(async_capture=False)

    assert len(trace_store.entries) == 1
    payload = trace_store.entries[0].to_json_dict()
    assert payload["source"] == "ask_screen"
    assert payload["mode"] == "ask"
    assert payload["route_kind"] == "command"
    assert payload["transcript_normalized"] == "play music"
    assert payload["command_intent"] == "play_music"
    assert payload["outcome"] == "Playing"


def test_begin_ask_traces_ask_fallback_with_capped_body_preview() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo why is the sky blue")
    trace_store = _MemoryTraceStore()
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                voice_trace_enabled=True,
                voice_trace_include_transcripts=True,
                voice_trace_body_preview_chars=12,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=_FakeAskClient(["Because sunlight scatters in the air."]),
        trace_store_factory=lambda settings: trace_store,
    )

    coordinator.begin_ask(async_capture=False)
    coordinator._tts_queue.join()

    assert len(trace_store.entries) == 1
    payload = trace_store.entries[0].to_json_dict()
    assert payload["route_kind"] == "ask"
    assert payload["transcript_normalized"] == "why is the sky blue"
    assert payload["assistant_body_preview"] == "Because s..."


def test_begin_ask_trace_completes_when_answer_speech_is_cancelled_by_new_capture() -> None:
    context = AppContext()
    speak_started = threading.Event()
    service = _SequenceVoiceService(
        [
            "hey yoyo why is the sky blue",
            "play music",
        ]
    )
    trace_store = _MemoryTraceStore()

    def speak(
        text: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        service.speak_calls.append(text)
        speak_started.set()
        assert cancel_event is not None
        cancel_event.wait(timeout=1.0)
        return False

    service.speak = speak
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                voice_trace_enabled=True,
                voice_trace_include_transcripts=True,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=_FakeAskClient(["Because sunlight scatters in the air."]),
        trace_store_factory=lambda settings: trace_store,
    )

    coordinator.begin_ask(async_capture=False)
    assert speak_started.wait(timeout=1.0)

    coordinator.begin_listening(async_capture=False)
    coordinator._tts_queue.join()

    payloads = [entry.to_json_dict() for entry in trace_store.entries]
    assert [payload["mode"] for payload in payloads] == ["ask", "command"]
    assert payloads[0]["route_kind"] == "error"
    assert payloads[0]["outcome"] == "cancelled"
    assert payloads[0]["assistant_body_preview"] == "Because sunlight scatters in the air."
    assert payloads[1]["route_kind"] == "command"
    assert payloads[1]["outcome"] == "Playing"
    assert coordinator._active_traces == {}


def test_begin_listening_traces_stt_failure() -> None:
    context = AppContext()
    trace_store = _MemoryTraceStore()

    class _SttFailureVoiceService(_FakeVoiceService):
        def transcribe(
            self,
            audio_path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            raise RuntimeError("stt boom")

    service = _SttFailureVoiceService("unused")
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                voice_trace_enabled=True,
                voice_trace_include_transcripts=True,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        trace_store_factory=lambda settings: trace_store,
    )

    coordinator.begin_listening(async_capture=False)

    assert len(trace_store.entries) == 1
    payload = trace_store.entries[0].to_json_dict()
    assert payload["route_kind"] == "error"
    assert payload["outcome"] == "Mic Unavailable"
    assert payload["error"]["stage"] == "stt"
    assert payload["error"]["type"] == "RuntimeError"


def test_begin_ask_trace_records_music_focus_after_resume() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo play music")
    music_backend = _FakeMusicBackend("playing")
    trace_store = _MemoryTraceStore()
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                voice_trace_enabled=True,
                voice_trace_include_transcripts=True,
            ),
        ),
        command_executor=_build_executor(context=context, play_music_action=lambda: True),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=_FakeAskClient(["unused"]),
        music_backend=music_backend,
        trace_store_factory=lambda settings: trace_store,
    )

    coordinator.begin_ask(async_capture=False)

    assert len(trace_store.entries) == 1
    payload = trace_store.entries[0].to_json_dict()
    assert payload["music_before"]["playback_state"] == "playing"
    assert payload["audio_focus_before"]["music_paused_for_voice"] is False
    assert payload["music_after"]["playback_state"] == "playing"
    assert payload["audio_focus_after"]["music_paused_for_voice"] is False


def test_begin_ask_pauses_music_and_resumes_after_answer_speech() -> None:
    """Ask should hold music focus until the spoken answer has finished."""

    context = AppContext()
    speak_started = threading.Event()
    release_speech = threading.Event()

    class _BlockingSpeechVoiceService(_FakeVoiceService):
        def speak(
            self,
            text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            self.speak_calls.append(text)
            speak_started.set()
            release_speech.wait(timeout=1.0)
            return not (cancel_event is not None and cancel_event.is_set())

    service = _BlockingSpeechVoiceService("hey yoyo why is the sky blue")
    ask_client = _FakeAskClient(["Because sunlight scatters in the air."])
    music_backend = _FakeMusicBackend("playing")
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
        music_backend=music_backend,
    )

    coordinator.begin_ask(async_capture=False)

    assert music_backend.pause_calls == 1
    assert music_backend.get_playback_state() == "paused"
    assert speak_started.wait(timeout=1.0)
    assert music_backend.play_calls == 0

    release_speech.set()
    coordinator._tts_queue.join()

    assert service.speak_calls == ["Because sunlight scatters in the air."]
    assert music_backend.play_calls == 1
    assert music_backend.get_playback_state() == "playing"


def test_begin_ptt_capture_pauses_music_and_resumes_after_command_result(
    tmp_path: Path,
) -> None:
    """Hold-to-Ask should pause active music for the PTT capture window."""

    audio_path = tmp_path / "ptt.wav"
    audio_path.write_bytes(b"RIFF")
    capture_started = threading.Event()
    music_backend = _FakeMusicBackend("playing")
    outcomes: list[VoiceCommandOutcome] = []

    class _PTTVoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return True

        def tts_available(self) -> bool:
            return False

        def capture_audio(self, request) -> VoiceCaptureResult:
            capture_started.set()
            assert request.cancel_event is not None
            assert request.cancel_event.wait(timeout=1.0)
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(
            self,
            path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            assert path == audio_path
            del cancel_event
            return VoiceTranscript(text="volume up", confidence=1.0, is_final=True)

        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
            return False

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(
            context=None,
            volume_up_action=lambda _step: 60,
        ),
        voice_service_factory=lambda _settings: _PTTVoiceService(),
        output_player=_FakeOutputPlayer(),
        music_backend=music_backend,
    )
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_ptt_capture()

    assert capture_started.wait(timeout=1.0)
    assert music_backend.pause_calls == 1
    assert music_backend.get_playback_state() == "paused"

    coordinator.finish_ptt_capture()

    _wait_until(lambda: music_backend.play_calls == 1)
    assert outcomes[-1].headline == "Volume"
    assert music_backend.get_playback_state() == "playing"
    assert not audio_path.exists()


def test_calling_outcome_hands_paused_music_to_call_policy() -> None:
    """Call commands should not resume music before the call runtime owns audio."""

    context = AppContext()
    service = _FakeVoiceService("call mama")
    music_backend = _FakeMusicBackend("playing")
    handoff_calls = 0

    class _CallingExecutor:
        def execute(self, transcript: str) -> VoiceCommandOutcome:
            assert transcript == "call mama"
            return VoiceCommandOutcome(
                "Calling",
                "Calling Mama.",
                should_speak=False,
                auto_return=False,
            )

    def handoff_to_call() -> bool:
        nonlocal handoff_calls
        handoff_calls += 1
        return True

    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=_CallingExecutor(),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        music_backend=music_backend,
        call_music_handoff=handoff_to_call,
    )

    coordinator.begin_listening(async_capture=False)

    assert music_backend.pause_calls == 1
    assert music_backend.play_calls == 0
    assert music_backend.get_playback_state() == "paused"
    assert handoff_calls == 1


def test_begin_ask_reports_offline_after_routing_non_command() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo why is the sky blue")
    ask_client = _FakeAskClient(["unused"], available=False)
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert service.capture_calls == 1
    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Ask Offline",
        "I cannot reach Ask right now. I can still help with music, calls, and volume.",
        should_speak=False,
        auto_return=False,
    )


def test_begin_ask_executes_mutable_alias_match(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "volume_up": {
                        "aliases": ["boost sound"],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    context = AppContext()
    context.settings["max_volume"] = 55
    service = _FakeVoiceService("hey yoyo boost sound")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                command_dictionary_path=str(commands_file),
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome("Volume", "Volume is 10 out of 10.")
    assert context.voice.last_transcript == "boost sound"
    assert context.voice.output_volume == 55


def test_begin_ask_routes_safe_dictionary_action(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "actions": {
                    "open_talk": {
                        "aliases": ["open talk"],
                        "route": "open_talk",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    context = AppContext()
    service = _FakeVoiceService("hey yoyo open talk")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=True,
                command_dictionary_path=str(commands_file),
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Command",
        "",
        should_speak=False,
        route_name="open_talk",
        auto_return=False,
    )


def test_begin_ask_returns_local_help_when_fallback_disabled() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo tell me a story")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=False,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Try Again",
        "Try saying call mom, play music, or volume up.",
        should_speak=False,
        auto_return=False,
    )


def test_begin_ask_exit_phrase_works_when_fallback_disabled() -> None:
    context = AppContext()
    service = _FakeVoiceService("hey yoyo go back")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                activation_prefixes=("hey yoyo", "yoyo"),
                ask_fallback_enabled=False,
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Ask",
        "Going back.",
        should_speak=False,
        route_name="back",
        auto_return=False,
    )


def test_entry_cycle_uses_ask_mode_for_non_quick_and_ptt_for_quick() -> None:
    context = AppContext()
    ask_service = _FakeVoiceService("what is space")
    ask_client = _FakeAskClient(["Space is everything around Earth."])
    ask_outcomes: list[VoiceCommandOutcome] = []
    ask_coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: ask_service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    ask_coordinator.bind(state_listener=lambda state: None, outcome_listener=ask_outcomes.append)

    ask_coordinator.begin_entry_cycle(quick_command=False, async_capture=False)

    assert ask_service.capture_calls == 1
    assert ask_client.ask_calls[0]["question"] == "what is space"
    assert ask_outcomes[-1] == VoiceCommandOutcome(
        "Answer",
        "Space is everything around Earth.",
        auto_return=False,
    )

    ptt_service = _NoAudioVoiceService()
    ptt_ask_client = _FakeAskClient(["unused"])
    ptt_coordinator = VoiceRuntimeCoordinator(
        context=AppContext(),
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda settings: ptt_service,
        output_player=_FakeOutputPlayer(),
        ask_client=ptt_ask_client,
    )

    ptt_coordinator.begin_entry_cycle(quick_command=True, async_capture=False)

    _wait_until(lambda: ptt_service.capture_calls == 1)
    assert ptt_ask_client.ask_calls == []


def test_ask_success_appends_bounded_history_and_speaks_answer() -> None:
    context = AppContext()
    service = _FakeVoiceService("tell me about mars")
    ask_client = _FakeAskClient(["Mars is red and dusty."])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(
                mode="cloud",
                cloud_worker_ask_model="test-ask",
                cloud_worker_ask_max_history_turns=1,
                cloud_worker_ask_max_response_chars=12,
                cloud_worker_ask_instructions="Answer safely.",
            ),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)

    coordinator.begin_ask(async_capture=False)

    _wait_until(lambda: service.speak_calls == ["Mars is red and dusty."])
    assert ask_client.ask_calls == [
        {
            "question": "tell me about mars",
            "history": [],
            "model": "test-ask",
            "instructions": "Answer safely.",
            "max_output_chars": 12,
            "cancel_event": ask_client.ask_calls[0]["cancel_event"],
            "timeout_seconds": 12.0,
        }
    ]
    assert coordinator._ask_conversation._turns == [("tell me abou", "Mars is red ")]
    assert outcomes[-1] == VoiceCommandOutcome(
        "Answer",
        "Mars is red and dusty.",
        auto_return=False,
    )
    assert context.voice.last_spoken_text == "Mars is red and dusty."
    assert context.voice.interaction.headline == "Answer"


def test_second_ask_turn_sends_previous_user_and_assistant_history() -> None:
    context = AppContext()
    service = _SequenceVoiceService(["what is mars", "how far away is it"])
    ask_client = _FakeAskClient(["Mars is a planet.", "It is very far away."])
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )

    coordinator.begin_ask(async_capture=False)
    coordinator.begin_ask(async_capture=False)

    assert ask_client.ask_calls[0]["history"] == []
    assert ask_client.ask_calls[1]["question"] == "how far away is it"
    assert ask_client.ask_calls[1]["history"] == [
        VoiceWorkerAskTurn(role="user", text="what is mars"),
        VoiceWorkerAskTurn(role="assistant", text="Mars is a planet."),
    ]


def test_async_ask_thinking_transition_uses_dispatcher() -> None:
    context = AppContext()
    service = _FakeVoiceService("what is mars")
    ask_started = threading.Event()
    release_ask = threading.Event()
    dispatched_callbacks: list[Callable[[], None]] = []

    class _BlockingAskClient(_FakeAskClient):
        def ask(
            self,
            *,
            question: str,
            history: list[VoiceWorkerAskTurn],
            model: str,
            instructions: str,
            max_output_chars: int,
            cancel_event: threading.Event | None = None,
            timeout_seconds: float | None = None,
        ) -> VoiceWorkerAskResult:
            ask_started.set()
            release_ask.wait(timeout=1.0)
            return super().ask(
                question=question,
                history=history,
                model=model,
                instructions=instructions,
                max_output_chars=max_output_chars,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )

    ask_client = _BlockingAskClient(["Mars is a planet."])
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(
        state_listener=lambda state: None,
        outcome_listener=lambda outcome: None,
        dispatcher=dispatched_callbacks.append,
    )

    coordinator.begin_ask(async_capture=True)

    assert ask_started.wait(timeout=1.0)
    assert context.voice.interaction.headline == "Listening"
    assert coordinator.state.headline == "Listening"
    assert dispatched_callbacks

    release_ask.set()
    coordinator.cancel()


def test_cancelled_ask_answer_is_not_spoken_or_recorded() -> None:
    context = AppContext()
    first_started = threading.Event()
    first_release = threading.Event()
    speak_calls: list[str] = []

    class _BlockingVoiceService:
        def speak(
            self,
            text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
            speak_calls.append(text)
            if text == "Blocking command":
                first_started.set()
                first_release.wait(timeout=1.0)
            return True

    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=VoiceCommandExecutor(context=context),
        voice_service_factory=lambda _settings: _BlockingVoiceService(),
        output_player=_FakeOutputPlayer(),
    )

    coordinator._apply_outcome(
        VoiceCommandOutcome("Command", "Blocking command", should_speak=True)
    )
    assert first_started.wait(timeout=1.0)
    ask_generation = coordinator.state.generation
    coordinator._dispatch_ask_outcome(
        VoiceCommandOutcome("Answer", "Stale answer", should_speak=True, auto_return=False),
        generation=ask_generation,
    )

    coordinator.cancel()
    first_release.set()
    coordinator._tts_queue.join()

    assert speak_calls == ["Blocking command"]
    assert context.voice.last_spoken_text == "Blocking command"


def test_cancel_stops_active_ask_tts() -> None:
    context = AppContext()
    speak_started = threading.Event()
    cancel_seen = threading.Event()
    speak_finished = threading.Event()
    cancel_events: list[threading.Event | None] = []

    class _CancellableVoiceService:
        def speak(
            self,
            text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            cancel_events.append(cancel_event)
            speak_started.set()
            assert text == "Long answer"
            assert cancel_event is not None
            if cancel_event.wait(timeout=1.0):
                cancel_seen.set()
            speak_finished.set()
            return not cancel_event.is_set()

    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=VoiceCommandExecutor(context=context),
        voice_service_factory=lambda _settings: _CancellableVoiceService(),
        output_player=_FakeOutputPlayer(),
    )
    generation = coordinator._next_generation()
    coordinator._dispatch_ask_outcome(
        VoiceCommandOutcome("Answer", "Long answer", should_speak=True, auto_return=False),
        generation=generation,
    )
    assert speak_started.wait(timeout=1.0)

    coordinator.cancel()

    assert cancel_seen.wait(timeout=1.0)
    assert speak_finished.wait(timeout=1.0)
    coordinator._tts_queue.join()
    assert len(cancel_events) == 1
    assert context.voice.last_spoken_text == ""


def test_ask_exit_phrase_routes_back_and_stale_outcomes_do_not_speak() -> None:
    context = AppContext()
    service = _FakeVoiceService("go back")
    ask_client = _FakeAskClient(["unused"])
    outcomes: list[VoiceCommandOutcome] = []
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )
    coordinator.bind(state_listener=lambda state: None, outcome_listener=outcomes.append)
    coordinator._ask_conversation.append("earlier question", "earlier answer")

    coordinator.reset_to_idle()
    assert coordinator._ask_conversation.history_for_worker() == [
        VoiceWorkerAskTurn(role="user", text="earlier question"),
        VoiceWorkerAskTurn(role="assistant", text="earlier answer"),
    ]

    coordinator.begin_ask(async_capture=False)
    stale_generation = coordinator.state.generation - 1
    coordinator._dispatch_ask_outcome(
        VoiceCommandOutcome("Answer", "stale answer", should_speak=True, auto_return=False),
        generation=stale_generation,
    )

    assert ask_client.ask_calls == []
    assert outcomes[-1] == VoiceCommandOutcome(
        "Ask",
        "Going back.",
        should_speak=False,
        route_name="back",
        auto_return=False,
    )
    assert service.speak_calls == []
    assert coordinator._ask_conversation.history_for_worker() == [
        VoiceWorkerAskTurn(role="user", text="earlier question"),
        VoiceWorkerAskTurn(role="assistant", text="earlier answer"),
    ]


def test_unavailable_ask_client_reports_offline_after_capture() -> None:
    context = AppContext()
    service = _FakeVoiceService("what is mars")
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=_FakeAskClient(available=False),
    )

    coordinator.begin_ask(async_capture=False)

    assert service.capture_calls == 1
    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "Ask Offline"
    assert context.voice.interaction.body == (
        "I cannot reach Ask right now. I can still help with music, calls, and volume."
    )


def test_ai_disabled_reports_ask_off_after_capture_for_non_command() -> None:
    context = AppContext()
    context.configure_voice(ai_requests_enabled=False)
    service = _FakeVoiceService("what is mars")
    ask_client = _FakeAskClient(["unused"])
    coordinator = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(context=context),
        command_executor=_build_executor(context=context),
        voice_service_factory=lambda settings: service,
        output_player=_FakeOutputPlayer(),
        ask_client=ask_client,
    )

    coordinator.begin_ask(async_capture=False)

    assert service.capture_calls == 1
    assert ask_client.ask_calls == []
    assert context.voice.interaction.phase == "reply"
    assert context.voice.interaction.headline == "Ask Off"
    assert context.voice.interaction.body == "Turn Ask on in Setup first."


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

        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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


def test_local_feedback_disabled_skips_attention_tone() -> None:
    play_calls: list[Path] = []

    class _RecordingOutputPlayer:
        def play_wav(self, path: Path, **kwargs) -> None:
            play_calls.append(path)

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(local_feedback_enabled=False),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        output_player=_RecordingOutputPlayer(),
    )

    coordinator._play_attention_tone()

    assert play_calls == []


def test_local_feedback_skips_busy_playback_lock() -> None:
    play_calls: list[dict[str, object]] = []

    class _RecordingOutputPlayer:
        def play_wav(self, path: Path, **kwargs) -> None:
            play_calls.append({"path": path, **kwargs})

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(local_feedback_enabled=True),
        ),
        command_executor=VoiceCommandExecutor(context=None),
        output_player=_RecordingOutputPlayer(),
    )

    coordinator._play_attention_tone()

    assert play_calls
    assert play_calls[0]["block_if_busy"] is False


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

        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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


def test_ptt_release_transcribes_with_fresh_cancel_event(tmp_path: Path) -> None:
    audio_path = tmp_path / "ptt.wav"
    audio_path.write_bytes(b"RIFF")
    capture_started = threading.Event()
    release_seen = threading.Event()
    transcribe_cancel_events: list[threading.Event] = []
    transcripts: list[str] = []
    outcomes: list[VoiceCommandOutcome] = []

    class _PTTReleaseVoiceService:
        def capture_available(self) -> bool:
            return True

        def stt_available(self) -> bool:
            return True

        def tts_available(self) -> bool:
            return False

        def capture_audio(self, request) -> VoiceCaptureResult:
            capture_started.set()
            assert request.cancel_event is not None
            assert request.cancel_event.wait(timeout=1.0)
            release_seen.set()
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(
            self,
            path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            assert path == audio_path
            assert cancel_event is not None
            transcribe_cancel_events.append(cancel_event)
            return VoiceTranscript(text="play music", confidence=1.0, is_final=True)

        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
            return False

    class _CommandExecutor:
        def execute(self, transcript: str) -> VoiceCommandOutcome:
            transcripts.append(transcript)
            return VoiceCommandOutcome("Done", transcript, should_speak=False)

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: VoiceSettings(mode="cloud"),
        ),
        command_executor=_CommandExecutor(),
        voice_service_factory=lambda _settings: _PTTReleaseVoiceService(),
        output_player=_FakeOutputPlayer(),
    )
    coordinator.bind(
        state_listener=None,
        outcome_listener=outcomes.append,
        dispatcher=lambda callback: callback(),
    )

    coordinator.begin_ptt_capture()
    assert capture_started.wait(timeout=1.0)
    coordinator.finish_ptt_capture()

    _wait_until(lambda: outcomes)
    assert release_seen.is_set()
    assert transcripts == ["play music"]
    assert len(transcribe_cancel_events) == 1
    assert not transcribe_cancel_events[0].is_set()
    assert outcomes[-1] == VoiceCommandOutcome("Done", "play music", should_speak=False)
    assert not audio_path.exists()


def test_ptt_release_skips_transcription_when_active_cancel_event_changed(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "ptt-race.wav"
    audio_path.write_bytes(b"RIFF")
    transcribe_calls = 0

    class _PTTRaceVoiceService:
        def capture_audio(self, _request) -> VoiceCaptureResult:
            return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        def transcribe(
            self,
            path: Path,
            *,
            cancel_event: threading.Event | None = None,
        ) -> VoiceTranscript:
            nonlocal transcribe_calls
            transcribe_calls += 1
            return VoiceTranscript(text="play music", confidence=1.0, is_final=True)

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        output_player=_FakeOutputPlayer(),
    )
    release_event = threading.Event()
    coordinator.state.generation = 7
    coordinator.state.ptt_active = False
    coordinator._active_capture_cancel = threading.Event()

    coordinator._run_ptt_listening_cycle(
        _PTTRaceVoiceService(),
        7,
        release_event,
    )

    assert transcribe_calls == 0
    assert not audio_path.exists()


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


def test_voice_runtime_coordinator_releases_cached_service_when_settings_change(
    monkeypatch,
) -> None:
    """Replacing the cached service should drop backend-owned resources explicitly."""

    current_settings = VoiceSettings(output_volume=50)
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
    current_settings = replace(current_settings, output_volume=51)
    second = coordinator._voice_service()

    assert len(created_services) == 2
    assert first is created_services[0]
    assert second is created_services[1]
    assert created_services[0].released is True
    assert created_services[1].released is False


def test_voice_runtime_coordinator_caches_factory_service_until_settings_change() -> None:
    current_settings = VoiceSettings(tts_voice="en")
    created_services: list[_FakeVoiceService] = []

    def factory(settings: VoiceSettings) -> _FakeVoiceService:
        service = _FakeVoiceService("")
        service.settings = settings
        created_services.append(service)
        return service

    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(
            context=None,
            settings_provider=lambda: current_settings,
        ),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=factory,
    )

    first = coordinator._voice_service()
    second = coordinator._voice_service()
    current_settings = replace(current_settings, tts_voice="en-us")
    third = coordinator._voice_service()

    assert first is second
    assert third is not first
    assert len(created_services) == 2
    assert created_services[0].release_calls == 1
    assert created_services[1].release_calls == 0


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
    voice_cfg.worker.ask_model = "test-ask"
    voice_cfg.worker.ask_timeout_seconds = 6.5
    voice_cfg.worker.ask_max_history_turns = 7
    voice_cfg.worker.ask_max_response_chars = 222
    voice_cfg.worker.ask_instructions = "Answer safely."
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
    assert settings.cloud_worker_ask_model == "test-ask"
    assert settings.cloud_worker_ask_timeout_seconds == 6.5
    assert settings.cloud_worker_ask_max_history_turns == 7
    assert settings.cloud_worker_ask_max_response_chars == 222
    assert settings.cloud_worker_ask_instructions == "Answer safely."
    assert settings.local_feedback_enabled is False


def test_voice_settings_resolver_includes_command_routing_config() -> None:
    config_manager = _FakeConfigManager([])
    voice_cfg = config_manager.get_voice_settings()
    voice_cfg.assistant.activation_prefixes = ["yoyo", "hey yoyo"]
    voice_cfg.assistant.command_dictionary_path = "data/voice/commands.yaml"
    voice_cfg.assistant.command_routing = SimpleNamespace(
        mode="command_first",
        ask_fallback_enabled=False,
        fallback_min_command_confidence=0.91,
    )

    settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()

    assert settings.activation_prefixes == ("yoyo", "hey yoyo")
    assert settings.command_dictionary_path == "data/voice/commands.yaml"
    assert settings.command_routing_mode == "command_first"
    assert settings.ask_fallback_enabled is False
    assert settings.fallback_min_command_confidence == 0.91


def test_voice_settings_resolver_includes_trace_config() -> None:
    config_manager = _FakeConfigManager([])
    voice_cfg = config_manager.get_voice_settings()
    voice_cfg.trace = SimpleNamespace(
        enabled=False,
        path="logs/voice/test-turns.jsonl",
        max_turns=123,
        include_transcripts=False,
        body_preview_chars=44,
    )

    settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()

    assert settings.voice_trace_enabled is False
    assert settings.voice_trace_path == "logs/voice/test-turns.jsonl"
    assert settings.voice_trace_max_turns == 123
    assert settings.voice_trace_include_transcripts is False
    assert settings.voice_trace_body_preview_chars == 44


def test_voice_settings_resolver_falls_back_for_empty_routing_config() -> None:
    default_settings = VoiceSettings()
    config_manager = _FakeConfigManager([])
    voice_cfg = config_manager.get_voice_settings()

    voice_cfg.assistant.activation_prefixes = None
    voice_cfg.assistant.command_routing = None

    null_settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()

    assert null_settings.activation_prefixes == default_settings.activation_prefixes
    assert null_settings.command_routing_mode == default_settings.command_routing_mode
    assert null_settings.ask_fallback_enabled == default_settings.ask_fallback_enabled
    assert (
        null_settings.fallback_min_command_confidence
        == default_settings.fallback_min_command_confidence
    )

    voice_cfg.assistant.activation_prefixes = []

    empty_settings = VoiceSettingsResolver(
        context=None,
        config_manager=config_manager,
    ).defaults()

    assert empty_settings.activation_prefixes == default_settings.activation_prefixes


def test_spoken_outcome_does_not_block_main_thread() -> None:
    started = threading.Event()
    release = threading.Event()

    class _VoiceService:
        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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


def test_begin_listening_cancels_active_tts_before_capture() -> None:
    speak_started = threading.Event()
    tts_cancel_seen = threading.Event()
    capture_started = threading.Event()

    class _RaceVoiceService(_NoAudioVoiceService):
        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            assert cancel_event is not None
            speak_started.set()
            if cancel_event.wait(timeout=1.0):
                tts_cancel_seen.set()
            return False

        def capture_audio(self, request) -> VoiceCaptureResult:
            assert tts_cancel_seen.is_set()
            capture_started.set()
            return super().capture_audio(request)

    service = _RaceVoiceService()
    coordinator = VoiceRuntimeCoordinator(
        context=None,
        settings_resolver=VoiceSettingsResolver(context=None),
        command_executor=VoiceCommandExecutor(context=None),
        voice_service_factory=lambda _settings: service,
        output_player=_FakeOutputPlayer(),
    )

    coordinator._apply_outcome(VoiceCommandOutcome("Done", "Long reply", should_speak=True))
    assert speak_started.wait(timeout=1.0)

    coordinator.begin_listening(async_capture=True)

    assert tts_cancel_seen.wait(timeout=1.0)
    assert capture_started.wait(timeout=1.0)
    coordinator._tts_queue.join()


def test_spoken_outcome_failure_does_not_change_successful_command_outcome() -> None:
    class _VoiceService:
        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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
        def speak(
            self,
            _text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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
        def speak(
            self,
            text: str,
            *,
            cancel_event: threading.Event | None = None,
        ) -> bool:
            del cancel_event
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
