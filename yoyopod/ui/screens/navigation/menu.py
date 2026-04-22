"""Graffiti Buddy standard-device menu."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.theme import (
    MUTED,
    draw_icon,
    draw_list_item,
    render_footer,
    render_header,
    rounded_panel,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext


ITEM_MODES = {
    "Listen": ("listen", "listen", "Music and playlists"),
    "Talk": ("talk", "talk", "Calls and voice notes"),
    "Ask": ("ask", "ask", "Future safe AI mode"),
    "Setup": ("setup", "setup", "Power and device care"),
}


class MenuScreen(Screen):
    """Standard multi-button menu matching the new root IA."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        items: Optional[List[str]] = None,
        selected_index: int = 0,
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "Menu", app=app)
        self.items = items or ["Listen", "Talk", "Ask", "Setup"]
        self.selected_index = selected_index

    def render(self) -> None:
        """Render the standard menu with the new branded list treatment."""
        selected_item = self.get_selected()
        selected_mode, selected_icon, _ = ITEM_MODES.get(
            selected_item, ("setup", "setup", "Browse the device")
        )
        content_top = render_header(
            self.display,
            self.context,
            mode=selected_mode,
            title="YoyoPod",
            subtitle="Pick a mode for this adventure.",
            icon=selected_icon,
            show_time=False,
        )

        panel_top = content_top + 4
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=(30, 34, 41),
            outline=None,
            radius=24,
        )

        item_height = 54
        row_top = panel_top + 10
        row_bottom = panel_bottom - 8
        # Compute how many rows can fit and scroll so the selected row is visible.
        max_visible = (row_bottom - row_top - 44) // item_height + 1
        max_visible = max(1, min(len(self.items), max_visible))
        start_index = max(
            0, min(self.selected_index - (max_visible // 2), len(self.items) - max_visible)
        )

        for offset in range(max_visible):
            index = start_index + offset
            item = self.items[index]
            y1 = row_top + (offset * item_height)
            y2 = y1 + 44

            mode, icon, subtitle = ITEM_MODES.get(item, ("setup", "setup", "Mode"))
            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=item,
                subtitle=subtitle,
                mode=mode,
                selected=index == self.selected_index,
            )
            draw_icon(
                self.display,
                icon,
                self.display.WIDTH - 58,
                y1 + 7,
                24,
                MUTED if index != self.selected_index else (245, 247, 250),
            )

        render_footer(self.display, "A open | B back | X/Y move", mode=selected_mode)
        self.display.update()

    def select_next(self) -> None:
        """Move selection to the next item."""
        self.selected_index = (self.selected_index + 1) % len(self.items)
        logger.debug(f"Selected: {self.items[self.selected_index]}")

    def select_previous(self) -> None:
        """Move selection to the previous item."""
        self.selected_index = (self.selected_index - 1) % len(self.items)
        logger.debug(f"Selected: {self.items[self.selected_index]}")

    def get_selected(self) -> str:
        """Get the selected menu item."""
        return self.items[self.selected_index]

    def on_select(self, data=None) -> None:
        """Open the selected mode."""
        self.request_route("select", payload=self.get_selected())

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
