"""Unified Ask screen with voice-command logic."""

from __future__ import annotations

import math
import threading
import wave
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.navigation.lvgl import LvglAskView
from yoyopy.ui.screens.theme import (
    ASK,
    INK,
    MUTED,
    MUTED_DIM,
    draw_icon,
    render_footer,
    render_header,
    rounded_panel,
    text_fit,
    wrap_text,
)
from yoyopy.voice import VoiceCaptureRequest, VoiceCommandIntent, VoiceService, VoiceSettings
from yoyopy.voice.output import AlsaOutputPlayer

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager, Contact
    from yoyopy.ui.screens import ScreenView
    from yoyopy.voip import VoIPManager


# ---------------------------------------------------------------------------
# Icon circle colors (pre-blended over BACKGROUND)
# ---------------------------------------------------------------------------
_ICON_CIRCLE_IDLE: tuple[int, int, int] = (74, 69, 45)
_ICON_CIRCLE_LISTENING: tuple[int, int, int] = (95, 86, 48)

# ---------------------------------------------------------------------------
# Unified Ask screen
# ---------------------------------------------------------------------------


class AskScreen(Screen):
    """Unified stateful Ask screen with idle / listening / thinking / reply states."""

    _FAMILY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
        ("mom", "mama", "mum", "mommy", "mother"),
        ("dad", "dada", "daddy", "papa", "father"),
    )
    _HINT_TEXT = "Say things like call mom, play music, volume up, mute mic, or read screen."

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        config_manager: Optional["ConfigManager"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        volume_up_action: Optional[Callable[[int], int | None]] = None,
        volume_down_action: Optional[Callable[[int], int | None]] = None,
        mute_action: Optional[Callable[[], bool]] = None,
        unmute_action: Optional[Callable[[], bool]] = None,
        play_music_action: Optional[Callable[[], bool]] = None,
        voice_settings_provider: Optional[Callable[[], VoiceSettings]] = None,
        voice_service_factory: Optional[Callable[[VoiceSettings], VoiceService]] = None,
    ) -> None:
        super().__init__(display, context, "Ask")
        self.config_manager = config_manager
        self.voip_manager = voip_manager
        self.volume_up_action = volume_up_action
        self.volume_down_action = volume_down_action
        self.mute_action = mute_action
        self.unmute_action = unmute_action
        self.play_music_action = play_music_action
        self.voice_settings_provider = voice_settings_provider
        self.voice_service_factory = voice_service_factory
        self._cached_voice_service: VoiceService | None = None
        self._state: str = "idle"
        self._headline: str = "Ask"
        self._body: str = "Ask me anything..."
        self._auto_listen_started = False
        self._capture_in_flight = False
        self._listen_generation = 0
        self._active_capture_cancel: threading.Event | None = None
        self._output_player = AlsaOutputPlayer()
        # Quick-command support
        self._quick_command = False
        self._ptt_active = False
        self._auto_return_timer: threading.Timer | None = None
        self._lvgl_view: "ScreenView | None" = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self) -> None:
        """Reset to a ready state when entering the Ask screen."""

        super().enter()
        self._cancel_listening_cycle()
        self._auto_listen_started = False
        self._capture_in_flight = False

        if self._quick_command:
            # Skip idle and jump straight into PTT capture
            self._state = "idle"
            self._headline = "Ask"
            self._body = "Ask me anything..."
            self._start_ptt_capture()
        else:
            self._state = "idle"
            self._headline = "Ask"
            self._body = "Ask me anything..."
            self._begin_listening_on_entry()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Invalidate any in-flight result before leaving the screen."""

        self._cancel_listening_cycle()
        self._cancel_auto_return()
        self._quick_command = False
        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    # ------------------------------------------------------------------
    # Quick-command support
    # ------------------------------------------------------------------

    def set_quick_command(self, enabled: bool) -> None:
        """Enable or disable quick-command mode for one-shot entry."""

        self._quick_command = enabled

    def wants_ptt_passthrough(self) -> bool:
        """Return True when Ask should receive raw PTT release events."""

        return self.is_one_button_mode() and self._quick_command

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: str, headline: str, body: str) -> None:
        """Update the visual state, headline, and body text."""

        self._state = state
        self._headline = headline
        self._body = body

    def _set_response(self, headline: str, body: str) -> None:
        """Transition to the reply state without spoken playback."""

        self._state = "reply"
        self._headline = headline
        self._body = body

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglAskView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current Ask state."""

        icon_key = "ask"
        if self._headline in {"Mic Muted", "Mic Unavailable", "Voice Off"}:
            icon_key = "mic_off"
        return (self._headline, self._body, self._render_hint_bar(), icon_key)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Render the current Ask state."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        if self._state == "reply":
            self._render_reply()
        else:
            self._render_icon_state()

    def _render_icon_state(self) -> None:
        """Render idle / listening / thinking states with centered icon circle."""

        content_top = render_header(
            self.display,
            self.context,
            mode="ask",
            title="Ask",
            show_time=False,
            show_mode_chip=False,
        )

        # Icon circle (112x112)
        circle_size = 112
        circle_radius = circle_size // 2
        cx = (self.display.WIDTH - circle_size) // 2
        cy = content_top + 12
        if self._state == "listening":
            circle_fill = _ICON_CIRCLE_LISTENING
        else:
            circle_fill = _ICON_CIRCLE_IDLE

        rounded_panel(
            self.display,
            cx,
            cy,
            cx + circle_size,
            cy + circle_size,
            fill=circle_fill,
            outline=None,
            radius=circle_radius,
        )

        # 56x56 icon centered inside the circle
        icon_size = 56
        icon_x = cx + (circle_size - icon_size) // 2
        icon_y = cy + (circle_size - icon_size) // 2
        draw_icon(self.display, "ask", icon_x, icon_y, icon_size, ASK.accent)

        # Centered heading (20px, white)
        heading = text_fit(self.display, self._headline, self.display.WIDTH - 40, 20)
        heading_w, _ = self.display.get_text_size(heading, 20)
        heading_y = cy + circle_size + 10
        self.display.text(
            heading,
            (self.display.WIDTH - heading_w) // 2,
            heading_y,
            color=INK,
            font_size=20,
        )

        # Centered subtitle (14px)
        if self._state == "thinking":
            subtitle_color = MUTED_DIM
        else:
            subtitle_color = ASK.accent

        subtitle = text_fit(self.display, self._body, self.display.WIDTH - 40, 14)
        subtitle_w, _ = self.display.get_text_size(subtitle, 14)
        subtitle_y = heading_y + 24
        self.display.text(
            subtitle,
            (self.display.WIDTH - subtitle_w) // 2,
            subtitle_y,
            color=subtitle_color,
            font_size=14,
        )

        render_footer(self.display, self._render_hint_bar(), mode="ask")
        self.display.update()

    def _render_reply(self) -> None:
        """Render the reply state with left-aligned wrapped text."""

        content_top = render_header(
            self.display,
            self.context,
            mode="ask",
            title=self._headline,
            show_time=False,
            show_mode_chip=False,
        )

        # Left-aligned wrapped body text
        text_x = 24
        text_y = content_top + 16
        line_height = 23
        max_lines = 8
        text_max_width = self.display.WIDTH - (text_x * 2)
        lines = wrap_text(self.display, self._body, text_max_width, 14, max_lines=max_lines)
        for line in lines:
            self.display.text(
                line,
                text_x,
                text_y,
                color=MUTED,
                font_size=14,
            )
            text_y += line_height

        render_footer(self.display, self._render_hint_bar(), mode="ask")
        self.display.update()

    def _render_hint_bar(self) -> str:
        """Return state-specific hint text for the footer."""

        if self._state == "idle":
            if self.is_one_button_mode():
                return "Double listen / Hold back"
            return "A listen | B back"
        if self._state == "listening":
            if self._quick_command and self.is_one_button_mode():
                return "Speaking..."
            return "Listening..."
        if self._state == "thinking":
            return "Processing..."
        # reply
        if self._quick_command:
            return "Returning soon"
        if self.is_one_button_mode():
            return "Double ask again / Hold back"
        return "A ask again | B back"

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def on_select(self, data=None) -> None:
        """Start listening, or ask again from the reply state."""

        if self._capture_in_flight:
            return
        self._start_listening_cycle(async_capture=self.voice_service_factory is None)

    def on_back(self, data=None) -> None:
        """Cancel any in-flight capture and pop the screen."""

        self._cancel_listening_cycle()
        self._cancel_auto_return()
        self.request_route("back")

    def on_voice_command(self, data=None) -> None:
        """Parse and execute a deterministic local voice command."""

        transcript = self._extract_transcript(data)
        if not transcript:
            self._set_response("No Speech", "I did not catch a command.")
            return

        if self.context is not None:
            self.context.record_voice_transcript(transcript, mode="voice_commands")

        command = self._voice_service().match_command(transcript)
        if not command.is_command:
            self._speak_response(
                "Not Recognized",
                f"I heard '{transcript}' but that is not a voice command. Try: call mom, play music, or volume up.",
            )
            return

        if command.intent is VoiceCommandIntent.CALL_CONTACT:
            self._handle_call_command(command.contact_name)
            return
        if command.intent is VoiceCommandIntent.VOLUME_UP:
            self._handle_volume_change(+5)
            return
        if command.intent is VoiceCommandIntent.VOLUME_DOWN:
            self._handle_volume_change(-5)
            return
        if command.intent is VoiceCommandIntent.PLAY_MUSIC:
            self._handle_play_music_command()
            return
        if command.intent is VoiceCommandIntent.MUTE_MIC:
            self._apply_mic_state(muted=True)
            self._speak_response("Mic Muted", "Voice commands mic is muted.")
            return
        if command.intent is VoiceCommandIntent.UNMUTE_MIC:
            self._apply_mic_state(muted=False)
            self._speak_response("Mic Live", "Voice commands mic is live.")
            return
        if command.intent is VoiceCommandIntent.READ_SCREEN:
            self._speak_response("Screen Read", self._screen_summary())
            return

        self._set_response("Not Ready", "That command is recognized but not wired yet.")

    # ------------------------------------------------------------------
    # Voice service
    # ------------------------------------------------------------------

    def _voice_service(self) -> VoiceService:
        """Return the cached VoiceService, rebuilding only when settings change."""

        settings = self._voice_settings()
        if self.voice_service_factory is not None:
            return self.voice_service_factory(settings)
        if self._cached_voice_service is None or self._cached_voice_service.settings != settings:
            self._cached_voice_service = VoiceService(settings=settings)
        return self._cached_voice_service

    def _voice_settings(self) -> VoiceSettings:
        """Return the latest runtime voice settings."""

        if self.voice_settings_provider is not None:
            return self.voice_settings_provider()
        defaults = self._default_voice_settings()
        if self.context is not None:
            voice = self.context.voice
            return replace(
                defaults,
                commands_enabled=voice.commands_enabled,
                ai_requests_enabled=voice.ai_requests_enabled,
                screen_read_enabled=voice.screen_read_enabled,
                stt_enabled=voice.stt_enabled,
                tts_enabled=voice.tts_enabled,
                mic_muted=voice.mic_muted,
                output_volume=voice.output_volume,
            )
        return defaults

    def _default_voice_settings(self) -> VoiceSettings:
        """Return configured voice defaults when a screen-level provider is absent."""

        capture_device_id = None
        if self.config_manager is not None:
            capture_device_id = self.config_manager.get_capture_device_id()

        defaults = VoiceSettings(capture_device_id=capture_device_id)
        if self.config_manager is None:
            return defaults

        get_app_settings = getattr(self.config_manager, "get_app_settings", None)
        if not callable(get_app_settings):
            return defaults

        app_settings = get_app_settings()
        voice_cfg = getattr(app_settings, "voice", None)
        if voice_cfg is None:
            return defaults

        get_default_output_volume = getattr(self.config_manager, "get_default_output_volume", None)
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
            capture_device_id=capture_device_id,
            sample_rate_hz=voice_cfg.sample_rate_hz,
            record_seconds=voice_cfg.record_seconds,
            tts_rate_wpm=voice_cfg.tts_rate_wpm,
            tts_voice=voice_cfg.tts_voice,
        )

    # ------------------------------------------------------------------
    # Capture cycle
    # ------------------------------------------------------------------

    def _begin_listening_on_entry(self) -> None:
        """Auto-start one listen cycle when the screen first opens."""

        if self._auto_listen_started:
            return
        self._auto_listen_started = True
        self._start_listening_cycle(async_capture=True)

    def _start_listening_cycle(self, *, async_capture: bool) -> None:
        """Kick off one voice-command capture cycle."""

        if self._capture_in_flight:
            return
        if self.context is not None and not self.context.voice.commands_enabled:
            self._set_response("Voice Off", "Turn voice commands on in Setup first.")
            self._refresh_after_state_change()
            return
        if self.context is not None and self.context.voice.mic_muted:
            self._set_response("Mic Muted", "Unmute the microphone in Setup or by voice first.")
            self._refresh_after_state_change()
            return

        voice_service = self._voice_service()
        if self.context is not None:
            self.context.update_voice_backend_status(
                stt_available=voice_service.capture_available() and voice_service.stt_available(),
                tts_available=voice_service.tts_available(),
            )
        if not voice_service.capture_available():
            self._set_response(
                "Mic Unavailable", "Local recording is not ready on this device yet."
            )
            self._refresh_after_state_change()
            return
        if not voice_service.stt_available():
            self._set_response("Speech Offline", "The offline speech model is not installed yet.")
            self._refresh_after_state_change()
            return

        self._capture_in_flight = True
        self._set_state("listening", "Listening", "Speak now...")
        self._refresh_after_state_change()
        self._listen_generation += 1
        generation = self._listen_generation
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event

        if async_capture:
            threading.Thread(
                target=self._run_listening_cycle,
                args=(voice_service, generation, cancel_event),
                daemon=True,
                name="AskScreenCapture",
            ).start()
            return

        self._run_listening_cycle(voice_service, generation, cancel_event)

    def _run_listening_cycle(
        self,
        voice_service: VoiceService,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        """Record, transcribe, and apply one command cycle."""

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
            self._dispatch_listen_result("", capture_failed=True, generation=generation)
            return

        try:
            transcript = voice_service.transcribe(capture_result.audio_path)
        except Exception as exc:
            logger.warning("Voice command transcription failed: {}", exc)
            self._dispatch_listen_result("", capture_failed=True, generation=generation)
            return
        finally:
            capture_result.audio_path.unlink(missing_ok=True)

        if cancel_event.is_set():
            return

        self._dispatch_listen_result(
            transcript.text.strip(),
            capture_failed=False,
            generation=generation,
        )

    def _dispatch_listen_result(
        self,
        transcript: str,
        *,
        capture_failed: bool,
        generation: int,
    ) -> None:
        """Apply one listen result, marshalled onto the UI thread when possible."""

        def apply_result() -> None:
            if generation != self._listen_generation:
                return
            self._active_capture_cancel = None
            self._capture_in_flight = False
            navigated = False
            if capture_failed:
                self._set_response(
                    "Mic Unavailable", "The Pi microphone input is busy or unavailable."
                )
            elif transcript:
                self._set_state("thinking", "Thinking", "Just a moment...")
                self._refresh_after_state_change()
                self.on_voice_command({"transcript": transcript})
                navigated = self._apply_pending_navigation_request()
            else:
                self._set_response("No Speech", "I did not catch a command.")
            if navigated:
                return
            self._refresh_after_state_change()
            self._schedule_auto_return()

        scheduler = (
            getattr(self.screen_manager, "action_scheduler", None)
            if self.screen_manager is not None
            else None
        )
        if scheduler is not None:
            scheduler(apply_result)
            return
        apply_result()

    def _refresh_after_state_change(self) -> None:
        """Refresh the screen after updating the voice UI state."""

        if self.screen_manager is not None and self.screen_manager.get_current_screen() is self:
            self.screen_manager.refresh_current_screen()

    def _apply_pending_navigation_request(self) -> bool:
        """Apply any queued navigation immediately when Ask triggers it off-input-path."""

        if self.screen_manager is None:
            return False
        navigation_request = self.consume_navigation_request()
        if navigation_request is None:
            return False
        return self.screen_manager.apply_navigation_request(
            navigation_request,
            source_screen=self,
        )

    def _cancel_listening_cycle(self) -> None:
        """Invalidate the current listen cycle and request capture cancellation."""

        self._listen_generation += 1
        if self._active_capture_cancel is not None:
            self._active_capture_cancel.set()
            self._active_capture_cancel = None
        self._capture_in_flight = False

    # ------------------------------------------------------------------
    # PTT capture cycle
    # ------------------------------------------------------------------

    def _start_ptt_capture(self) -> None:
        """Begin open-ended recording that stops on PTT_RELEASE."""

        if self.context is not None and not self.context.voice.commands_enabled:
            self._set_response("Voice Off", "Turn voice commands on in Setup first.")
            self._refresh_after_state_change()
            self._schedule_auto_return()
            return
        if self.context is not None and self.context.voice.mic_muted:
            self._set_response("Mic Muted", "Unmute the microphone first.")
            self._refresh_after_state_change()
            self._schedule_auto_return()
            return

        voice_service = self._voice_service()
        if not voice_service.capture_available():
            self._set_response("Mic Unavailable", "Voice capture is not ready on this device.")
            self._refresh_after_state_change()
            self._schedule_auto_return()
            return
        if not voice_service.stt_available():
            self._set_response("Speech Offline", "The offline speech model is not installed yet.")
            self._refresh_after_state_change()
            self._schedule_auto_return()
            return

        self._capture_in_flight = True
        self._ptt_active = True
        self._set_state("listening", "Listening", "Speak now...")
        self._refresh_after_state_change()
        self._listen_generation += 1
        generation = self._listen_generation
        cancel_event = threading.Event()
        self._active_capture_cancel = cancel_event
        logger.info("PTT capture started (generation={})", generation)

        self._play_attention_tone()

        threading.Thread(
            target=self._run_ptt_listening_cycle,
            args=(voice_service, generation, cancel_event),
            daemon=True,
            name="AskPTTCapture",
        ).start()

    def _run_ptt_listening_cycle(
        self,
        voice_service: VoiceService,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        """Record until cancel_event is set (by PTT_RELEASE), then transcribe."""

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

        if generation != self._listen_generation:
            if capture_result.audio_path is not None:
                capture_result.audio_path.unlink(missing_ok=True)
            return

        if capture_result.audio_path is None:
            if not self._ptt_active:
                logger.info("PTT capture ended without audio; treating the release as no speech")
                self._dispatch_listen_result("", capture_failed=False, generation=generation)
            else:
                logger.warning("PTT capture ended without audio while hold was still active")
                self._dispatch_listen_result("", capture_failed=True, generation=generation)
            return

        # If PTT was released (not cancelled by back/exit), process the audio.
        if not self._ptt_active:
            logger.info("PTT release finalized capture; starting transcription (generation={})", generation)
            try:
                transcript = voice_service.transcribe(capture_result.audio_path)
            except Exception as exc:
                logger.warning("PTT transcription failed: {}", exc)
                self._dispatch_listen_result("", capture_failed=True, generation=generation)
                return
            finally:
                capture_result.audio_path.unlink(missing_ok=True)

            self._dispatch_listen_result(
                transcript.text.strip(), capture_failed=False, generation=generation,
            )
            logger.info(
                "PTT transcription complete (generation={}, transcript_chars={})",
                generation,
                len(transcript.text.strip()),
            )
        elif capture_result.audio_path is not None:
            capture_result.audio_path.unlink(missing_ok=True)

    def on_ptt_release(self, data=None) -> None:
        """Stop PTT recording when the button is released after a hold."""

        if self._ptt_active and self._active_capture_cancel is not None:
            self._ptt_active = False
            logger.info("PTT release received (generation={})", self._listen_generation)
            self._set_state("thinking", "Thinking", "Just a moment...")
            self._refresh_after_state_change()
            self._active_capture_cancel.set()

    # ------------------------------------------------------------------
    # Auto-return helpers
    # ------------------------------------------------------------------

    def _schedule_auto_return(self) -> None:
        """Pop back after 2 seconds in quick-command mode."""

        if not self._quick_command:
            return
        self._cancel_auto_return()
        self._auto_return_timer = threading.Timer(2.0, self._auto_pop)
        self._auto_return_timer.daemon = True
        self._auto_return_timer.start()

    def _auto_pop(self) -> None:
        """Return to the previous screen via the action scheduler."""

        self._auto_return_timer = None

        def apply_pop() -> None:
            self.request_route("back")
            self._apply_pending_navigation_request()

        scheduler = (
            getattr(self.screen_manager, "action_scheduler", None)
            if self.screen_manager is not None
            else None
        )
        if scheduler is not None:
            scheduler(apply_pop)
        else:
            apply_pop()

    def _cancel_auto_return(self) -> None:
        """Cancel any pending auto-return timer."""

        if self._auto_return_timer is not None:
            self._auto_return_timer.cancel()
            self._auto_return_timer = None

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _extract_transcript(self, data: object) -> str:
        """Return the transcript text from a voice-command event payload."""

        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            value = data.get("command") or data.get("transcript") or data.get("text")
            if isinstance(value, str):
                return value.strip()
        return ""

    def _handle_volume_change(self, delta: int) -> None:
        """Apply a local volume adjustment and announce the result."""

        current = None
        if delta > 0 and self.volume_up_action is not None:
            current = self.volume_up_action(abs(delta))
        elif delta < 0 and self.volume_down_action is not None:
            current = self.volume_down_action(abs(delta))
        elif self.context is not None:
            current = (
                self.context.volume_up(abs(delta))
                if delta > 0
                else self.context.volume_down(abs(delta))
            )

        self._sync_context_output_volume(current)
        if current is None and self.context is not None:
            current = self.context.voice.output_volume
        self._speak_response(
            "Volume", f"Volume is {current if current is not None else 'updated'}."
        )

    def _handle_play_music_command(self) -> None:
        """Start local music playback when the app provides a playback hook."""

        if self.play_music_action is None:
            self._set_response("Music Off", "Local music playback is not ready yet.")
            return
        if not self.play_music_action():
            self._set_response("Music Empty", "I could not find any local music to play.")
            return
        self._set_response("Playing", "Starting local music.")
        self.request_route("shuffle_started")

    def _handle_call_command(self, spoken_name: str) -> None:
        """Resolve a contact and place a call when the VoIP manager is available."""

        contact = self._find_contact(spoken_name)
        if contact is None:
            self._set_response("No Match", f"I could not find {spoken_name}.")
            return

        display_name = contact.display_name
        if self.context is not None:
            self.context.set_talk_contact(name=display_name, sip_address=contact.sip_address)

        if self.voip_manager is None:
            self._speak_response("Call Ready", f"I found {display_name}, but calling is not ready.")
            return

        self._speak_response("Calling", f"Calling {display_name}.")
        if self.voip_manager.make_call(contact.sip_address, contact_name=display_name):
            self.request_route("call_started")
            return

        self._speak_response("Call Failed", f"I could not call {display_name}.")

    def _find_contact(self, spoken_name: str) -> "Contact | None":
        """Return a contact matching the spoken name by child-facing label first."""

        if self.config_manager is None:
            return None

        normalized = self._normalize_label(spoken_name)
        if not normalized:
            return None

        for contact in self.config_manager.get_contacts():
            labels = self._contact_labels(contact)
            if normalized in labels:
                return contact
        return None

    @classmethod
    def _normalize_label(cls, value: str) -> str:
        """Normalize spoken and configured labels for alias matching."""

        return " ".join(value.strip().lower().split())

    @classmethod
    def _contact_labels(cls, contact: "Contact") -> set[str]:
        """Return exact and family-alias labels for a contact."""

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

    def _screen_summary(self) -> str:
        """Return the current screen summary for spoken playback."""

        if self.context is not None and self.context.voice.screen_read_enabled:
            return "You are on Ask. Say a direct command now."
        return "Screen read is off. Turn it on in Setup to auto-read screens."

    def _apply_mic_state(self, *, muted: bool) -> None:
        """Keep local voice mute state in sync with the live VoIP mute path when available."""

        if self.context is not None:
            self.context.set_mic_muted(muted)
        action = self.mute_action if muted else self.unmute_action
        if action is not None:
            try:
                action()
            except Exception as exc:
                logger.warning("Voice mic state update failed: {}", exc)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _speak_response(self, headline: str, body: str) -> None:
        """Update the UI response and forward it to the TTS boundary."""

        self._set_response(headline, body)
        if self.context is not None:
            self.context.record_voice_response(body)
        if not self._voice_service().speak(body):
            logger.debug("Voice response not spoken: {}", body)

    def _sync_context_output_volume(self, volume: int | None) -> None:
        """Refresh cached volume state after routing through the shared output path."""

        if volume is None or self.context is None:
            return
        self.context.playback.volume = volume
        self.context.voice.output_volume = volume

    # ------------------------------------------------------------------
    # Audio helpers
    # ------------------------------------------------------------------

    def _play_attention_tone(self) -> None:
        """Play a short Pi-side tone before recording a command."""

        beep_path: Path | None = None
        try:
            with NamedTemporaryFile(prefix="yoyopy-beep-", suffix=".wav", delete=False) as handle:
                beep_path = Path(handle.name)
            self._write_beep_wav(beep_path)
            self._output_player.play_wav(beep_path, timeout_seconds=2.0)
        except Exception:
            logger.debug("Voice attention tone unavailable")
        finally:
            if beep_path is not None:
                beep_path.unlink(missing_ok=True)

    @staticmethod
    def _write_beep_wav(path: Path) -> None:
        """Write a short attention beep WAV for local playback."""

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
