"""Unified Ask screen with voice-command logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.navigation.ask_rendering import AskScreenRenderingMixin
from yoyopy.ui.screens.navigation.ask_voice import AskScreenVoiceMixin
from yoyopy.voice import VoiceService, VoiceSettings
from yoyopy.voice.output import AlsaOutputPlayer

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager
    from yoyopy.ui.screens import ScreenView
    from yoyopy.voip import VoIPManager


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
        self._active_capture_cancel = None
        self._output_player = AlsaOutputPlayer()
        self._quick_command = False
        self._ptt_active = False
        self._auto_return_timer = None
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Reset to a ready state when entering the Ask screen."""

        super().enter()
        self._cancel_listening_cycle()
        self._auto_listen_started = False
        self._capture_in_flight = False

        self._state = "idle"
        self._headline = "Ask"
        self._body = "Ask me anything..."
        if self._quick_command:
            self._start_ptt_capture()
        else:
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

    def set_quick_command(self, enabled: bool) -> None:
        """Enable or disable quick-command mode for one-shot entry."""

        self._quick_command = enabled

    def wants_ptt_passthrough(self) -> bool:
        """Return True when Ask should receive raw PTT release events."""

        return self.is_one_button_mode() and self._quick_command
