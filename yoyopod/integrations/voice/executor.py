"""Deterministic voice-command execution for coordinator seam consumption."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.integrations.voice import VoiceCommandIntent, VoiceCommandMatch, match_voice_command

from yoyopod.integrations.voice.settings import VoiceCommandOutcome

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod_cli.config import ConfigManager
    from yoyopod.integrations.call import VoIPManager
    from yoyopod.integrations.contacts.directory import PeopleManager
    from yoyopod.integrations.contacts.models import Contact

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_CALL_HINT_TOKENS = frozenset({"call", "dial", "phone", "ring"})
_CONFIRM_YES_TOKENS = frozenset({"yes", "yeah", "yep", "yup", "sure", "ok", "okay"})
_CONFIRM_NO_TOKENS = frozenset(
    {"no", "nope", "nah", "cancel", "stop", "dont", "don't", "not", "never"}
)
_NEGATION_TOKENS = frozenset(
    {"no", "not", "never", "dont", "don't", "cant", "can't", "cannot", "wont", "won't"}
)


@dataclass(slots=True, frozen=True)
class _PendingCallConfirmation:
    spoken_name: str
    display_name: str


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
        people_directory: "PeopleManager | None" = None,
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
        self._people_directory = people_directory
        self._voip_manager = voip_manager
        self._volume_up_action = volume_up_action
        self._volume_down_action = volume_down_action
        self._mute_action = mute_action
        self._unmute_action = unmute_action
        self._play_music_action = play_music_action
        self._screen_summary_provider = screen_summary_provider or self._default_screen_summary
        self._pending_call_confirmation: _PendingCallConfirmation | None = None

    def execute(
        self,
        transcript: str,
        *,
        command: VoiceCommandMatch | None = None,
    ) -> VoiceCommandOutcome:
        """Parse and execute one local deterministic voice command."""

        normalized = transcript.strip()
        if not normalized:
            return VoiceCommandOutcome(
                "No Speech", "I did not catch a command.", should_speak=False
            )

        if self._context is not None:
            self._context.record_voice_transcript(normalized, mode="voice_commands")

        pending_outcome = self._resolve_pending_confirmation(normalized)
        if pending_outcome is not None:
            return pending_outcome

        if command is None:
            command = match_voice_command(normalized)
        if not command.is_command:
            inferred_call = self._infer_call_confirmation(normalized)
            if inferred_call is not None:
                self._pending_call_confirmation = inferred_call
                return VoiceCommandOutcome(
                    "Confirm Call",
                    f"Did you want to call {inferred_call.display_name}? Say yes or no.",
                    auto_return=False,
                )
            logger.info(
                "Voice command not recognized transcript={}",
                _preview_voice_text(normalized),
            )
            return VoiceCommandOutcome(
                "Not Recognized",
                "I heard "
                f"'{normalized}'"
                " but that is not a voice command. Try: call mom, play music, or volume up.",
            )
        logger.info(
            "Voice command matched intent={} transcript={} contact={}",
            command.intent.value,
            _preview_voice_text(normalized),
            command.contact_name or "",
        )

        if command.intent is VoiceCommandIntent.CALL_CONTACT:
            self._pending_call_confirmation = None
            return self._handle_call_command(command.contact_name)
        if command.intent is VoiceCommandIntent.VOLUME_UP:
            self._pending_call_confirmation = None
            return self._handle_volume_change(+1)
        if command.intent is VoiceCommandIntent.VOLUME_DOWN:
            self._pending_call_confirmation = None
            return self._handle_volume_change(-1)
        if command.intent is VoiceCommandIntent.PLAY_MUSIC:
            self._pending_call_confirmation = None
            return self._handle_play_music_command()
        if command.intent is VoiceCommandIntent.MUTE_MIC:
            self._pending_call_confirmation = None
            self._apply_mic_state(muted=True)
            return VoiceCommandOutcome("Mic Muted", "Voice commands mic is muted.")
        if command.intent is VoiceCommandIntent.UNMUTE_MIC:
            self._pending_call_confirmation = None
            self._apply_mic_state(muted=False)
            return VoiceCommandOutcome("Mic Live", "Voice commands mic is live.")
        if command.intent is VoiceCommandIntent.READ_SCREEN:
            self._pending_call_confirmation = None
            return VoiceCommandOutcome("Screen Read", self._screen_read_summary())

        return VoiceCommandOutcome("Not Ready", "That command is recognized but not wired yet.")

    def _handle_volume_change(self, delta: int) -> VoiceCommandOutcome:
        current = None
        if delta > 0 and self._volume_up_action is not None:
            current = self._volume_up_action(abs(delta))
        elif delta < 0 and self._volume_down_action is not None:
            current = self._volume_down_action(abs(delta))
        elif self._context is not None:
            if delta > 0:
                current = self._context.volume_level_up(abs(delta))
            else:
                current = self._context.volume_level_down(abs(delta))

        self._sync_context_output_volume(current)
        if current is None and self._context is not None:
            current = self._context.voice.output_volume
        return VoiceCommandOutcome(
            "Volume",
            self._format_volume_feedback(current),
        )

    def _handle_play_music_command(self) -> VoiceCommandOutcome:
        if self._play_music_action is None:
            return VoiceCommandOutcome("Music Off", "Local music playback is not ready yet.")
        if not self._play_music_action():
            return VoiceCommandOutcome("Music Empty", "I could not find any local music to play.")
        return VoiceCommandOutcome(
            "Playing",
            "Starting local music.",
            should_speak=False,
            route_name="shuffle_started",
        )

    def _handle_call_command(self, spoken_name: str) -> VoiceCommandOutcome:
        contact = self._find_contact(spoken_name)
        if contact is None:
            return VoiceCommandOutcome("No Match", f"I could not find {spoken_name}.")

        route, address = contact.preferred_call_target(gsm_enabled=False)
        if route != "sip" or not address:
            return VoiceCommandOutcome(
                "Not Ready",
                f"{contact.display_name} is saved, but this device can only place SIP calls right now.",
            )

        display_name = contact.display_name
        if self._context is not None:
            self._context.set_talk_contact(name=display_name, sip_address=address)

        if self._voip_manager is None:
            return VoiceCommandOutcome(
                "Call Ready",
                f"I found {display_name}, but calling is not ready.",
            )

        if self._voip_manager.make_call(address, contact_name=display_name):
            return VoiceCommandOutcome(
                "Calling",
                f"Calling {display_name}.",
                auto_return=False,
            )

        return VoiceCommandOutcome("Call Failed", f"I could not call {display_name}.")

    def _find_contact(self, spoken_name: str) -> "Contact | None":
        if self._people_directory is None:
            return None

        normalized = self._normalize_label(spoken_name)
        if not normalized:
            return None

        for contact in self._people_directory.get_contacts():
            if normalized in self._contact_labels(contact):
                return contact
        return None

    def _infer_call_confirmation(self, transcript: str) -> _PendingCallConfirmation | None:
        """Infer likely call intent when words are out of grammar order."""

        if self._people_directory is None:
            return None

        tokens = _voice_tokens(transcript)
        if not tokens or not any(token in _CALL_HINT_TOKENS for token in tokens):
            return None
        if any(token in _NEGATION_TOKENS for token in tokens):
            return None

        for contact in self._people_directory.get_contacts():
            for label in sorted(self._contact_labels(contact), key=len, reverse=True):
                label_tokens = _voice_tokens(label)
                if label_tokens and all(token in tokens for token in label_tokens):
                    return _PendingCallConfirmation(
                        spoken_name=label,
                        display_name=contact.display_name,
                    )
        return None

    def _resolve_pending_confirmation(self, transcript: str) -> VoiceCommandOutcome | None:
        pending = self._pending_call_confirmation
        if pending is None:
            return None

        tokens = set(_voice_tokens(transcript))
        if tokens & _CONFIRM_YES_TOKENS:
            self._pending_call_confirmation = None
            return self._handle_call_command(pending.spoken_name)
        if tokens & _CONFIRM_NO_TOKENS:
            self._pending_call_confirmation = None
            return VoiceCommandOutcome(
                "Cancelled",
                f"Okay, I will not call {pending.display_name}.",
            )

        self._pending_call_confirmation = None
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
            *{cls._normalize_label(alias) for alias in getattr(contact, "aliases", [])},
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

    def _screen_read_summary(self) -> str:
        if self._context is not None and not self._context.voice.screen_read_enabled:
            return "Screen read is off. Turn it on in Setup to auto-read screens."
        return self._screen_summary_provider()

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
        self._context.media.playback.volume = volume
        self._context.voice.output_volume = volume

    def _format_volume_feedback(self, volume: int | None) -> str:
        if volume is None:
            return "Volume updated."
        if self._context is not None:
            level = self._context.output_volume_level(volume)
        else:
            level = max(0, min(10, int(round(max(0, min(100, int(volume))) / 10))))
        return f"Volume is {level} out of 10."


def _preview_voice_text(text: str, *, limit: int = 96) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return repr(normalized)
    return repr(normalized[: limit - 3] + "...")


def _voice_tokens(text: str) -> tuple[str, ...]:
    """Return normalized tokens for lightweight command confirmation."""

    return tuple(_TOKEN_RE.findall(text.strip().lower()))
