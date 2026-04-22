"""PIL fallback view for the outgoing-call screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.ui.screens.theme import (
    INK,
    TALK,
    draw_talk_large_card,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)

if TYPE_CHECKING:
    from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen


def render_outgoing_call_pil(screen: "OutgoingCallScreen") -> None:
    """Render the outgoing-call screen through the PIL display path."""

    callee_name = screen.callee_name
    render_status_bar(screen.display, screen.context, show_time=True)
    card_top = screen.display.STATUS_BAR_HEIGHT + 42
    card_left = (screen.display.WIDTH - 112) // 2
    draw_talk_large_card(
        screen.display,
        left=card_left,
        top=card_top,
        size=112,
        color=TALK.accent,
        label=talk_monogram(callee_name or "Unknown"),
        outlined=True,
    )
    screen.ring_animation_frame += 1

    display_name = callee_name or "Unknown"
    if len(display_name) > 14:
        display_name = f"{display_name[:13]}..."
    name_width, name_height = screen.display.get_text_size(display_name, 20)
    title_y = card_top + 126
    screen.display.text(
        display_name,
        (screen.display.WIDTH - name_width) // 2,
        title_y,
        color=INK,
        font_size=20,
    )
    draw_talk_status_chip(
        screen.display,
        center_x=screen.display.WIDTH // 2,
        top=title_y + name_height + 10,
        text="CALLING...",
        color=TALK.accent,
    )

    footer = "Hold = Cancel" if screen.is_one_button_mode() else "B cancel"
    render_footer(screen.display, footer, mode="talk")
    screen.display.update()
