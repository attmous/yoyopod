"""PIL fallback view for the incoming-call screen."""

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
    from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen


def render_incoming_call_pil(screen: "IncomingCallScreen") -> None:
    """Render the incoming-call screen through the PIL display path."""

    render_status_bar(screen.display, screen.context, show_time=True)
    card_top = screen.display.STATUS_BAR_HEIGHT + 42
    card_left = (screen.display.WIDTH - 112) // 2
    caller_name = screen.current_caller_name()
    draw_talk_large_card(
        screen.display,
        left=card_left,
        top=card_top,
        size=112,
        color=TALK.accent,
        label=talk_monogram(caller_name),
    )
    screen.ring_animation_frame += 1

    display_name = caller_name
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
        text="INCOMING CALL",
        color=TALK.accent,
    )

    footer = (
        "Tap = Answer | Hold = Decline" if screen.is_one_button_mode() else "A answer | B reject"
    )
    render_footer(screen.display, footer, mode="talk")
    screen.display.update()
