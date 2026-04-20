"""Unified Ask screen with voice-command logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from yoyopod.runtime.voice import (
    VoiceCommandExecutor,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.navigation.ask_rendering import AskScreenRenderingMixin
from yoyopod.ui.screens.navigation.ask_voice import AskScreenVoiceMixin
from yoyopod.voice import VoiceManager, VoiceSettings

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.config import ConfigManager
    from yoyopod.people import PeopleManager
    from yoyopod.ui.screens import ScreenView
    from yoyopod.communication import VoIPManager


class AskScreen(AskScreenVoiceMixin, AskScreenRenderingMixin, Screen):
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
        people_directory: Optional["PeopleManager"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        volume_up_action: Optional[Callable[[int], int | None]] = None,
        volume_down_action: Optional[Callable[[int], int | None]] = None,
        mute_action: Optional[Callable[[], bool]] = None,
        unmute_action: Optional[Callable[[], bool]] = None,
        play_music_action: Optional[Callable[[], bool]] = None,
        voice_settings_provider: Optional[Callable[[], VoiceSettings]] = None,
        voice_service_factory: Optional[Callable[[VoiceSettings], VoiceManager]] = None,
        voice_runtime: Optional["VoiceRuntimeCoordinator"] = None,
    ) -> None:
        super().__init__(display, context, "Ask")
        self.config_manager = config_manager
        self.voip_manager = voip_manager
        self.voice_runtime = voice_runtime or VoiceRuntimeCoordinator(
            context=context,
            settings_resolver=VoiceSettingsResolver(
                context=context,
                config_manager=config_manager,
                settings_provider=voice_settings_provider,
            ),
            command_executor=VoiceCommandExecutor(
                context=context,
                config_manager=config_manager,
                people_directory=people_directory,
                voip_manager=voip_manager,
                volume_up_action=volume_up_action,
                volume_down_action=volume_down_action,
                mute_action=mute_action,
                unmute_action=unmute_action,
                play_music_action=play_music_action,
                screen_summary_provider=self._screen_summary,
            ),
            voice_service_factory=voice_service_factory,
        )
        self._async_voice_capture = voice_runtime is not None or voice_service_factory is None
        self._state: str = "idle"
        self._headline: str = "Ask"
        self._body: str = "Ask me anything..."
        self._capture_in_flight = False
        self._listen_generation = 0
        self._quick_command = False
        self._ptt_active = False
        self._auto_return_timer = None
        self._lvgl_view: "ScreenView | None" = None
        self._bind_voice_runtime()

    def enter(self) -> None:
        """Reset to a ready state when entering the Ask screen."""

        super().enter()
        self._cancel_auto_return()
        self.voice_runtime.begin_entry_cycle(
            quick_command=self._quick_command,
            async_capture=self._async_voice_capture,
        )
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Invalidate any in-flight result before leaving the screen."""

        self.voice_runtime.cancel()
        self._cancel_auto_return()
        self._quick_command = False
        super().exit()

    def set_screen_manager(self, manager) -> None:
        """Bind screen-manager scheduling to the shared voice runtime."""

        super().set_screen_manager(manager)
        self._bind_voice_runtime()

    def set_quick_command(self, enabled: bool) -> None:
        """Enable or disable quick-command mode for one-shot entry."""

        self._quick_command = enabled

    def wants_ptt_passthrough(self) -> bool:
        """Return True when Ask should receive raw PTT release events."""

        return self.is_one_button_mode() and self._quick_command

    def _screen_summary(self) -> str:
        """Return the current screen summary for spoken playback."""

        if self.context is not None and self.context.voice.screen_read_enabled:
            return "You are on Ask. Say a direct command now."
        return "Screen read is off. Turn it on in Setup to auto-read screens."
