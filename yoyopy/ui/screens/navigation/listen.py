"""Listen source browser for the Graffiti Buddy redesign."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import LISTEN, MUTED, SURFACE, audio_source_label, audio_source_subtitle, draw_empty_state, draw_list_item, render_footer, render_header, rounded_panel

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager


@dataclass(frozen=True, slots=True)
class ListenSource:
    """One configured source in the Listen browser."""

    key: str
    title: str
    subtitle: str


class ListenScreen(Screen):
    """Source chooser for the new Listen root mode."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        config_manager: Optional["ConfigManager"] = None,
    ) -> None:
        super().__init__(display, context, "Listen")
        self.config_manager = config_manager
        self.sources: list[ListenSource] = []
        self.selected_index = 0

    def enter(self) -> None:
        """Refresh configured sources when entering the screen."""
        super().enter()
        self._load_sources()

    def _load_sources(self) -> None:
        """Load configured music sources from the app config."""
        configured = ["local"]
        if self.config_manager is not None:
            configured = self.config_manager.get_listen_sources()

        normalized: list[str] = []
        for source in configured:
            source_key = source.strip().lower()
            if source_key and source_key not in normalized:
                normalized.append(source_key)

        self.sources = [
            ListenSource(
                key=source_key,
                title=audio_source_label(source_key),
                subtitle=audio_source_subtitle(source_key),
            )
            for source_key in normalized
        ]

        if self.context is not None and self.sources:
            current_key = getattr(self.context, "current_audio_source", self.sources[0].key)
            for index, source in enumerate(self.sources):
                if source.key == current_key:
                    self.selected_index = index
                    break

        if self.sources:
            self.selected_index = min(self.selected_index, len(self.sources) - 1)
        else:
            self.selected_index = 0

    def render(self) -> None:
        """Render the configured Listen sources."""
        position_text = None
        if self.sources:
            position_text = f"{self.selected_index + 1}/{len(self.sources)}"

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Listen",
            page_text=position_text,
            show_time=False,
            show_mode_chip=False,
        )

        if not self.sources:
            draw_empty_state(
                self.display,
                mode="listen",
                title="No sources",
                subtitle="Add music sources in config to fill this page.",
                icon="listen",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="listen")
            self.display.update()
            return

        panel_top = content_top + 4
        panel_bottom = self.display.HEIGHT - 26
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=22,
        )

        list_top = panel_top + 10
        item_height = 46
        for index, source in enumerate(self.sources):
            y1 = list_top + (index * item_height)
            y2 = y1 + 40
            if y2 > panel_bottom - 8:
                break

            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=source.title,
                subtitle="",
                mode="listen",
                selected=index == self.selected_index,
            )

        if len(self.sources) > 1:
            dots_y = panel_bottom - 12
            dots_width = 16 * len(self.sources)
            dots_x = (self.display.WIDTH - dots_width) // 2
            for index in range(len(self.sources)):
                color = LISTEN.accent if index == self.selected_index else MUTED
                self.display.circle(dots_x + (index * 16), dots_y, 3, fill=color)

        help_text = "Tap next / Open / Hold back" if self.is_one_button_mode() else "A open | B back | X/Y move"
        render_footer(self.display, help_text, mode="listen")
        self.display.update()

    def on_select(self, data=None) -> None:
        """Open the playlist flow for the selected source."""
        if not self.sources:
            return

        source = self.sources[self.selected_index]
        if self.context is not None:
            self.context.current_audio_source = source.key
        self.request_route("source_selected", payload=source.key)

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance through sources with wraparound."""
        if not self.sources:
            return
        self.selected_index = (self.selected_index + 1) % len(self.sources)

    def on_up(self, data=None) -> None:
        """Move selection up."""
        if not self.sources:
            return
        self.selected_index = (self.selected_index - 1) % len(self.sources)

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.on_advance()
