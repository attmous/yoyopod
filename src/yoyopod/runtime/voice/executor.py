"""Deterministic voice-command execution for runtime seam consumption."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.voice import VoiceCommandIntent
from yoyopod.voice.commands import match_voice_command

from .settings import VoiceCommandOutcome

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.config import ConfigManager
    from yoyopod.communication import VoIPManager
    from yoyopod.people import Contact
    from yoyopod.people import PeopleDirectory


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
        people_directory: "PeopleDirectory | None" = None,
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
        self._context.media.playback.volume = volume
        self._context.voice.output_volume = volume
