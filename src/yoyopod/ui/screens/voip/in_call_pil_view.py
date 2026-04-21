"""PIL fallback view for the in-call screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.ui.screens.theme import (
    ERROR,
    INK,
    SUCCESS,
    TALK,
    draw_talk_large_card,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)

if TYPE_CHECKING:
    from yoyopod.ui.screens.voip.in_call import InCallScreen


def render_in_call_pil(screen: "InCallScreen") -> None:
    """Render the active-call screen through the PIL display path."""

    caller_info = screen.current_caller_info()
    duration = screen.current_call_duration()
    is_muted = screen.is_call_muted()

    render_status_bar(screen.display, screen.context, show_time=True)
    caller_name = caller_info.get("display_name", "Unknown")
    card_top = screen.display.STATUS_BAR_HEIGHT + 42
    card_left = (screen.display.WIDTH - 112) // 2
    draw_talk_large_card(
        screen.display,
        left=card_left,
        top=card_top,
        size=112,
        color=TALK.accent,
        label=talk_monogram(caller_name),
    )
    name_width, name_height = screen.display.get_text_size(caller_name, 20)
    title_y = card_top + 126
    screen.display.text(
        caller_name,
        (screen.display.WIDTH - name_width) // 2,
        title_y,
        color=INK,
        font_size=20,
    )

    duration_text = screen.format_duration(duration)
    chip_bottom = draw_talk_status_chip(
        screen.display,
        center_x=screen.display.WIDTH // 2,
        top=title_y + name_height + 10,
        text=f"IN CALL | {duration_text}",
        color=SUCCESS,
    )

    if is_muted:
        draw_talk_status_chip(
            screen.display,
            center_x=screen.display.WIDTH // 2,
            top=chip_bottom + 8,
            text="MUTED",
            color=ERROR,
            icon="mic_off",
        )

    footer = (
        f"Tap = {'Unmute' if is_muted else 'Mute'} | Hold = End"
        if screen.is_one_button_mode()
        else f"X {'unmute' if is_muted else 'mute'} | B end call"
    )
    render_footer(screen.display, footer, mode="talk")
    screen.display.update()
