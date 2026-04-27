"""Voice session coordination for local Ask interactions."""

from __future__ import annotations

import math
import threading
import time
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Queue
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Callable, Protocol

from loguru import logger

from yoyopod.backends.voice import AlsaOutputPlayer
from yoyopod.core import VoiceInteractionState
from yoyopod.integrations.voice import (
    AskConversationState,
    VoiceCaptureRequest,
    VoiceManager,
    VoiceSettings,
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
)

from yoyopod.integrations.voice.executor import VoiceCommandExecutor
from yoyopod.integrations.voice.settings import VoiceCommandOutcome, VoiceSettingsResolver

if TYPE_CHECKING:
    from yoyopod.core import AppContext


_ASK_OFFLINE_BODY = "I cannot reach Ask right now. I can still help with music, calls, and volume."


@dataclass(slots=True, frozen=True)
class _QueuedSpeech:
    text: str
    generation: int | None = None
    record_response: bool = False
    cancel_event: threading.Event | None = None


class _AskClient(Protocol):
    @property
    def is_available(self) -> bool:
        """Return whether cloud Ask can accept requests."""
        ...

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
        """Return one answer from the cloud Ask worker."""
        ...


class VoiceRuntimeCoordinator:
    """Own one reusable voice interaction session outside the screen layer."""

    def __init__(
        self,
        *,
        context: "AppContext | None",
        settings_resolver: VoiceSettingsResolver,
        command_executor: VoiceCommandExecutor,
        voice_service_factory: Callable[[VoiceSettings], VoiceManager] | None = None,
        output_player: AlsaOutputPlayer | None = None,
        ask_client: _AskClient | None = None,
    ) -> None:
        self._context = context
        self._settings_resolver = settings_resolver
        self._command_executor = command_executor
        self._voice_service_factory = voice_service_factory
        self._output_player = output_player or AlsaOutputPlayer()
        self._ask_client = ask_client
        self._ask_conversation = AskConversationState()
        self._cached_voice_service: VoiceManager | None = None
        self._state = VoiceInteractionState()
        self._active_capture_cancel: threading.Event | None = None
        self._active_capture_cancel_lock = threading.Lock()
        self._state_listener: Callable[[VoiceInteractionState], None] | None = None
        self._outcome_listener: Callable[[VoiceCommandOutcome], None] | None = None
        self._dispatcher: Callable[[Callable[[], None]], None] | None = None
        self._tts_queue: Queue[_QueuedSpeech] = Queue()
        self._tts_thread: threading.Thread | None = None
        self._tts_thread_lock = threading.Lock()
        self._tts_cancel_lock = threading.Lock()
        self._tts_idle = threading.Event()
        self._tts_idle.set()
        self._tts_cancel_events: set[threading.Event] = set()
        self._generation_scoped_tts_cancel_events: set[threading.Event] = set()

    @property
    def state(self) -> VoiceInteractionState:
        """Return the current interaction snapshot."""

        return self._state

    def bind(
        self,
        *,
        state_listener: Callable[[VoiceInteractionState], None] | None,
        outcome_listener: Callable[[VoiceCommandOutcome], None] | None = None,
        dispatcher: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        """Bind optional UI consumers for voice state and outcomes."""

        self._state_listener = state_listener
        self._outcome_listener = outcome_listener
        self._dispatcher = dispatcher

    def defaults(self) -> VoiceSettings:
        """Expose default settings for compatibility callers."""

        return self._settings_resolver.defaults()

    def settings(self) -> VoiceSettings:
        """Expose current settings for compatibility callers."""

        return self._settings_resolver.current()

    def reset_to_idle(self) -> None:
        """Return the interaction to its ready state."""

        self.cancel()
        self._set_state("idle", "Ask", "Ask me anything...")

    def begin_entry_cycle(self, *, quick_command: bool, async_capture: bool) -> None:
        """Start the default Ask entry behavior for the current mode."""

        self.reset_to_idle()
        if quick_command:
            self.begin_ptt_capture()
            return
        self.begin_ask(async_capture=async_capture)

    def reset_conversation(self) -> None:
        """Clear the current Ask conversation history."""

        self._ask_conversation.reset()

    def begin_ask(self, *, async_capture: bool) -> None:
        """Start one record-transcribe-ask-answer cycle."""

        if self._state.capture_in_flight:
            return
        self._cancel_pending_speech_before_capture()
        voice_service, settings = self._voice_service_with_settings()
        readiness_error = self._prepare_ask_capture(
            voice_service=voice_service,
            settings=settings,
        )
        if readiness_error is not None:
            self._apply_outcome(readiness_error)
            return

        ask_client = self._ask_client
        if ask_client is None:
            self._apply_outcome(
                VoiceCommandOutcome(
                    "Ask Offline",
                    _ASK_OFFLINE_BODY,
                    should_speak=False,
                    auto_return=False,
                )
            )
            return

        self._ask_conversation.max_turns = max(1, settings.cloud_worker_ask_max_history_turns)
        self._ask_conversation.max_text_chars = max(
            1,
            settings.cloud_worker_ask_max_response_chars,
        )
        generation = self._next_generation()
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event
        self._set_state(
            "listening",
            "Listening",
            "Ask your question...",
            capture_in_flight=True,
            generation=generation,
        )
        if async_capture:
            threading.Thread(
                target=self._run_ask_cycle,
                args=(voice_service, ask_client, settings, generation, cancel_event),
                daemon=True,
                name="VoiceRuntimeAsk",
            ).start()
            return
        self._run_ask_cycle(voice_service, ask_client, settings, generation, cancel_event)

    def begin_listening(self, *, async_capture: bool) -> None:
        """Start one record-transcribe-command cycle."""

        if self._state.capture_in_flight:
            return
        self._cancel_pending_speech_before_capture()
        voice_service, settings = self._voice_service_with_settings()
        readiness_error = self._prepare_capture(voice_service=voice_service, settings=settings)
        if readiness_error is not None:
            self._apply_outcome(readiness_error)
            return

        generation = self._next_generation()
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event
        self._set_state(
            "listening",
            "Listening",
            "Speak now...",
            capture_in_flight=True,
            generation=generation,
        )
        if async_capture:
            threading.Thread(
                target=self._run_listening_cycle,
                args=(voice_service, generation, cancel_event),
                daemon=True,
                name="VoiceRuntimeCapture",
            ).start()
            return
        self._run_listening_cycle(voice_service, generation, cancel_event)

    def begin_ptt_capture(self) -> None:
        """Start an open-ended PTT capture that ends on release."""

        self._cancel_pending_speech_before_capture()
        voice_service, settings = self._voice_service_with_settings()
        readiness_error = self._prepare_capture(
            voice_service=voice_service,
            settings=settings,
            ptt_mode=True,
        )
        if readiness_error is not None:
            self._apply_outcome(readiness_error)
            return

        generation = self._next_generation()
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event
        self._set_state(
            "listening",
            "Listening",
            "Speak now...",
            capture_in_flight=True,
            ptt_active=True,
            generation=generation,
        )
        logger.info("PTT capture started (generation={})", generation)
        self._play_attention_tone()
        threading.Thread(
            target=self._run_ptt_listening_cycle,
            args=(voice_service, generation, cancel_event),
            daemon=True,
            name="VoiceRuntimePTT",
        ).start()

    def finish_ptt_capture(self) -> None:
        """Stop an active PTT capture and transition to thinking."""

        if not self._state.ptt_active or self._active_capture_cancel is None:
            return
        logger.info("PTT release received (generation={})", self._state.generation)
        self._set_state(
            "thinking",
            "Thinking",
            "Just a moment...",
            capture_in_flight=True,
            ptt_active=False,
        )
        self._active_capture_cancel.set()

    def cancel(self) -> None:
        """Cancel any in-flight capture without mutating navigation."""

        with self._active_capture_cancel_lock:
            self._next_generation()
            if self._active_capture_cancel is not None:
                self._active_capture_cancel.set()
                self._active_capture_cancel = None
        self._set_state(
            self._state.phase,
            self._state.headline,
            self._state.body,
            capture_in_flight=False,
            ptt_active=False,
        )

    def handle_transcript(self, transcript: str) -> VoiceCommandOutcome:
        """Execute one already-captured transcript through the shared command seam."""

        self._set_state("thinking", "Thinking", "Just a moment...")
        outcome = self._command_executor.execute(transcript)
        logger.info(
            "Voice command outcome headline={} should_speak={} route={} auto_return={} transcript={}",
            outcome.headline,
            outcome.should_speak,
            outcome.route_name or "",
            outcome.auto_return,
            _preview_voice_text(transcript),
        )
        self._apply_outcome(outcome)
        return outcome

    def dispatch_listen_result(
        self,
        transcript: str,
        *,
        capture_failed: bool,
        generation: int,
    ) -> None:
        """Apply one listen result, scheduling onto the bound dispatcher when needed."""

        def apply_result() -> None:
            if generation != self._state.generation:
                return
            self._active_capture_cancel = None
            logger.info(
                "Voice listen result applying generation={} capture_failed={} transcript_chars={} "
                "transcript={}",
                generation,
                capture_failed,
                len(transcript.strip()),
                _preview_voice_text(transcript),
            )
            if capture_failed:
                self._apply_outcome(
                    VoiceCommandOutcome(
                        "Mic Unavailable",
                        "The Pi microphone input is busy or unavailable.",
                        should_speak=False,
                    )
                )
                return
            if transcript:
                self.handle_transcript(transcript)
                return
            self._apply_outcome(
                VoiceCommandOutcome("No Speech", "I did not catch a command.", should_speak=False)
            )

        self._dispatch(apply_result)

    def _dispatch_ask_thinking(self, generation: int) -> None:
        """Move an active Ask generation into Thinking on the dispatcher path."""

        def apply_thinking() -> None:
            if generation != self._state.generation:
                return
            self._set_state(
                "thinking",
                "Thinking",
                "Finding an answer...",
                capture_in_flight=True,
            )

        self._dispatch(apply_thinking)

    def _dispatch_ask_outcome(
        self,
        outcome: VoiceCommandOutcome,
        generation: int,
        *,
        on_apply: Callable[[], None] | None = None,
    ) -> None:
        """Apply one Ask result when it still belongs to the active generation."""

        def apply_result() -> None:
            if generation != self._state.generation:
                return
            self._active_capture_cancel = None
            if on_apply is not None:
                on_apply()
            self._apply_ask_outcome(outcome, generation=generation)

        self._dispatch(apply_result)

    def _prepare_capture(
        self,
        *,
        voice_service: VoiceManager,
        settings: VoiceSettings,
        ptt_mode: bool = False,
    ) -> VoiceCommandOutcome | None:
        if self._context is not None and not self._context.voice.commands_enabled:
            body = (
                "Turn voice commands on in Setup first."
                if not ptt_mode
                else "Turn voice commands on in Setup first."
            )
            return VoiceCommandOutcome("Voice Off", body, should_speak=False)
        if self._context is not None and self._context.voice.mic_muted:
            body = (
                "Unmute the microphone in Setup or by voice first."
                if not ptt_mode
                else "Unmute the microphone first."
            )
            return VoiceCommandOutcome("Mic Muted", body, should_speak=False)

        if self._context is not None:
            self._context.update_voice_backend_status(
                stt_available=voice_service.capture_available() and voice_service.stt_available(),
                tts_available=voice_service.tts_available(),
            )
        if not voice_service.capture_available():
            body = (
                "Local recording is not ready on this device yet."
                if not ptt_mode
                else "Voice capture is not ready on this device."
            )
            return VoiceCommandOutcome("Mic Unavailable", body, should_speak=False)
        if not voice_service.stt_available():
            if settings.mode == "cloud":
                return VoiceCommandOutcome(
                    "Speech Offline",
                    "Cloud speech is unavailable. Local controls still work.",
                    should_speak=False,
                )
            return VoiceCommandOutcome(
                "Speech Offline",
                "The offline speech model is not installed yet.",
                should_speak=False,
            )
        return None

    def _prepare_ask_capture(
        self,
        *,
        voice_service: VoiceManager,
        settings: VoiceSettings,
    ) -> VoiceCommandOutcome | None:
        context_ai_disabled = (
            self._context is not None and not self._context.voice.ai_requests_enabled
        )
        if context_ai_disabled or not settings.ai_requests_enabled:
            return VoiceCommandOutcome(
                "Ask Off",
                "Turn Ask on in Setup first.",
                should_speak=False,
            )
        if self._context is not None and self._context.voice.mic_muted:
            return VoiceCommandOutcome(
                "Mic Muted",
                "Unmute the microphone first.",
                should_speak=False,
            )

        if self._context is not None:
            self._context.update_voice_backend_status(
                stt_available=voice_service.capture_available() and voice_service.stt_available(),
                tts_available=voice_service.tts_available(),
            )
        if self._ask_client is None or not self._ask_client.is_available:
            return VoiceCommandOutcome(
                "Ask Offline",
                _ASK_OFFLINE_BODY,
                should_speak=False,
                auto_return=False,
            )
        if not voice_service.capture_available():
            return VoiceCommandOutcome(
                "Mic Unavailable",
                "Voice capture is not ready on this device.",
                should_speak=False,
            )
        if not voice_service.stt_available():
            return VoiceCommandOutcome(
                "Speech Offline",
                "Cloud speech is unavailable. Local controls still work.",
                should_speak=False,
                auto_return=False,
            )
        return None

    def _voice_service(self) -> VoiceManager:
        return self._voice_service_with_settings()[0]

    def _voice_service_with_settings(self) -> tuple[VoiceManager, VoiceSettings]:
        settings = self._settings_resolver.current()
        if self._cached_voice_service is None:
            self._cached_voice_service = self._build_voice_service(settings)
            return self._cached_voice_service, settings
        if getattr(self._cached_voice_service, "settings", settings) != settings:
            release_resources = getattr(self._cached_voice_service, "release_resources", None)
            if callable(release_resources):
                release_resources()
            self._cached_voice_service = self._build_voice_service(settings)
        return self._cached_voice_service, settings

    def _build_voice_service(self, settings: VoiceSettings) -> VoiceManager:
        if self._voice_service_factory is not None:
            service = self._voice_service_factory(settings)
            if getattr(service, "settings", None) is None:
                try:
                    setattr(service, "settings", settings)
                except Exception:
                    pass
            return service
        return VoiceManager(settings=settings)

    def _next_generation(self) -> int:
        self._cancel_generation_scoped_tts()
        self._state.generation += 1
        return self._state.generation

    def _cancel_pending_speech_before_capture(self) -> None:
        with self._tts_cancel_lock:
            cancel_events = list(self._tts_cancel_events)
        for cancel_event in cancel_events:
            cancel_event.set()
        if cancel_events:
            self._tts_idle.wait(timeout=1.0)

    def _cancel_generation_scoped_tts(self) -> None:
        with self._tts_cancel_lock:
            cancel_events = list(self._generation_scoped_tts_cancel_events)
        for cancel_event in cancel_events:
            cancel_event.set()

    def _run_listening_cycle(
        self,
        voice_service: VoiceManager,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        self._play_attention_tone()
        request = VoiceCaptureRequest(
            mode="voice_commands",
            timeout_seconds=4.0,
            cancel_event=cancel_event,
        )
        capture_result = voice_service.capture_audio(request)
        if cancel_event.is_set():
            if capture_result.audio_path is not None:
                capture_result.audio_path.unlink(missing_ok=True)
            return
        if capture_result.audio_path is None:
            self.dispatch_listen_result("", capture_failed=True, generation=generation)
            return

        try:
            transcript = voice_service.transcribe(
                capture_result.audio_path,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            logger.warning("Voice command transcription failed: {}", exc)
            self.dispatch_listen_result("", capture_failed=True, generation=generation)
            return
        finally:
            capture_result.audio_path.unlink(missing_ok=True)

        if cancel_event.is_set():
            return
        self.dispatch_listen_result(
            transcript.text.strip(),
            capture_failed=False,
            generation=generation,
        )

    def _run_ask_cycle(
        self,
        voice_service: VoiceManager,
        ask_client: _AskClient,
        settings: VoiceSettings,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        self._play_attention_tone()
        request = VoiceCaptureRequest(
            mode="ask",
            timeout_seconds=4.0,
            cancel_event=cancel_event,
        )
        capture_result = voice_service.capture_audio(request)
        if cancel_event.is_set() or generation != self._state.generation:
            if capture_result.audio_path is not None:
                capture_result.audio_path.unlink(missing_ok=True)
            return
        if capture_result.audio_path is None:
            self._dispatch_ask_outcome(
                VoiceCommandOutcome(
                    "No Speech",
                    "I did not catch that.",
                    should_speak=False,
                    auto_return=False,
                ),
                generation,
            )
            return

        try:
            transcript = voice_service.transcribe(
                capture_result.audio_path,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            logger.warning("Ask transcription failed: {}", exc)
            self._dispatch_ask_outcome(
                VoiceCommandOutcome(
                    "Mic Unavailable",
                    "The Pi microphone input is busy or unavailable.",
                    should_speak=False,
                    auto_return=False,
                ),
                generation,
            )
            return
        finally:
            capture_result.audio_path.unlink(missing_ok=True)

        if cancel_event.is_set() or generation != self._state.generation:
            return
        question = transcript.text.strip()
        if not question:
            self._dispatch_ask_outcome(
                VoiceCommandOutcome(
                    "No Speech",
                    "I did not catch that.",
                    should_speak=False,
                    auto_return=False,
                ),
                generation,
            )
            return
        if self._ask_conversation.is_exit_request(question):
            self._dispatch_ask_outcome(
                VoiceCommandOutcome(
                    "Ask",
                    "Going back.",
                    should_speak=False,
                    route_name="back",
                    auto_return=False,
                ),
                generation,
            )
            return

        self._dispatch_ask_thinking(generation)
        if cancel_event.is_set() or generation != self._state.generation:
            return
        history = self._ask_conversation.history_for_worker()
        try:
            result = ask_client.ask(
                question=question,
                history=history,
                model=settings.cloud_worker_ask_model,
                instructions=settings.cloud_worker_ask_instructions,
                max_output_chars=self._ask_conversation.max_text_chars,
                cancel_event=cancel_event,
                timeout_seconds=settings.cloud_worker_ask_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Ask worker request failed: {}", exc)
            self._dispatch_ask_outcome(
                VoiceCommandOutcome(
                    "Ask Offline",
                    _ASK_OFFLINE_BODY,
                    should_speak=False,
                    auto_return=False,
                ),
                generation,
            )
            return

        if cancel_event.is_set() or generation != self._state.generation:
            return
        self._dispatch_ask_outcome(
            VoiceCommandOutcome(
                "Answer",
                result.answer,
                should_speak=True,
                auto_return=False,
            ),
            generation,
            on_apply=lambda: self._ask_conversation.append(question, result.answer),
        )

    def _run_ptt_listening_cycle(
        self,
        voice_service: VoiceManager,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        request = VoiceCaptureRequest(
            mode="voice_commands_ptt",
            timeout_seconds=30.0,
            cancel_event=cancel_event,
        )
        capture_result = voice_service.capture_audio(request)
        logger.info(
            "PTT capture finished (generation={}, recorded={}, audio_path={})",
            generation,
            capture_result.recorded,
            capture_result.audio_path is not None,
        )

        if generation != self._state.generation:
            if capture_result.audio_path is not None:
                capture_result.audio_path.unlink(missing_ok=True)
            return

        if capture_result.audio_path is None:
            if not self._state.ptt_active:
                logger.info("PTT capture ended without audio; treating the release as no speech")
                self.dispatch_listen_result("", capture_failed=False, generation=generation)
            else:
                logger.warning("PTT capture ended without audio while hold was still active")
                self.dispatch_listen_result("", capture_failed=True, generation=generation)
            return

        if not self._state.ptt_active:
            logger.info(
                "PTT release finalized capture; starting transcription (generation={})",
                generation,
            )
            transcription_cancel_event = threading.Event()
            with self._active_capture_cancel_lock:
                if (
                    generation != self._state.generation
                    or self._active_capture_cancel is not cancel_event
                ):
                    capture_result.audio_path.unlink(missing_ok=True)
                    return
                self._active_capture_cancel = transcription_cancel_event
            try:
                transcript = voice_service.transcribe(
                    capture_result.audio_path,
                    cancel_event=transcription_cancel_event,
                )
            except Exception as exc:
                if transcription_cancel_event.is_set() or generation != self._state.generation:
                    logger.info(
                        "PTT transcription cancelled (generation={})",
                        generation,
                    )
                    return
                logger.warning("PTT transcription failed: {}", exc)
                self.dispatch_listen_result("", capture_failed=True, generation=generation)
                return
            finally:
                capture_result.audio_path.unlink(missing_ok=True)

            if transcription_cancel_event.is_set() or generation != self._state.generation:
                return
            self.dispatch_listen_result(
                transcript.text.strip(),
                capture_failed=False,
                generation=generation,
            )
            logger.info(
                "PTT transcription complete (generation={}, transcript_chars={}, transcript={})",
                generation,
                len(transcript.text.strip()),
                _preview_voice_text(transcript.text),
            )
            return

        capture_result.audio_path.unlink(missing_ok=True)

    def _apply_outcome(self, outcome: VoiceCommandOutcome) -> None:
        logger.info(
            "Voice outcome applied headline={} should_speak={} route={} auto_return={} body_chars={}",
            outcome.headline,
            outcome.should_speak,
            outcome.route_name or "",
            outcome.auto_return,
            len(outcome.body),
        )
        self._set_state(
            "reply",
            outcome.headline,
            outcome.body,
            capture_in_flight=False,
            ptt_active=False,
        )
        if self._context is not None and outcome.should_speak:
            self._context.record_voice_response(outcome.body)
        if outcome.should_speak:
            self._speak_outcome_async(outcome.body)
        if self._outcome_listener is not None:
            self._dispatch(lambda: self._outcome_listener(outcome))

    def _apply_ask_outcome(self, outcome: VoiceCommandOutcome, *, generation: int) -> None:
        logger.info(
            "Ask outcome applied headline={} should_speak={} route={} auto_return={} body_chars={}",
            outcome.headline,
            outcome.should_speak,
            outcome.route_name or "",
            outcome.auto_return,
            len(outcome.body),
        )
        self._set_state(
            "reply",
            outcome.headline,
            outcome.body,
            capture_in_flight=False,
            ptt_active=False,
        )
        if outcome.should_speak:
            self._speak_outcome_async(
                outcome.body,
                generation=generation,
                record_response=True,
            )
        if self._outcome_listener is not None:
            self._dispatch(lambda: self._outcome_listener(outcome))

    def _speak_outcome_async(
        self,
        text: str,
        *,
        generation: int | None = None,
        record_response: bool = False,
    ) -> None:
        """Speak an outcome outside the main-thread UI path."""

        self._ensure_tts_worker()
        cancel_event = threading.Event()
        with self._tts_cancel_lock:
            self._tts_cancel_events.add(cancel_event)
        if generation is not None:
            with self._tts_cancel_lock:
                self._generation_scoped_tts_cancel_events.add(cancel_event)
        self._tts_queue.put(
            _QueuedSpeech(
                text=text,
                generation=generation,
                record_response=record_response,
                cancel_event=cancel_event,
            )
        )

    def _ensure_tts_worker(self) -> None:
        """Start the serialized outcome-speech worker once."""

        with self._tts_thread_lock:
            if self._tts_thread is not None and self._tts_thread.is_alive():
                return
            self._tts_thread = threading.Thread(
                target=self._run_tts_worker,
                daemon=True,
                name="VoiceRuntimeTTS",
            )
            self._tts_thread.start()

    def _run_tts_worker(self) -> None:
        while True:
            item = self._tts_queue.get()
            started_at = time.monotonic()
            try:
                if item.generation is not None and item.generation != self._state.generation:
                    logger.info(
                        "Voice response speech skipped for stale generation={} current={}",
                        item.generation,
                        self._state.generation,
                    )
                    continue
                if item.cancel_event is not None and item.cancel_event.is_set():
                    logger.info(
                        "Voice response speech skipped because cancellation was already set"
                    )
                    continue
                logger.info(
                    "Voice response speech started chars={} text={}",
                    len(item.text.strip()),
                    _preview_voice_text(item.text),
                )
                self._tts_idle.clear()
                spoken = self._voice_service().speak(
                    item.text,
                    cancel_event=item.cancel_event,
                )
                if not spoken:
                    logger.debug("Voice response not spoken: {}", item.text)
                if (
                    spoken
                    and item.record_response
                    and self._context is not None
                    and not (item.cancel_event is not None and item.cancel_event.is_set())
                    and (item.generation is None or item.generation == self._state.generation)
                ):
                    self._context.record_voice_response(item.text)
                logger.info(
                    "Voice response speech finished spoken={} elapsed_ms={:.1f}",
                    spoken,
                    (time.monotonic() - started_at) * 1000,
                )
            except Exception:
                logger.exception("Voice response speech failed")
            finally:
                if item.cancel_event is not None:
                    with self._tts_cancel_lock:
                        self._tts_cancel_events.discard(item.cancel_event)
                        self._generation_scoped_tts_cancel_events.discard(item.cancel_event)
                self._tts_queue.task_done()
                if self._tts_queue.empty():
                    self._tts_idle.set()

    def _set_state(
        self,
        phase: str,
        headline: str,
        body: str,
        *,
        capture_in_flight: bool | None = None,
        ptt_active: bool | None = None,
        generation: int | None = None,
    ) -> None:
        if capture_in_flight is None:
            capture_in_flight = self._state.capture_in_flight
        if ptt_active is None:
            ptt_active = self._state.ptt_active
        if generation is None:
            generation = self._state.generation

        self._state.phase = phase
        self._state.headline = headline
        self._state.body = body
        self._state.capture_in_flight = capture_in_flight
        self._state.ptt_active = ptt_active
        self._state.generation = generation
        if self._context is not None:
            self._context.update_voice_interaction(
                phase=phase,
                headline=headline,
                body=body,
                capture_in_flight=capture_in_flight,
                ptt_active=ptt_active,
                generation=generation,
            )
        if self._state_listener is not None:
            snapshot = replace(self._state)
            self._dispatch(lambda: self._state_listener(snapshot))

    def _dispatch(self, callback: Callable[[], None]) -> None:
        if self._dispatcher is not None:
            self._dispatcher(callback)
            return
        callback()

    def _play_attention_tone(self) -> None:
        try:
            if not self._settings_resolver.current().local_feedback_enabled:
                return
        except Exception:
            logger.debug("Voice local feedback setting unavailable")

        beep_path: Path | None = None
        try:
            with NamedTemporaryFile(prefix="yoyopod-beep-", suffix=".wav", delete=False) as handle:
                beep_path = Path(handle.name)
            self._write_beep_wav(beep_path)
            device_id = self._context.voice.speaker_device_id if self._context is not None else None
            play_kwargs: dict[str, object] = {
                "timeout_seconds": 2.0,
                "block_if_busy": False,
            }
            if device_id:
                play_kwargs["device_id"] = device_id
            self._output_player.play_wav(beep_path, **play_kwargs)
        except Exception:
            logger.debug("Voice attention tone unavailable")
        finally:
            if beep_path is not None:
                beep_path.unlink(missing_ok=True)

    @staticmethod
    def _write_beep_wav(path: Path) -> None:
        sample_rate = 16000
        duration_seconds = 0.18
        frequency_hz = 1046.0
        amplitude = 12000
        frame_count = int(sample_rate * duration_seconds)

        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            frames = bytearray()
            for index in range(frame_count):
                envelope = 1.0 - (index / frame_count)
                sample = int(
                    amplitude
                    * envelope
                    * math.sin((2.0 * math.pi * frequency_hz * index) / sample_rate)
                )
                frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
            handle.writeframes(bytes(frames))


def _preview_voice_text(text: str, *, limit: int = 96) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return repr(normalized)
    return repr(normalized[: limit - 3] + "...")
