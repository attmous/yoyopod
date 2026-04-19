"""Voice-note flow screen for the Talk experience."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional, cast

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.theme import (
    INK,
    SUCCESS,
    WARNING,
    draw_talk_action_button,
    draw_talk_page_dots,
    draw_talk_person_header,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)
from yoyopod.ui.screens.voip.lvgl.voice_note_view import LvglVoiceNoteView
from yoyopod.ui.screens.voip.voice_note_models import (
    VoiceNoteAction,
    VoiceNoteActions,
    VoiceNoteState,
    build_voice_note_actions,
    build_voice_note_state_provider,
)
from yoyopod.ui.screens.voip.voice_note_recording import VoiceNoteRecordingController
from yoyopod.ui.screens.voip.voice_note_viewmodel import VoiceNoteViewModel

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.voip.voice_note_recording import VoiceNoteRecordingResult

__all__ = [
    "VoiceNoteScreen",
    "VoiceNoteAction",
    "VoiceNoteActions",
    "VoiceNoteState",
    "build_voice_note_actions",
    "build_voice_note_state_provider",
]


class VoiceNoteScreen(Screen):
    """Kid-facing voice-note flow with real record, review, and send states."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        state_provider: Callable[[], VoiceNoteState] | None = None,
        actions: VoiceNoteActions | None = None,
    ) -> None:
        super().__init__(display, context, "VoiceNote")
        self._state_provider = state_provider or build_voice_note_state_provider(context=context)
        self._actions = actions or VoiceNoteActions()
        self._recording_controller = VoiceNoteRecordingController(self._actions)
        self._state = "ready"
        self._selected_action_index = 0
        self._lvgl_view: LvglVoiceNoteView | None = None

    def enter(self) -> None:
        """Reset the voice-note flow when opened."""

        super().enter()
        self._discard_terminal_draft_for_recipient()
        self._sync_state_from_provider(default_state="ready")
        self._selected_action_index = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL voice-note view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> LvglVoiceNoteView | None:
        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = cast(
            LvglVoiceNoteView | None,
            current_retained_view(cast(Any, self._lvgl_view), ui_backend),
        )
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglVoiceNoteView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def wants_ptt_passthrough(self) -> bool:
        """Return True when the single-button adapter should emit raw PTT hold events."""

        return self.is_one_button_mode() and self._state in {"ready", "recording"}

    def _view_model(self) -> VoiceNoteViewModel:
        """Build the pure voice-note view model for rendering."""

        return VoiceNoteViewModel(
            state=self.current_state(),
            flow_state=self._state,
            one_button_mode=self.is_one_button_mode(),
            selected_action_index=self._selected_action_index,
        )

    def recipient_name(self) -> str:
        """Return the selected recipient."""

        return self.current_state().recipient_name

    def recipient_address(self) -> str:
        """Return the selected recipient SIP address."""

        return self.current_state().recipient_address

    def recipient_monogram(self) -> str:
        """Return a compact label for the active recipient."""

        return talk_monogram(self.recipient_name())

    def current_state(self) -> VoiceNoteState:
        """Return the prepared voice-note state for the current render."""

        return self._state_provider()

    def _sync_state_from_provider(self, default_state: str = "ready") -> None:
        """Reflect the prepared voice-note state into the screen and shared context."""

        state = self.current_state()
        if state.send_state in {"", "idle"}:
            self._state = default_state
            if self.context is not None:
                self.context.update_active_voice_note(send_state="idle")
            return

        self._state = state.send_state or default_state
        if self.context is not None:
            self.context.update_active_voice_note(
                send_state=state.send_state,
                status_text=state.status_text,
                file_path=state.file_path,
                duration_ms=state.duration_ms,
            )
        if self._state not in {"review", "failed"}:
            self._selected_action_index = 0

    def _discard_terminal_draft_for_recipient(self) -> None:
        """Start fresh when reopening a terminal draft for the same recipient."""

        state = self.current_state()
        if state.send_state in {"sent", "failed"}:
            if self._actions.discard_active_draft is not None:
                self._actions.discard_active_draft()
            if self.context is not None:
                self.context.update_active_voice_note(send_state="idle")

    def _refresh_input_mode(self) -> None:
        """Rebind active input handlers when the voice-note interaction mode changes."""

        if self.screen_manager is None:
            return
        rebind = getattr(self.screen_manager, "rebind_current_screen_inputs", None)
        if callable(rebind):
            rebind()

    def actions(self) -> list[VoiceNoteAction]:
        """Return the selectable actions for the current voice-note state."""

        return self._view_model().actions()

    def current_actions_for_view(self) -> tuple[list[str], list[str], int]:
        """Return visible action rows for the current state."""

        return self._view_model().current_actions_for_view()

    def current_action_subtitles(self) -> list[str]:
        """Return subtitles for the current action list."""

        return self._view_model().current_action_subtitles()

    def current_action_icons(self) -> list[str]:
        """Return icon keys for the current action list."""

        return self._view_model().current_action_icons()

    def current_action_colors(self) -> list[tuple[int, int, int]]:
        """Return the Talk action colors for the current button row."""

        return self._view_model().current_action_colors()

    def current_action_color_kinds(self) -> list[int]:
        """Return native LVGL color kinds for the current action row."""

        return self._view_model().current_action_color_kinds()

    def current_primary_icon(self) -> str:
        """Return the large centered action icon for non-review states."""

        return self._view_model().current_primary_icon()

    def current_primary_color(self) -> tuple[int, int, int]:
        """Return the large centered action color for non-review states."""

        return self._view_model().current_primary_color()

    def current_primary_color_kind(self) -> int:
        """Return the native LVGL color kind for the centered action."""

        return self._view_model().current_primary_color_kind()

    def current_primary_status(self) -> tuple[str, tuple[int, int, int]]:
        """Return the main status label and color for non-review states."""

        return self._view_model().current_primary_status()

    def current_primary_status_kind(self) -> int:
        """Return the native LVGL color kind for the centered status label."""

        return self._view_model().current_primary_status_kind()

    def current_status_chip(self) -> tuple[str | None, int]:
        """Return the current state-chip label and style kind."""

        return self._view_model().current_status_chip()

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current voice-note state."""

        return self._view_model().current_view_model()

    def render(self) -> None:
        """Render the current voice-note flow state."""

        self._sync_state_from_provider(default_state=self._state)
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        view_model = self._view_model()
        title_text, _subtitle_text, footer_text, _icon_key = view_model.current_view_model()
        render_status_bar(self.display, self.context, show_time=True)
        bottom = draw_talk_person_header(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=self.display.STATUS_BAR_HEIGHT + 26,
            name=self.recipient_name(),
            label=self.recipient_monogram(),
        )

        items, _badges, selected_index = view_model.current_actions_for_view()
        if items:
            icons = view_model.current_action_icons()
            colors = view_model.current_action_colors()
            diameter = 56
            gap = 12
            center_y = bottom + 52
            row_width = (len(items) * diameter) + (max(0, len(items) - 1) * gap)
            start_center = ((self.display.WIDTH - row_width) // 2) + (diameter // 2)
            for row, _item_title in enumerate(items):
                draw_talk_action_button(
                    self.display,
                    center_x=start_center + (row * (diameter + gap)),
                    center_y=center_y,
                    button_size="small",
                    color=colors[row],
                    icon=icons[row],
                    filled=row == selected_index,
                    active=row == selected_index,
                )

            label = items[selected_index]
            label_width, label_height = self.display.get_text_size(label, 16)
            label_y = center_y + (diameter // 2) + 14
            self.display.text(
                label,
                (self.display.WIDTH - label_width) // 2,
                label_y,
                color=INK,
                font_size=16,
            )
            draw_talk_page_dots(
                self.display,
                center_x=self.display.WIDTH // 2,
                top=label_y + label_height + 14,
                total=len(items),
                current=selected_index,
                color=SUCCESS if self._state == "review" else WARNING,
            )
        else:
            center_y = bottom + 64
            draw_talk_action_button(
                self.display,
                center_x=self.display.WIDTH // 2,
                center_y=center_y,
                button_size="large",
                color=view_model.current_primary_color(),
                icon=view_model.current_primary_icon(),
                filled=False,
                active=True,
            )
            status_text, status_color = view_model.current_primary_status()
            draw_talk_status_chip(
                self.display,
                center_x=self.display.WIDTH // 2,
                top=center_y + 54,
                text=status_text,
                color=status_color,
            )

        render_footer(self.display, footer_text, mode="talk")
        self.display.update()

    def _selected_action(self) -> VoiceNoteAction | None:
        """Return the currently highlighted voice-note action."""

        actions = self.actions()
        if not actions:
            return None
        return actions[self._selected_action_index % len(actions)]

    def _close_to_talk_contact(self) -> None:
        """Clear terminal draft state and return to the selected contact."""

        if self._actions.discard_active_draft is not None:
            self._actions.discard_active_draft()
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
        self._state = "ready"
        self._selected_action_index = 0
        self.request_route("back")

    def _preview_active_voice_note(self) -> None:
        """Play the current draft locally before sending it."""

        if self.context is None or self._actions.preview_draft is None:
            return

        state = self.current_state()
        file_path = state.file_path
        if not file_path:
            return

        if self._actions.preview_draft(file_path):
            if self._actions.set_draft_status_text is not None:
                self._actions.set_draft_status_text("Playing preview")
            self.context.update_active_voice_note(
                send_state="review",
                status_text="Playing preview",
                file_path=file_path,
                duration_ms=state.duration_ms,
            )
            return

        if self._actions.set_draft_status_text is not None:
            self._actions.set_draft_status_text("Couldn't play note")
        self.context.update_active_voice_note(
            send_state="review",
            status_text="Couldn't play note",
            file_path=file_path,
            duration_ms=state.duration_ms,
        )

    def on_select(self, data: object | None = None) -> None:
        """Advance the voice-note flow."""

        if self._state == "ready":
            if self.is_one_button_mode():
                self.request_route("back")
                return
            self._start_recording()
            return
        if self._state == "recording":
            self._stop_recording()
            return
        if self._state == "review":
            selected_action = self._selected_action()
            if selected_action is None:
                return
            if selected_action.key == "send":
                self._send_active_voice_note()
                return
            if selected_action.key == "play":
                self._preview_active_voice_note()
                return
            self._discard_and_reset()
            return
        if self._state == "failed":
            selected_action = self._selected_action()
            if selected_action is None or selected_action.key == "retry":
                self._send_active_voice_note()
                return
            self._discard_and_reset()
            return
        if self._state == "sent":
            self._close_to_talk_contact()
            return
        if self._state == "sending":
            return
        self.request_route("back")

    def on_advance(self, data: object | None = None) -> None:
        """Cycle selectable actions in one-button mode."""

        actions = self.actions()
        if not actions:
            return
        self._selected_action_index = (self._selected_action_index + 1) % len(actions)

    def on_back(self, data: object | None = None) -> None:
        """Return to the previous Talk screen."""

        if self._state == "recording":
            self._cancel_recording()
            return
        if self._state == "sending":
            return
        if self._state in {"review", "failed", "sent"}:
            self._close_to_talk_contact()
            return
        self.request_route("back")

    def on_ptt_press(self, data: object | None = None) -> None:
        """Start recording once the raw hold threshold is crossed."""

        if not isinstance(data, dict) or data.get("stage") != "hold_started":
            return
        if self._state != "ready":
            return
        self._start_recording()

    def on_ptt_release(self, data: object | None = None) -> None:
        """Stop an active recording when the button is released."""

        if self._state != "recording":
            return
        if not isinstance(data, dict) or not data.get("hold_started", False):
            self._cancel_recording()
            return
        self._stop_recording()

    def _start_recording(self) -> None:
        """Start a new voice-note recording for the active recipient."""

        result = self._recording_controller.start_recording(
            recipient_address=self.recipient_address(),
            recipient_name=self.recipient_name(),
        )
        self._consume_recording_result(result, on_success=self._sync_state_from_provider)
        if result.next_state == "recording":
            self._refresh_input_mode()

    def _stop_recording(self) -> None:
        """Stop the active recording and move to review."""

        result = self._recording_controller.stop_recording()
        self._consume_recording_result(
            result,
            on_success=lambda default_state: self._sync_state_from_provider(
                default_state=default_state,
            ),
        )
        self._refresh_input_mode()

    def _cancel_recording(self) -> None:
        """Cancel the active recording and return to the ready state."""

        result = self._recording_controller.cancel_recording()
        self._consume_recording_result(
            result,
            on_success=lambda _default_state: self._mark_recording_idle(),
        )
        self._refresh_input_mode()

    def _discard_and_reset(self) -> None:
        """Discard the current draft and return to the ready state."""

        if self._actions.discard_active_draft is not None:
            self._actions.discard_active_draft()
        self._state = "ready"
        self._selected_action_index = 0
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
        self._refresh_input_mode()

    def _send_active_voice_note(self) -> None:
        """Send the recorded voice note through the VoIP manager."""

        if self._actions.send_active_draft is None:
            return
        if self._actions.send_active_draft():
            self._sync_state_from_provider(default_state="sending")
            self._state = "sending"
            return
        self._sync_state_from_provider(default_state="failed")
        self._state = "failed"

    def _consume_recording_result(
        self,
        result: VoiceNoteRecordingResult,
        on_success: Callable[[str], None],
    ) -> None:
        """Apply recording lifecycle transitions from the recording controller."""

        if result.next_state is None:
            return
        if result.next_state == "ready":
            self._mark_recording_idle()
            return
        if result.next_state == "failed":
            self._state = "failed"
            if self.context is not None and result.status_text is not None:
                self.context.update_active_voice_note(
                    send_state="failed",
                    status_text=result.status_text,
                )
            return

        if result.next_state in {"recording", "review", "sending", "sent"}:
            if result.next_state in {"recording", "review"}:
                self._selected_action_index = 0
            on_success(result.next_state)
            self._state = result.next_state

    def _mark_recording_idle(self) -> None:
        """Clear transient recording state."""

        self._state = "ready"
        self._selected_action_index = 0
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
