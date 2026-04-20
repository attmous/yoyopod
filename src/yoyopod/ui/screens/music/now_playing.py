"""Graffiti Buddy now-playing screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.music.lvgl import LvglNowPlayingView
from yoyopod.ui.screens.theme import (
    BACKGROUND,
    ERROR,
    INK,
    LISTEN,
    MUTED,
    MUTED_DIM,
    SURFACE_RAISED,
    draw_icon,
    mix,
    render_backdrop,
    render_footer,
    render_status_bar,
    rounded_panel,
    text_fit,
    wrap_text,
)

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.audio.music.backend import MusicBackend
    from yoyopod.ui.screens import ScreenView


@dataclass(frozen=True, slots=True)
class NowPlayingState:
    """Prepared playback state for the now-playing screen."""

    title: str
    artist: str
    progress: float
    state_label: str
    is_playing: bool


@dataclass(frozen=True, slots=True)
class NowPlayingActions:
    """Focused playback actions exposed to the now-playing screen."""

    toggle_playback: Callable[[], None] | None = None
    previous_track: Callable[[], None] | None = None
    next_track: Callable[[], None] | None = None


def build_now_playing_state_provider(
    *,
    context: "AppContext | None" = None,
    music_backend: "MusicBackend | None" = None,
) -> Callable[[], NowPlayingState]:
    """Build a narrow prepared-state provider for the now-playing screen."""

    def provider() -> NowPlayingState:
        if music_backend is not None:
            if not music_backend.is_connected:
                return NowPlayingState(
                    title="Music Offline",
                    artist="Trying to reconnect",
                    progress=0.0,
                    state_label="OFFLINE",
                    is_playing=False,
                )

            current_track = music_backend.get_current_track()
            playback_state = music_backend.get_playback_state()
            if current_track is not None:
                progress = 0.0
                if current_track.length > 0:
                    progress = music_backend.get_time_position() / current_track.length
                state_label = (
                    "PLAYING"
                    if playback_state == "playing"
                    else "PAUSED" if playback_state == "paused" else "READY"
                )
                return NowPlayingState(
                    title=current_track.name,
                    artist=current_track.get_artist_string() or "Unknown artist",
                    progress=progress,
                    state_label=state_label,
                    is_playing=playback_state == "playing",
                )

            return NowPlayingState(
                title="No Track Yet",
                artist="Pick local music to begin",
                progress=0.0,
                state_label="READY",
                is_playing=False,
            )

        track = context.get_current_track() if context is not None else None
        if track is None:
            return NowPlayingState(
                title="No Track Yet",
                artist="Pick local music to begin",
                progress=0.0,
                state_label="READY",
                is_playing=False,
            )

        return NowPlayingState(
            title=track.name,
            artist=track.get_artist_string(),
            progress=context.get_playback_progress() if context is not None else 0.0,
            state_label=(
                "PLAYING"
                if context is not None and context.media.playback.is_playing
                else "PAUSED"
            ),
            is_playing=bool(context is not None and context.media.playback.is_playing),
        )

    return provider


def build_now_playing_actions(
    *,
    context: "AppContext | None" = None,
    music_backend: "MusicBackend | None" = None,
) -> NowPlayingActions:
    """Build the focused playback actions for the now-playing screen."""

    def toggle_playback() -> None:
        if music_backend is not None:
            if not music_backend.is_connected:
                return
            if music_backend.get_playback_state() == "playing":
                music_backend.pause()
            else:
                music_backend.play()
            return
        if context is not None:
            context.toggle_playback()

    def previous_track() -> None:
        if music_backend is not None:
            if music_backend.is_connected:
                music_backend.previous_track()
            return
        if context is not None:
            context.previous_track()

    def next_track() -> None:
        if music_backend is not None:
            if music_backend.is_connected:
                music_backend.next_track()
            return
        if context is not None:
            context.next_track()

    return NowPlayingActions(
        toggle_playback=toggle_playback,
        previous_track=previous_track,
        next_track=next_track,
    )


class NowPlayingScreen(Screen):
    """Current playback screen styled for the new Listen mode."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        state_provider: Callable[[], NowPlayingState] | None = None,
        actions: NowPlayingActions | None = None,
    ) -> None:
        super().__init__(display, context, "NowPlaying")
        self._state_provider = state_provider or build_now_playing_state_provider(context=context)
        self._actions = actions or build_now_playing_actions(context=context)
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL now-playing view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if getattr(self.display, "backend_kind", "pil") != "lvgl":
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

        self._lvgl_view = LvglNowPlayingView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the now-playing view."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        state = self.current_state()
        state_text = self._display_state_text(state.state_label)
        footer = self.get_footer_text(is_playing=state.is_playing, state_label=state.state_label)
        visuals = self._state_visuals(state.state_label)

        render_backdrop(self.display, "listen")
        render_status_bar(self.display, self.context, show_time=True)

        halo_width = 92
        halo_height = 66
        halo_left = (self.display.WIDTH - halo_width) // 2
        halo_top = self.display.STATUS_BAR_HEIGHT + 16
        rounded_panel(
            self.display,
            halo_left,
            halo_top,
            halo_left + halo_width,
            halo_top + halo_height,
            fill=visuals["icon_fill"],
            outline=visuals["icon_outline"],
            radius=20,
        )
        draw_icon(
            self.display,
            "music_note",
            halo_left + 24,
            halo_top + 13,
            42,
            visuals["icon_color"],
        )

        title_y = halo_top + halo_height + 18
        title_lines = wrap_text(
            self.display,
            state.title,
            self.display.WIDTH - 32,
            18,
            max_lines=2,
        ) or [text_fit(self.display, state.title, self.display.WIDTH - 32, 18)]
        title_line_height = self.display.get_text_size("Ag", 18)[1]
        for index, line in enumerate(title_lines):
            title_width, _ = self.display.get_text_size(line, 18)
            self.display.text(
                line,
                (self.display.WIDTH - title_width) // 2,
                title_y + (index * title_line_height),
                color=INK,
                font_size=18,
            )

        title_bottom = title_y + (len(title_lines) * title_line_height)
        artist_y = title_bottom + 8
        artist_text = text_fit(self.display, state.artist, self.display.WIDTH - 36, 11)
        artist_width, _ = self.display.get_text_size(artist_text, 11)
        self.display.text(
            artist_text,
            (self.display.WIDTH - artist_width) // 2,
            artist_y,
            color=MUTED,
            font_size=11,
        )

        state_width, state_height = self.display.get_text_size(state_text, 10)
        chip_width = state_width + 26
        chip_left = (self.display.WIDTH - chip_width) // 2
        chip_top = artist_y + 22
        rounded_panel(
            self.display,
            chip_left,
            chip_top,
            chip_left + chip_width,
            chip_top + state_height + 10,
            fill=visuals["chip_fill"],
            outline=None,
            radius=12,
        )
        self.display.text(
            state_text,
            (self.display.WIDTH - state_width) // 2,
            chip_top + 4,
            color=visuals["chip_text"],
            font_size=10,
        )

        progress_width = 168
        progress_x = (self.display.WIDTH - progress_width) // 2
        progress_y = min(self.display.HEIGHT - 52, chip_top + state_height + 18)
        self.display.rectangle(
            progress_x,
            progress_y,
            progress_x + progress_width,
            progress_y + 8,
            fill=mix(BACKGROUND, SURFACE_RAISED, 0.5),
        )
        fill_width = max(0, min(progress_width, int(progress_width * state.progress)))
        if fill_width > 0:
            self.display.rectangle(
                progress_x,
                progress_y,
                progress_x + fill_width,
                progress_y + 8,
                fill=visuals["progress_fill"],
            )

        render_footer(self.display, footer, mode="listen")
        self.display.update()

    def get_footer_text(self, *, is_playing: bool, state_label: str | None = None) -> str:
        """Return the gesture hint for the active playback state."""

        if self.is_one_button_mode():
            if state_label in {"OFFLINE", "READY"}:
                return "Hold back"
            return "Tap skip / Double pause" if is_playing else "Tap skip / Double play"
        return "A play | B back | X/Y tracks"

    @staticmethod
    def _display_state_text(state_label: str) -> str:
        """Return the human-facing chip label for the current playback state."""

        return state_label.title()

    @staticmethod
    def _state_visuals(state_label: str) -> dict[str, tuple[int, int, int]]:
        """Return the compact now-playing palette for one playback state."""

        if state_label == "PAUSED":
            return {
                "icon_fill": mix(SURFACE_RAISED, BACKGROUND, 0.2),
                "icon_outline": mix(MUTED, BACKGROUND, 0.55),
                "icon_color": MUTED,
                "chip_fill": SURFACE_RAISED,
                "chip_text": MUTED,
                "progress_fill": MUTED_DIM,
            }
        if state_label == "OFFLINE":
            return {
                "icon_fill": mix(ERROR, BACKGROUND, 0.82),
                "icon_outline": mix(ERROR, BACKGROUND, 0.55),
                "icon_color": INK,
                "chip_fill": mix(ERROR, BACKGROUND, 0.78),
                "chip_text": ERROR,
                "progress_fill": MUTED_DIM,
            }
        return {
            "icon_fill": mix(LISTEN.accent, BACKGROUND, 0.82),
            "icon_outline": mix(LISTEN.accent, BACKGROUND, 0.58),
            "icon_color": LISTEN.accent,
            "chip_fill": LISTEN.accent_dim,
            "chip_text": LISTEN.accent,
            "progress_fill": LISTEN.accent,
        }

    def current_state(self) -> NowPlayingState:
        """Return the prepared playback state for the current render."""

        return self._state_provider()

    def _toggle_playback(self) -> None:
        """Toggle playback via the injected action seam."""

        if self._actions.toggle_playback is not None:
            self._actions.toggle_playback()

    def _previous_track(self) -> None:
        """Go to the previous track via the injected action seam."""

        if self._actions.previous_track is not None:
            self._actions.previous_track()

    def _next_track(self) -> None:
        """Go to the next track via the injected action seam."""

        if self._actions.next_track is not None:
            self._actions.next_track()

    def on_select(self, data: object | None = None) -> None:
        """Toggle play/pause."""
        self._toggle_playback()

    def on_play_pause(self, data: object | None = None) -> None:
        """Toggle play/pause from a dedicated action."""
        self._toggle_playback()

    def on_back(self, data: object | None = None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data: object | None = None) -> None:
        """Advance to the next track in one-button mode."""
        self._next_track()

    def on_up(self, data: object | None = None) -> None:
        """Go to the previous track."""
        self._previous_track()

    def on_prev_track(self, data: object | None = None) -> None:
        """Go to the previous track from a dedicated media action."""
        self._previous_track()

    def on_down(self, data: object | None = None) -> None:
        """Go to the next track."""
        self._next_track()

    def on_next_track(self, data: object | None = None) -> None:
        """Go to the next track from a dedicated media action."""
        self._next_track()
