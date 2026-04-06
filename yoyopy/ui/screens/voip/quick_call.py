"""People-first Talk home screen for YoyoPod."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    INK,
    MUTED,
    SURFACE,
    TALK,
    draw_empty_state,
    draw_icon,
    mix,
    render_backdrop,
    render_footer,
    render_status_bar,
    rounded_panel,
    text_fit,
)
from yoyopy.ui.screens.voip.lvgl import LvglCallView

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager, Contact
    from yoyopy.ui.screens import ScreenView
    from yoyopy.voip import CallHistoryStore, VoIPManager


@dataclass(slots=True)
class TalkPerson:
    """One kid-facing contact card in the Talk deck."""

    title: str
    source_name: str
    sip_address: str
    subtitle: str = "Call or voice note"


class CallScreen(Screen):
    """Talk screen showing one person at a time."""

    _MAX_CONTACTS = 10

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        config_manager: Optional["ConfigManager"] = None,
        call_history_store: Optional["CallHistoryStore"] = None,
    ) -> None:
        super().__init__(display, context, "Talk")
        self.voip_manager = voip_manager
        self.config_manager = config_manager
        self.call_history_store = call_history_store
        self.people: list[TalkPerson] = []
        self.selected_index = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh the contact deck when Talk becomes active."""

        super().enter()
        self._load_people()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving Talk."""

        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _sorted_contacts(self) -> list["Contact"]:
        """Return contacts ordered for child-facing Talk access."""

        if self.config_manager is None:
            return []

        contacts = list(self.config_manager.get_contacts())
        favorites = [contact for contact in contacts if contact.favorite]
        others = [contact for contact in contacts if not contact.favorite]
        return (favorites + others)[: self._MAX_CONTACTS]

    def _load_people(self) -> None:
        """Load the Talk deck from configured contacts."""

        contacts = self._sorted_contacts()
        self.people = [
            TalkPerson(
                title=contact.display_name,
                source_name=contact.name,
                sip_address=contact.sip_address,
            )
            for contact in contacts
        ]

        if not self.people:
            self.selected_index = 0
            return

        preferred_address = ""
        if self.context is not None:
            preferred_address = self.context.talk_contact_address

        if preferred_address:
            for index, person in enumerate(self.people):
                if person.sip_address == preferred_address:
                    self.selected_index = index
                    break

        self.selected_index = min(self.selected_index, len(self.people) - 1)

    def _selected_person(self) -> TalkPerson | None:
        """Return the currently selected contact card."""

        if not self.people:
            return None
        return self.people[self.selected_index]

    def current_card_model(self) -> tuple[str, str, int, int]:
        """Return the active Talk card content for both PIL and LVGL paths."""

        selected_person = self._selected_person()
        if selected_person is None:
            return ("", "", 0, 0)
        subtitle = selected_person.subtitle
        if self.context is not None:
            latest_note = self.context.latest_voice_note_by_contact.get(selected_person.sip_address, {})
            if latest_note.get("unread"):
                subtitle = "New voice note"
            elif latest_note.get("direction") == "outgoing" and latest_note.get("delivery_state") in {"sent", "delivered"}:
                subtitle = "Latest note sent"
            elif latest_note.get("local_file_path"):
                subtitle = "Play latest note"
        return (
            selected_person.title,
            subtitle,
            self.selected_index,
            len(self.people),
        )

    def render(self) -> None:
        """Render the Talk contact deck."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        theme = render_backdrop(self.display, "talk")
        render_status_bar(self.display, self.context, show_time=False)

        if not self.people:
            draw_empty_state(
                self.display,
                mode="talk",
                title="No people yet",
                subtitle="Add contacts to start calling or sending notes.",
                icon="talk",
                top=self.display.STATUS_BAR_HEIGHT + 18,
            )
            render_footer(self.display, "Hold back", mode="talk")
            self.display.update()
            return

        title_text, subtitle_text, selected_index, total_people = self.current_card_model()
        card_left = 16
        card_top = self.display.STATUS_BAR_HEIGHT + 24
        card_right = self.display.WIDTH - 16
        card_bottom = self.display.HEIGHT - 30
        rounded_panel(
            self.display,
            card_left,
            card_top,
            card_right,
            card_bottom,
            fill=mix(TALK.accent, SURFACE, 0.9),
            outline=TALK.accent_dim,
            radius=28,
            shadow=True,
        )

        draw_icon(self.display, "talk", (self.display.WIDTH // 2) - 30, card_top + 24, 60, theme.accent)

        fitted_title = text_fit(self.display, title_text, self.display.WIDTH - 50, 28)
        title_width, title_height = self.display.get_text_size(fitted_title, 28)
        title_y = card_top + 106
        self.display.text(
            fitted_title,
            (self.display.WIDTH - title_width) // 2,
            title_y,
            color=theme.accent,
            font_size=28,
        )

        fitted_subtitle = text_fit(self.display, subtitle_text, self.display.WIDTH - 54, 13)
        subtitle_width, _ = self.display.get_text_size(fitted_subtitle, 13)
        self.display.text(
            fitted_subtitle,
            (self.display.WIDTH - subtitle_width) // 2,
            title_y + title_height + 10,
            color=INK if not self._show_missed_calls() else MUTED,
            font_size=13,
        )

        if self._show_missed_calls():
            badge = self._missed_calls_badge()
            badge_width, _ = self.display.get_text_size(badge, 11)
            rounded_panel(
                self.display,
                (self.display.WIDTH - badge_width - 18) // 2,
                title_y + title_height + 32,
                (self.display.WIDTH + badge_width + 18) // 2,
                title_y + title_height + 54,
                fill=TALK.accent_dim,
                outline=None,
                radius=11,
            )
            self.display.text(
                badge,
                (self.display.WIDTH - badge_width) // 2,
                title_y + title_height + 38,
                color=INK,
                font_size=11,
            )

        dots_y = card_bottom - 18
        dots_width = max(1, total_people) * 14
        dots_x = (self.display.WIDTH - dots_width) // 2
        for index in range(total_people):
            dot_color = theme.accent if index == selected_index else TALK.accent_dim
            radius = 4 if index == selected_index else 3
            self.display.circle(dots_x + (index * 14), dots_y, radius, fill=dot_color)

        render_footer(self.display, "Tap next / Double open", mode="talk")
        self.display.update()

    def _show_missed_calls(self) -> bool:
        """Return True when a missed-call badge should be shown on the deck."""

        return bool(self.context is not None and getattr(self.context, "missed_calls", 0) > 0)

    def _missed_calls_badge(self) -> str:
        """Return the compact missed-call badge copy."""

        missed_calls = 0 if self.context is None else int(getattr(self.context, "missed_calls", 0))
        label = "missed call" if missed_calls == 1 else "missed calls"
        return f"{missed_calls} {label}"

    def on_select(self, data=None) -> None:
        """Open the selected contact's action menu."""

        selected_person = self._selected_person()
        if selected_person is None:
            return

        if self.context is not None:
            self.context.set_talk_contact(
                name=selected_person.title,
                sip_address=selected_person.sip_address,
            )
        self.request_route("open_contact")

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""

        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move through contacts with wraparound."""

        if not self.people:
            return
        self.selected_index = (self.selected_index + 1) % len(self.people)
