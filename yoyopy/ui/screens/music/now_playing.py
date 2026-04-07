"""Graffiti Buddy now-playing screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.music.lvgl import LvglNowPlayingView
from yoyopy.ui.screens.theme import INK, LISTEN, MUTED, SURFACE, draw_icon, render_footer, render_header, rounded_panel, text_fit, wrap_text

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView


class NowPlayingScreen(Screen):
    """Current playback screen styled for the new Listen mode."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        music_backend=None,
        mopidy_client=None,
    ) -> None:
        super().__init__(display, context, "NowPlaying")
        self.music_backend = music_backend or mopidy_client
        self.mopidy_client = self.music_backend
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving now playing."""
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

        self._lvgl_view = LvglNowPlayingView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the now-playing view."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        track_title, artist, progress, state_label, is_playing = self._track_snapshot()

        content_top = render_header(
            self.display,
            self.context,
            mode="listen",
            title="Now Playing",
            show_time=False,
            show_mode_chip=False,
        )

        panel_top = content_top + 8
        panel_bottom = self.display.HEIGHT - 30
        rounded_panel(
            self.display,
            14,
            panel_top,
            self.display.WIDTH - 14,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=26,
            shadow=True,
        )

        draw_icon(self.display, "listen", (self.display.WIDTH // 2) - 22, panel_top + 14, 44, LISTEN.accent)

        state_width, _ = self.display.get_text_size(state_label, 10)
        rounded_panel(
            self.display,
            (self.display.WIDTH - state_width - 22) // 2,
            panel_top + 64,
            (self.display.WIDTH + state_width + 22) // 2,
            panel_top + 86,
            fill=LISTEN.accent_dim,
            outline=None,
            radius=12,
        )
        self.display.text(state_label, (self.display.WIDTH - state_width) // 2, panel_top + 70, color=LISTEN.accent, font_size=10)

        title_y = panel_top + 102
        title_lines = wrap_text(
            self.display,
            track_title,
            self.display.WIDTH - 64,
            18,
            max_lines=2,
        ) or [text_fit(self.display, track_title, self.display.WIDTH - 64, 18)]
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

        artist_y = title_y + (len(title_lines) * title_line_height) + 4
        artist_text = text_fit(self.display, artist, self.display.WIDTH - 64, 11)
        artist_width, _ = self.display.get_text_size(artist_text, 11)
        self.display.text(artist_text, (self.display.WIDTH - artist_width) // 2, artist_y, color=MUTED, font_size=11)

        progress_x = 28
        progress_y = panel_bottom - 40
        progress_width = self.display.WIDTH - 56
        self.display.rectangle(progress_x, progress_y, progress_x + progress_width, progress_y + 8, fill=(22, 25, 32))
        fill_width = max(0, min(progress_width, int(progress_width * progress)))
        if fill_width > 0:
            self.display.rectangle(progress_x, progress_y, progress_x + fill_width, progress_y + 8, fill=LISTEN.accent)

        hint = self.get_footer_text(is_playing=is_playing)
        render_footer(self.display, hint, mode="listen")
        self.display.update()

    def get_footer_text(self, *, is_playing: bool) -> str:
        """Return the gesture hint for the active playback state."""

        if self.is_one_button_mode():
            return "Tap skip / Double pause" if is_playing else "Tap skip / Double play"
        return "A play | B back | X/Y tracks"

    def _track_snapshot(self) -> tuple[str, str, float, str, bool]:
        """Return current track, artist, progress and state label."""
        if self.music_backend:
            if not self.music_backend.is_connected:
                return ("Music Offline", "Trying to reconnect", 0.0, "OFFLINE", False)

            current_track = self.music_backend.get_current_track()
            playback_state = self.music_backend.get_playback_state()
            if current_track:
                progress = 0.0
                if current_track.length > 0:
                    progress = self.music_backend.get_time_position() / current_track.length
                state_label = (
                    "PLAYING"
                    if playback_state == "playing"
                    else "PAUSED" if playback_state == "paused" else "READY"
                )
                return (
                    current_track.name,
                    current_track.get_artist_string() or "Unknown artist",
                    progress,
                    state_label,
                    playback_state == "playing",
                )

            return ("No Track Yet", "Pick local music to begin", 0.0, "READY", False)

        track = self.context.get_current_track() if self.context else None
        if track is None:
            return ("No Track Yet", "Pick local music to begin", 0.0, "READY", False)

        return (
            track.title,
            track.artist,
            self.context.get_playback_progress() if self.context else 0.0,
            "PLAYING" if self.context and self.context.playback.is_playing else "PAUSED",
            bool(self.context and self.context.playback.is_playing),
        )

    def _toggle_playback(self) -> None:
        """Toggle playback via Mopidy or the local app context."""
        if self.music_backend:
            if not self.music_backend.is_connected:
                return
            state = self.music_backend.get_playback_state()
            if state == "playing":
                self.music_backend.pause()
            else:
                self.music_backend.play()
            return

        if self.context:
            self.context.toggle_playback()

    def _previous_track(self) -> None:
        """Go to the previous track."""
        if self.music_backend:
            if self.music_backend.is_connected:
                self.music_backend.previous_track()
            return
        if self.context:
            self.context.previous_track()

    def _next_track(self) -> None:
        """Go to the next track."""
        if self.music_backend:
            if self.music_backend.is_connected:
                self.music_backend.next_track()
            return
        if self.context:
            self.context.next_track()

    def on_select(self, data=None) -> None:
        """Toggle play/pause."""
        self._toggle_playback()

    def on_play_pause(self, data=None) -> None:
        """Toggle play/pause from a dedicated action."""
        self._toggle_playback()

    def on_back(self, data=None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance to the next track in one-button mode."""
        self._next_track()

    def on_up(self, data=None) -> None:
        """Go to the previous track."""
        self._previous_track()

    def on_prev_track(self, data=None) -> None:
        """Go to the previous track from a dedicated media action."""
        self._previous_track()

    def on_down(self, data=None) -> None:
        """Go to the next track."""
        self._next_track()

    def on_next_track(self, data=None) -> None:
        """Go to the next track from a dedicated media action."""
        self._next_track()
