"""Direct tests for extracted PIL fallback screen views."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoyopod.audio.music import LocalLibraryItem
from yoyopod.ui.screens.music.now_playing import NowPlayingState
from yoyopod.ui.screens.music.now_playing_pil_view import render_now_playing_pil
from yoyopod.ui.screens.music.playlist_pil_view import render_playlist_pil
from yoyopod.ui.screens.music.recent_pil_view import render_recent_tracks_pil
from yoyopod.ui.screens.navigation.hub import HubCard
from yoyopod.ui.screens.navigation.hub_pil_view import render_hub_pil
from yoyopod.ui.screens.navigation.listen_pil_view import render_listen_pil
from yoyopod.ui.screens.voip.call_history_pil_view import render_call_history_pil
from yoyopod.ui.screens.voip.contact_list_pil_view import render_contact_list_pil
from yoyopod.ui.screens.voip.in_call_pil_view import render_in_call_pil
from yoyopod.ui.screens.voip.incoming_call_pil_view import render_incoming_call_pil
from yoyopod.ui.screens.voip.outgoing_call_pil_view import render_outgoing_call_pil
from yoyopod.ui.screens.voip.talk_contact_pil_view import render_talk_contact_pil
from yoyopod.ui.screens.voip.voice_note_pil_view import render_voice_note_pil


class RecordingDisplay:
    """Minimal display double that records drawn text."""

    WIDTH = 240
    HEIGHT = 280
    STATUS_BAR_HEIGHT = 28
    COLOR_BLACK = (0, 0, 0)

    def __init__(self) -> None:
        self.updated = False
        self.text_calls: list[str] = []

    def is_portrait(self) -> bool:
        return True

    def get_adapter(self) -> None:
        return None

    def clear(self, *args, **kwargs) -> None:
        pass

    def rectangle(self, *args, **kwargs) -> None:
        pass

    def circle(self, *args, **kwargs) -> None:
        pass

    def line(self, *args, **kwargs) -> None:
        pass

    def text(self, text: str, *args, **kwargs) -> None:
        self.text_calls.append(text)

    def update(self) -> None:
        self.updated = True

    def get_text_size(
        self,
        text: str,
        font_size: int = 16,
        size: int | None = None,
    ) -> tuple[int, int]:
        resolved_size = size if size is not None else font_size
        return (max(1, len(text)) * max(4, resolved_size // 2), resolved_size)


def _assert_rendered(display: RecordingDisplay, expected_text: str) -> None:
    assert display.updated
    assert any(expected_text in text for text in display.text_calls)


def _make_now_playing_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display

        def current_state(self) -> NowPlayingState:
            return NowPlayingState(
                title="Paper Planes",
                artist="M.I.A.",
                progress=0.5,
                state_label="PLAYING",
                is_playing=True,
            )

        def display_state_text(self, state_label: str) -> str:
            return state_label.title()

        def get_footer_text(self, *, is_playing: bool, state_label: str | None = None) -> str:
            return "A play | B back | X/Y tracks"

        def state_visuals(self, state_label: str) -> dict[str, tuple[int, int, int]]:
            return {
                "icon_fill": (20, 30, 40),
                "icon_outline": (50, 60, 70),
                "icon_color": (80, 90, 100),
                "chip_fill": (110, 120, 130),
                "chip_text": (140, 150, 160),
                "progress_fill": (170, 180, 190),
            }

    return ScreenStub()


def _make_playlist_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None
        loading = False
        error_message = None
        playlists = ["Road Trip"]

        def __init__(self) -> None:
            self.display = display

        def is_one_button_mode(self) -> bool:
            return False

        def get_footer_text(self) -> str:
            return "A load | B back | X/Y move"

        def get_visible_window(self) -> tuple[list[str], list[str], int]:
            return (["Road Trip"], ["12"], 0)

        def get_visible_subtitles(self) -> list[str]:
            return [""]

        def get_visible_icon_keys(self) -> list[str]:
            return ["playlist"]

    return ScreenStub()


def _make_recent_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None
        error_message = None
        tracks = ["Ocean Eyes"]

        def __init__(self) -> None:
            self.display = display

        def is_one_button_mode(self) -> bool:
            return False

        def get_footer_text(self) -> str:
            return "A play | B back | X/Y move"

        def get_visible_window(self) -> tuple[list[str], list[str], int]:
            return (["Ocean Eyes"], [""], 0)

        def get_visible_subtitles(self) -> list[str]:
            return ["Billie Eilish"]

        def get_visible_icon_keys(self) -> list[str]:
            return ["music_note"]

    return ScreenStub()


def _make_in_call_screen() -> object:
    display = RecordingDisplay()
    voip_manager = SimpleNamespace(
        get_caller_info=lambda: {"display_name": "Avery"},
        get_call_duration=lambda: 65,
        is_muted=True,
    )

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.voip_manager = voip_manager

        def is_one_button_mode(self) -> bool:
            return False

        def format_duration(self, seconds: int) -> str:
            return f"{seconds // 60:02d}:{seconds % 60:02d}"

        def current_caller_info(self) -> dict[str, object]:
            return dict(self.voip_manager.get_caller_info())

        def current_call_duration(self) -> int:
            return int(self.voip_manager.get_call_duration())

        def is_call_muted(self) -> bool:
            return bool(self.voip_manager.is_muted)

    return ScreenStub()


def _make_incoming_call_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.caller_name = "Harper"
            self.ring_animation_frame = 0

        def is_one_button_mode(self) -> bool:
            return False

        def current_caller_name(self) -> str:
            return self.caller_name

        def current_caller_address(self) -> str:
            return "sip:harper@test"

    return ScreenStub()


def _make_outgoing_call_screen() -> object:
    display = RecordingDisplay()
    voip_manager = SimpleNamespace(
        get_caller_info=lambda: {"display_name": "Theo", "address": "sip:theo@test"},
    )

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.voip_manager = voip_manager
            self.callee_name = "Theo"
            self.callee_address = "sip:theo@test"
            self.ring_animation_frame = 0

        def is_one_button_mode(self) -> bool:
            return False

        def current_callee_info(self) -> tuple[str, str]:
            caller_info = self.voip_manager.get_caller_info()
            return (
                str(caller_info.get("display_name", self.callee_name)),
                str(caller_info.get("address", self.callee_address)),
            )

    return ScreenStub()


def _make_contact_list_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.title_text = "More People"
            self.empty_title = "No contacts"
            self.empty_subtitle = "Add contacts to call them here."
            self.contacts = ["Mila"]

        def get_visible_window(self) -> tuple[list[str], list[str], int]:
            return (["Mila"], [""], 0)

        def get_visible_subtitles(self) -> list[str]:
            return [""]

        def get_visible_icon_keys(self) -> list[str]:
            return ["mono:MI"]

        def instruction_text(self) -> str:
            return "A open | B back | X/Y move"

    return ScreenStub()


def _make_voice_note_screen() -> object:
    display = RecordingDisplay()
    view_model = SimpleNamespace(
        current_view_model=lambda: (
            "Review",
            "Listen, send, or record again.",
            "Select choose / Back",
            "voice_note",
        ),
        current_actions_for_view=lambda: (["Send", "Play", "Again"], ["3s", "", ""], 0),
        current_action_icons=lambda: ["check", "play", "close"],
        current_action_colors=lambda: [(10, 20, 30), (40, 50, 60), (70, 80, 90)],
        current_primary_color=lambda: (100, 110, 120),
        current_primary_icon=lambda: "voice_note",
        current_primary_status=lambda: ("Recording", (130, 140, 150)),
    )

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display

        def view_model(self) -> object:
            return view_model

        def recipient_name(self) -> str:
            return "Zoe"

        def recipient_monogram(self) -> str:
            return "ZO"

        def page_dot_color(self) -> tuple[int, int, int]:
            return (160, 170, 180)

    return ScreenStub()


def _make_talk_contact_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.selected_index = 9

        def actions(self) -> list[str]:
            return ["Call", "Voice Note"]

        def get_visible_action_icons(self) -> list[str]:
            return ["call", "voice_note"]

        def action_button_size(self) -> str:
            return "medium"

        def current_contact_name(self) -> str:
            return "Owen"

        def current_contact_monogram(self) -> str:
            return "OW"

        def get_visible_actions(self) -> tuple[list[str], list[str], int]:
            return (["Call", "Voice Note"], ["Start a voice call", "Record a short message"], 9)

        def footer_text(self) -> str:
            return "Tap Next | 2x Select | Hold Back"

    return ScreenStub()


def _make_call_history_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.entries = ["Grandma"]

        def get_visible_window(self) -> tuple[list[str], list[str], int]:
            return (["Grandma"], [""], 0)

        def get_visible_subtitles(self) -> list[str]:
            return ["Yesterday"]

        def get_visible_icon_keys(self) -> list[str]:
            return ["talk"]

        def instruction_text(self) -> str:
            return "A call | B back | X/Y move"

    return ScreenStub()


def _make_hub_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.selected_index = 0

        def cards(self) -> list[HubCard]:
            return [
                HubCard("Listen", "On-device music", "listen", "listen"),
                HubCard("Talk", "Calls ready", "talk", "talk"),
            ]

        def tile_glow_color(self, mode: str) -> tuple[int, int, int]:
            return (10, 20, 30)

        def tile_fill_color(self, mode: str) -> tuple[int, int, int]:
            return (40, 50, 60)

    return ScreenStub()


def _make_listen_screen() -> object:
    display = RecordingDisplay()

    class ScreenStub:
        context = None

        def __init__(self) -> None:
            self.display = display
            self.selected_index = 0
            self.items = [
                LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
                LocalLibraryItem("recent", "Recent", "Played lately"),
            ]

        def is_one_button_mode(self) -> bool:
            return False

        def item_icon_key(self, key: str) -> str:
            return "playlist" if key == "playlists" else "music_note"

    return ScreenStub()


@pytest.mark.parametrize(
    ("render_fn", "screen_factory", "expected_text"),
    [
        (render_now_playing_pil, _make_now_playing_screen, "Paper Planes"),
        (render_playlist_pil, _make_playlist_screen, "Road Trip"),
        (render_recent_tracks_pil, _make_recent_screen, "Ocean Eyes"),
        (render_in_call_pil, _make_in_call_screen, "Avery"),
        (render_incoming_call_pil, _make_incoming_call_screen, "Harper"),
        (render_outgoing_call_pil, _make_outgoing_call_screen, "Theo"),
        (render_contact_list_pil, _make_contact_list_screen, "Mila"),
        (render_voice_note_pil, _make_voice_note_screen, "Send"),
        (render_talk_contact_pil, _make_talk_contact_screen, "Voice Note"),
        (render_call_history_pil, _make_call_history_screen, "Grandma"),
        (render_hub_pil, _make_hub_screen, "Listen"),
        (render_listen_pil, _make_listen_screen, "Playlists"),
    ],
)
def test_extracted_pil_views_render_with_public_screen_surface(
    render_fn,
    screen_factory,
    expected_text: str,
) -> None:
    """Each PIL view should render directly from a narrow public screen surface."""

    screen = screen_factory()
    render_fn(screen)

    _assert_rendered(screen.display, expected_text)
