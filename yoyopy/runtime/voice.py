"""Shared runtime-owned voice orchestration for Ask and future voice contexts."""

from __future__ import annotations

import math
import threading
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopy.runtime_state import VoiceInteractionState
from yoyopy.voice import VoiceCaptureRequest, VoiceCommandIntent, VoiceService, VoiceSettings
from yoyopy.voice.commands import match_voice_command
from yoyopy.voice.output import AlsaOutputPlayer

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager, Contact
    from yoyopy.voip import VoIPManager


@dataclass(slots=True, frozen=True)
class VoiceCommandOutcome:
    """Result returned by the shared voice command executor."""

    headline: str
    body: str
    should_speak: bool = True
    route_name: str | None = None


class VoiceSettingsResolver:
    """Resolve current voice settings from the app runtime and config layer."""

    def __init__(
        self,
        *,
        context: "AppContext | None",
        config_manager: "ConfigManager | None" = None,
        settings_provider: Callable[[], VoiceSettings] | None = None,
    ) -> None:
        self._context = context
        self._config_manager = config_manager
        self._settings_provider = settings_provider

    def current(self) -> VoiceSettings:
        """Return the latest runtime voice settings."""

        if self._settings_provider is not None:
            return self._settings_provider()
        defaults = self.defaults()
        if self._context is None:
            return defaults

        voice = self._context.voice
        capture_device_id = (
            voice.capture_device_id
            if voice.capture_device_id is not None
            else defaults.capture_device_id
        )
        speaker_device_id = (
            voice.speaker_device_id
            if voice.speaker_device_id is not None
            else defaults.speaker_device_id
        )
        return replace(
            defaults,
            commands_enabled=voice.commands_enabled,
            ai_requests_enabled=voice.ai_requests_enabled,
            screen_read_enabled=voice.screen_read_enabled,
            stt_enabled=voice.stt_enabled,
            tts_enabled=voice.tts_enabled,
            mic_muted=voice.mic_muted,
            output_volume=voice.output_volume,
            capture_device_id=capture_device_id,
            speaker_device_id=speaker_device_id,
        )

    def defaults(self) -> VoiceSettings:
        """Return configured voice defaults when no provider is supplied."""

        capture_device_id = None
        speaker_device_id = None
        if self._config_manager is not None:
            voice_cfg = getattr(self._config_manager.get_app_settings(), "voice", None)
            if voice_cfg is not None:
                capture_device_id = getattr(voice_cfg, "capture_device_id", "").strip() or None
                speaker_device_id = getattr(voice_cfg, "speaker_device_id", "").strip() or None
            if capture_device_id is None:
                capture_device_id = self._config_manager.get_capture_device_id()
            if speaker_device_id is None:
                speaker_device_id = getattr(
                    self._config_manager,
                    "get_ring_output_device",
                    lambda: None,
                )()

        defaults = VoiceSettings(
            capture_device_id=capture_device_id,
            speaker_device_id=speaker_device_id or None,
        )
        if self._config_manager is None:
            return defaults

        get_app_settings = getattr(self._config_manager, "get_app_settings", None)
        if not callable(get_app_settings):
            return defaults

        app_settings = get_app_settings()
        voice_cfg = getattr(app_settings, "voice", None)
        if voice_cfg is None:
            return defaults

        get_default_output_volume = getattr(self._config_manager, "get_default_output_volume", None)
        output_volume = defaults.output_volume
        if callable(get_default_output_volume):
            output_volume = int(get_default_output_volume())

        return VoiceSettings(
            commands_enabled=voice_cfg.commands_enabled,
            ai_requests_enabled=voice_cfg.ai_requests_enabled,
            screen_read_enabled=voice_cfg.screen_read_enabled,
            stt_enabled=voice_cfg.stt_enabled,
            tts_enabled=voice_cfg.tts_enabled,
            output_volume=output_volume,
            stt_backend=voice_cfg.stt_backend,
            tts_backend=voice_cfg.tts_backend,
            vosk_model_path=voice_cfg.vosk_model_path,
            speaker_device_id=speaker_device_id,
            capture_device_id=capture_device_id,
            sample_rate_hz=voice_cfg.sample_rate_hz,
            record_seconds=voice_cfg.record_seconds,
            tts_rate_wpm=voice_cfg.tts_rate_wpm,
            tts_voice=voice_cfg.tts_voice,
        )


class VoiceCommandExecutor:
    """Execute deterministic voice commands against app runtime seams."""

    _FAMILY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
        ("mom", "mama", "mum", "mommy", "mother"),
        ("dad", "dada", "daddy", "papa", "father"),
    )

    def __init__(
        self,
        *,
        context: "AppContext | None",
        config_manager: "ConfigManager | None" = None,
        voip_manager: "VoIPManager | None" = None,
        volume_up_action: Callable[[int], int | None] | None = None,
        volume_down_action: Callable[[int], int | None] | None = None,
        mute_action: Callable[[], bool] | None = None,
        unmute_action: Callable[[], bool] | None = None,
        play_music_action: Callable[[], bool] | None = None,
        screen_summary_provider: Callable[[], str] | None = None,
    ) -> None:
        self._context = context
        self._config_manager = config_manager
        self._voip_manager = voip_manager
        self._volume_up_action = volume_up_action
        self._volume_down_action = volume_down_action
        self._mute_action = mute_action
        self._unmute_action = unmute_action
        self._play_music_action = play_music_action
        self._screen_summary_provider = screen_summary_provider or self._default_screen_summary

    def execute(self, transcript: str) -> VoiceCommandOutcome:
        """Parse and execute one local deterministic voice command."""

        normalized = transcript.strip()
        if not normalized:
            return VoiceCommandOutcome("No Speech", "I did not catch a command.", should_speak=False)

        if self._context is not None:
            self._context.record_voice_transcript(normalized, mode="voice_commands")

        command = match_voice_command(normalized)
        if not command.is_command:
            return VoiceCommandOutcome(
                "Not Recognized",
                "I heard "
                f"'{normalized}'"
                " but that is not a voice command. Try: call mom, play music, or volume up.",
            )

        if command.intent is VoiceCommandIntent.CALL_CONTACT:
            return self._handle_call_command(command.contact_name)
        if command.intent is VoiceCommandIntent.VOLUME_UP:
            return self._handle_volume_change(+5)
        if command.intent is VoiceCommandIntent.VOLUME_DOWN:
            return self._handle_volume_change(-5)
        if command.intent is VoiceCommandIntent.PLAY_MUSIC:
            return self._handle_play_music_command()
        if command.intent is VoiceCommandIntent.MUTE_MIC:
            self._apply_mic_state(muted=True)
            return VoiceCommandOutcome("Mic Muted", "Voice commands mic is muted.")
        if command.intent is VoiceCommandIntent.UNMUTE_MIC:
            self._apply_mic_state(muted=False)
            return VoiceCommandOutcome("Mic Live", "Voice commands mic is live.")
        if command.intent is VoiceCommandIntent.READ_SCREEN:
            return VoiceCommandOutcome("Screen Read", self._screen_summary_provider())

        return VoiceCommandOutcome("Not Ready", "That command is recognized but not wired yet.")

    def _handle_volume_change(self, delta: int) -> VoiceCommandOutcome:
        current = None
        if delta > 0 and self._volume_up_action is not None:
            current = self._volume_up_action(abs(delta))
        elif delta < 0 and self._volume_down_action is not None:
            current = self._volume_down_action(abs(delta))
        elif self._context is not None:
            current = (
                self._context.volume_up(abs(delta))
                if delta > 0
                else self._context.volume_down(abs(delta))
            )

        self._sync_context_output_volume(current)
        if current is None and self._context is not None:
            current = self._context.voice.output_volume
        return VoiceCommandOutcome(
            "Volume",
            f"Volume is {current if current is not None else 'updated'}.",
        )

    def _handle_play_music_command(self) -> VoiceCommandOutcome:
        if self._play_music_action is None:
            return VoiceCommandOutcome("Music Off", "Local music playback is not ready yet.")
        if not self._play_music_action():
            return VoiceCommandOutcome("Music Empty", "I could not find any local music to play.")
        return VoiceCommandOutcome("Playing", "Starting local music.", route_name="shuffle_started")

    def _handle_call_command(self, spoken_name: str) -> VoiceCommandOutcome:
        contact = self._find_contact(spoken_name)
        if contact is None:
            return VoiceCommandOutcome("No Match", f"I could not find {spoken_name}.")

        display_name = contact.display_name
        if self._context is not None:
            self._context.set_talk_contact(name=display_name, sip_address=contact.sip_address)

        if self._voip_manager is None:
            return VoiceCommandOutcome(
                "Call Ready",
                f"I found {display_name}, but calling is not ready.",
            )

        if self._voip_manager.make_call(contact.sip_address, contact_name=display_name):
            return VoiceCommandOutcome(
                "Calling",
                f"Calling {display_name}.",
                route_name="call_started",
            )

        return VoiceCommandOutcome("Call Failed", f"I could not call {display_name}.")

    def _find_contact(self, spoken_name: str) -> "Contact | None":
        if self._config_manager is None:
            return None

        normalized = self._normalize_label(spoken_name)
        if not normalized:
            return None

        for contact in self._config_manager.get_contacts():
            if normalized in self._contact_labels(contact):
                return contact
        return None

    @classmethod
    def _normalize_label(cls, value: str) -> str:
        return " ".join(value.strip().lower().split())

    @classmethod
    def _contact_labels(cls, contact: "Contact") -> set[str]:
        labels = {
            cls._normalize_label(contact.name),
            cls._normalize_label(contact.display_name),
            cls._normalize_label(getattr(contact, "notes", "")),
        }
        labels.discard("")

        expanded = set(labels)
        for group in cls._FAMILY_ALIAS_GROUPS:
            if any(label in group for label in labels):
                expanded.update(group)
        return expanded

    def _default_screen_summary(self) -> str:
        if self._context is not None and self._context.voice.screen_read_enabled:
            return "You are on Ask. Say a direct command now."
        return "Screen read is off. Turn it on in Setup to auto-read screens."

    def _apply_mic_state(self, *, muted: bool) -> None:
        if self._context is not None:
            self._context.set_mic_muted(muted)
        action = self._mute_action if muted else self._unmute_action
        if action is not None:
            try:
                action()
            except Exception as exc:
                logger.warning("Voice mic state update failed: {}", exc)

    def _sync_context_output_volume(self, volume: int | None) -> None:
        if volume is None or self._context is None:
            return
        self._context.playback.volume = volume
        self._context.voice.output_volume = volume


class VoiceRuntimeCoordinator:
    """Own one reusable voice interaction session outside the screen layer."""

    def __init__(
        self,
        *,
        context: "AppContext | None",
        settings_resolver: VoiceSettingsResolver,
        command_executor: VoiceCommandExecutor,
        voice_service_factory: Callable[[VoiceSettings], VoiceService] | None = None,
        output_player: AlsaOutputPlayer | None = None,
    ) -> None:
        self._context = context
        self._settings_resolver = settings_resolver
        self._command_executor = command_executor
        self._voice_service_factory = voice_service_factory
        self._output_player = output_player or AlsaOutputPlayer()
        self._cached_voice_service: VoiceService | None = None
        self._state = VoiceInteractionState()
        self._active_capture_cancel: threading.Event | None = None
        self._state_listener: Callable[[VoiceInteractionState], None] | None = None
        self._outcome_listener: Callable[[VoiceCommandOutcome], None] | None = None
        self._dispatcher: Callable[[Callable[[], None]], None] | None = None

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
        self.begin_listening(async_capture=async_capture)

    def begin_listening(self, *, async_capture: bool) -> None:
        """Start one record-transcribe-command cycle."""

        if self._state.capture_in_flight:
            return
        voice_service = self._voice_service()
        readiness_error = self._prepare_capture(voice_service=voice_service)
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

        voice_service = self._voice_service()
        readiness_error = self._prepare_capture(voice_service=voice_service, ptt_mode=True)
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

    def _prepare_capture(
        self,
        *,
        voice_service: VoiceService,
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
            return VoiceCommandOutcome(
                "Speech Offline",
                "The offline speech model is not installed yet.",
                should_speak=False,
            )
        return None

    def _voice_service(self) -> VoiceService:
        settings = self._settings_resolver.current()
        if self._voice_service_factory is not None:
            return self._voice_service_factory(settings)
        if self._cached_voice_service is None or self._cached_voice_service.settings != settings:
            self._cached_voice_service = VoiceService(settings=settings)
        return self._cached_voice_service

    def _next_generation(self) -> int:
        self._state.generation += 1
        return self._state.generation

    def _run_listening_cycle(
        self,
        voice_service: VoiceService,
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
            transcript = voice_service.transcribe(capture_result.audio_path)
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

    def _run_ptt_listening_cycle(
        self,
        voice_service: VoiceService,
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
            try:
                transcript = voice_service.transcribe(capture_result.audio_path)
            except Exception as exc:
                logger.warning("PTT transcription failed: {}", exc)
                self.dispatch_listen_result("", capture_failed=True, generation=generation)
                return
            finally:
                capture_result.audio_path.unlink(missing_ok=True)

            self.dispatch_listen_result(
                transcript.text.strip(),
                capture_failed=False,
                generation=generation,
            )
            logger.info(
                "PTT transcription complete (generation={}, transcript_chars={})",
                generation,
                len(transcript.text.strip()),
            )
            return

        capture_result.audio_path.unlink(missing_ok=True)

    def _apply_outcome(self, outcome: VoiceCommandOutcome) -> None:
        self._set_state(
            "reply",
            outcome.headline,
            outcome.body,
            capture_in_flight=False,
            ptt_active=False,
        )
        if self._context is not None and outcome.should_speak:
            self._context.record_voice_response(outcome.body)
        if outcome.should_speak and not self._voice_service().speak(outcome.body):
            logger.debug("Voice response not spoken: {}", outcome.body)
        if self._outcome_listener is not None:
            self._dispatch(lambda: self._outcome_listener(outcome))

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
        beep_path: Path | None = None
        try:
            with NamedTemporaryFile(prefix="yoyopy-beep-", suffix=".wav", delete=False) as handle:
                beep_path = Path(handle.name)
            self._write_beep_wav(beep_path)
            device_id = self._context.voice.speaker_device_id if self._context is not None else None
            play_kwargs: dict[str, object] = {"timeout_seconds": 2.0}
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
