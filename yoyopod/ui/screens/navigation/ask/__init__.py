"""Unified Ask screen with voice-command logic."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable, Optional

from yoyopod.integrations.voice import (
    VoiceCommandOutcome,
    VoiceCommandExecutor,
    VoiceRuntimeCoordinator,
    VoiceSettingsResolver,
)
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.navigation.lvgl import LvglAskView
from yoyopod.ui.screens.theme import (
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
from yoyopod.integrations.voice import VoiceManager, VoiceSettings

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.core import VoiceInteractionState
    from yoyopod.config import ConfigManager
    from yoyopod.integrations.call import VoIPManager
    from yoyopod.integrations.contacts.directory import PeopleManager
    from yoyopod.ui.screens.view import ScreenView


class AskScreen(Screen):
    """Unified stateful Ask screen with idle / listening / thinking / reply states."""

    _FAMILY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
        ("mom", "mama", "mum", "mommy", "mother"),
        ("dad", "dada", "daddy", "papa", "father"),
    )
    _HINT_TEXT = (
        "Ask a question. Use the quick button for calls, music, volume, and screen reading."
    )

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        app: Any | None = None,
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
        super().__init__(display, context, "Ask", app=app)
        resolved_config_manager = config_manager or getattr(app, "config_manager", None)
        resolved_people_directory = people_directory
        if resolved_people_directory is None:
            integrations = getattr(app, "integrations", None)
            contacts_integration = (
                integrations.get("contacts") if hasattr(integrations, "get") else None
            )
            resolved_people_directory = getattr(contacts_integration, "directory", None)
        if resolved_people_directory is None:
            resolved_people_directory = getattr(app, "people_directory", None)

        resolved_voip_manager = voip_manager or getattr(app, "voip_manager", None)
        audio_volume_controller = getattr(app, "audio_volume_controller", None)
        resolved_volume_up_action = volume_up_action
        if resolved_volume_up_action is None:
            resolved_volume_up_action = getattr(
                audio_volume_controller,
                "volume_level_up",
                None,
            ) or getattr(audio_volume_controller, "volume_up", None)
        resolved_volume_down_action = volume_down_action
        if resolved_volume_down_action is None:
            resolved_volume_down_action = getattr(
                audio_volume_controller,
                "volume_level_down",
                None,
            ) or getattr(audio_volume_controller, "volume_down", None)
        resolved_mute_action = mute_action or getattr(resolved_voip_manager, "mute", None)
        resolved_unmute_action = unmute_action or getattr(resolved_voip_manager, "unmute", None)
        local_music_service = getattr(app, "local_music_service", None)
        resolved_play_music_action = play_music_action or getattr(
            local_music_service,
            "shuffle_all",
            None,
        )
        resolved_voice_runtime = voice_runtime or getattr(app, "voice_runtime", None)

        self.config_manager = resolved_config_manager
        self.voip_manager = resolved_voip_manager
        self.voice_runtime = resolved_voice_runtime or VoiceRuntimeCoordinator(
            context=context,
            settings_resolver=VoiceSettingsResolver(
                context=context,
                config_manager=resolved_config_manager,
                settings_provider=voice_settings_provider,
            ),
            command_executor=VoiceCommandExecutor(
                context=context,
                config_manager=resolved_config_manager,
                people_directory=resolved_people_directory,
                voip_manager=resolved_voip_manager,
                volume_up_action=resolved_volume_up_action,
                volume_down_action=resolved_volume_down_action,
                mute_action=resolved_mute_action,
                unmute_action=resolved_unmute_action,
                play_music_action=resolved_play_music_action,
                screen_summary_provider=self._screen_summary,
            ),
            voice_service_factory=voice_service_factory,
        )
        self._async_voice_capture = (
            resolved_voice_runtime is not None or voice_service_factory is None
        )
        self._state: str = "idle"
        self._headline: str = "Ask"
        self._body: str = "Ask me anything..."
        self._capture_in_flight = False
        self._listen_generation = 0
        self._quick_command = False
        self._ptt_active = False
        self._auto_return_timer = None
        self._auto_return_token = 0
        self._lvgl_view: "ScreenView | None" = None
        self._entry_cycle_token = 0
        self._bind_voice_runtime()

    def enter(self) -> None:
        """Reset to a ready state when entering the Ask screen."""

        super().enter()
        self._cancel_auto_return()
        self._ensure_lvgl_view()
        self._schedule_entry_cycle()

    def exit(self) -> None:
        """Invalidate any in-flight result before leaving the screen."""

        self._entry_cycle_token += 1
        self.voice_runtime.cancel()
        self.voice_runtime.reset_conversation()
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

        if self._quick_command:
            return "You are on quick Ask. Say a direct command now."
        return "You are on Ask. Ask a question, or go back to exit."

    def on_select(self, data=None) -> None:
        """Start listening, or ask again from the reply state."""

        if self._quick_command:
            self.voice_runtime.begin_listening(async_capture=self._async_voice_capture)
            return
        self.voice_runtime.begin_ask(async_capture=self._async_voice_capture)

    def on_back(self, data=None) -> None:
        """Cancel any in-flight capture and pop the screen."""

        self.voice_runtime.cancel()
        self._cancel_auto_return()
        self.request_route("back")

    def on_voice_command(self, data=None) -> None:
        """Execute a supplied transcript through the shared runtime seam."""

        transcript = self._extract_transcript(data)
        self.voice_runtime.handle_transcript(transcript)

    def on_ptt_release(self, data=None) -> None:
        """Stop PTT recording when the button is released after a hold."""

        self.voice_runtime.finish_ptt_capture()

    def _bind_voice_runtime(self) -> None:
        """Bind screen-local consumers to the shared voice runtime."""

        dispatcher = None
        if self.screen_manager is not None:
            dispatcher = getattr(self.screen_manager, "action_scheduler", None)
        self.voice_runtime.bind(
            state_listener=self._on_voice_runtime_state_changed,
            outcome_listener=self._on_voice_runtime_outcome,
            dispatcher=dispatcher,
        )
        self._on_voice_runtime_state_changed(self.voice_runtime.state)

    def _schedule_entry_cycle(self) -> None:
        """Defer the default Ask entry cycle off the navigation hot path when possible."""

        self._entry_cycle_token += 1
        token = self._entry_cycle_token

        def start_entry_cycle() -> None:
            if token != self._entry_cycle_token:
                return
            if (
                self.screen_manager is not None
                and getattr(self.screen_manager, "current_screen", None) is not self
            ):
                return
            self.voice_runtime.begin_entry_cycle(
                quick_command=self._quick_command,
                async_capture=self._async_voice_capture,
            )

        scheduler = getattr(self.app, "scheduler", None)
        if scheduler is not None and hasattr(scheduler, "post"):
            scheduler.post(start_entry_cycle)
            return
        start_entry_cycle()

    def _on_voice_runtime_state_changed(self, state: "VoiceInteractionState") -> None:
        """Mirror shared voice runtime state into Ask presentation fields."""

        self._state = state.phase
        self._headline = state.headline
        self._body = state.body
        self._capture_in_flight = state.capture_in_flight
        self._ptt_active = state.ptt_active
        self._listen_generation = state.generation
        self._refresh_after_state_change()

    def _on_voice_runtime_outcome(self, outcome: VoiceCommandOutcome) -> None:
        """Handle navigation side effects emitted by the shared voice runtime."""

        navigated = False
        if outcome.route_name is not None:
            self.request_route(outcome.route_name)
            navigated = self._apply_pending_navigation_request()
        if not navigated and outcome.auto_return:
            self._schedule_auto_return()

    def _voice_service(self) -> "VoiceManager":
        """Return the effective voice service from the shared runtime."""

        return self.voice_runtime._voice_service()

    def _voice_settings(self) -> "VoiceSettings":
        """Return the resolved voice settings from the shared runtime."""

        return self.voice_runtime.settings()

    def _default_voice_settings(self) -> "VoiceSettings":
        """Return the config-derived default voice settings."""

        return self.voice_runtime.defaults()

    def _dispatch_listen_result(
        self,
        transcript: str,
        *,
        capture_failed: bool,
        generation: int,
    ) -> None:
        """Forward a listen result through the shared runtime dispatcher."""

        self.voice_runtime.state.generation = self._listen_generation
        self.voice_runtime.dispatch_listen_result(
            transcript,
            capture_failed=capture_failed,
            generation=generation,
        )

    def _run_ptt_listening_cycle(
        self,
        voice_service: "VoiceManager",
        generation: int,
        cancel_event,
    ) -> None:
        """Delegate the PTT listening cycle to the shared runtime."""

        self.voice_runtime.state.generation = self._listen_generation
        self.voice_runtime.state.ptt_active = self._ptt_active
        self.voice_runtime.state.capture_in_flight = self._capture_in_flight
        self.voice_runtime._run_ptt_listening_cycle(voice_service, generation, cancel_event)

    def _extract_transcript(self, data: object) -> str:
        """Return the transcript text from a voice-command event payload."""

        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            value = data.get("command") or data.get("transcript") or data.get("text")
            if isinstance(value, str):
                return value.strip()
        return ""

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

        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglAskView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current Ask state."""

        icon_key = "ask"
        if self._headline in {"Mic Muted", "Mic Unavailable", "Voice Off"}:
            icon_key = "mic_off"
        return (self._headline, self._body, self._render_hint_bar(), icon_key)

    def render(self) -> None:
        """Render the current Ask state."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("AskScreen requires an initialized LVGL backend")
        lvgl_view.sync()

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

        circle_size = 112
        circle_radius = circle_size // 2
        cx = (self.display.WIDTH - circle_size) // 2
        cy = content_top + 12
        circle_fill = self._icon_circle_fill()

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

        icon_size = 56
        icon_x = cx + (circle_size - icon_size) // 2
        icon_y = cy + (circle_size - icon_size) // 2
        draw_icon(self.display, "ask", icon_x, icon_y, icon_size, ASK.accent)

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

        subtitle_color = MUTED_DIM if self._state == "thinking" else ASK.accent
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
        if self._quick_command:
            return "Returning soon"
        if self.is_one_button_mode():
            return "Double ask again / Hold back"
        return "A ask again | B back"

    def _refresh_after_state_change(self) -> None:
        """Refresh the screen after updating the voice UI state."""

        if self.screen_manager is None:
            return
        get_current_screen = getattr(self.screen_manager, "get_current_screen", None)
        refresh_current_screen = getattr(self.screen_manager, "refresh_current_screen", None)
        if callable(get_current_screen) and callable(refresh_current_screen):
            if get_current_screen() is self:
                refresh_current_screen()

    def _icon_circle_fill(self) -> tuple[int, int, int]:
        """Return the blended icon halo color for the current state."""

        if self._state == "listening":
            return (95, 86, 48)
        return (74, 69, 45)

    def _schedule_auto_return(self) -> None:
        """Pop back after 2 seconds in quick-command mode."""

        if not self._quick_command:
            return
        self._cancel_auto_return()
        self._auto_return_token += 1
        token = self._auto_return_token
        self._auto_return_timer = threading.Timer(2.0, lambda: self._auto_pop(token))
        self._auto_return_timer.daemon = True
        self._auto_return_timer.start()

    def _auto_pop(self, token: int | None = None) -> None:
        """Return to the previous screen via the action scheduler."""

        self._auto_return_timer = None
        if token is not None and token != self._auto_return_token:
            return
        if not self._quick_command:
            return

        current_screen = None
        if self.screen_manager is not None:
            get_current_screen = getattr(self.screen_manager, "get_current_screen", None)
            if callable(get_current_screen):
                current_screen = get_current_screen()
            else:
                current_screen = getattr(self.screen_manager, "current_screen", None)
        if self.screen_manager is not None and current_screen is not self:
            return

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

        self._auto_return_token += 1
        if self._auto_return_timer is not None:
            self._auto_return_timer.cancel()
            self._auto_return_timer = None

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
