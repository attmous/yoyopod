"""Tangara-inspired local library menu for Listen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from yoyopod.integrations.music import LocalLibraryItem, LocalMusicService
from yoyopod.integrations.music import ShuffleAllCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.navigation.lvgl import LvglListenView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


class ListenScreen(Screen):
    """Local music landing screen for Playlists, Recent, and Shuffle."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        app: Any | None = None,
        music_service: Optional[LocalMusicService] = None,
    ) -> None:
        super().__init__(display, context, "Listen", app=app)
        self.music_service = music_service
        self.items: list[LocalLibraryItem] = []
        self.selected_index = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh the local library menu when entering Listen."""
        super().enter()
        self._load_items()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL Listen view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
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

        self._lvgl_view = LvglListenView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _load_items(self) -> None:
        """Load the fixed local-first Listen menu items."""
        music_service = self._resolve_music_service()
        if music_service is not None:
            self.items = music_service.menu_items()
        else:
            self.items = [
                LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
                LocalLibraryItem("recent", "Recent", "Played lately"),
                LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
            ]
        if self.items:
            self.selected_index = min(self.selected_index, len(self.items) - 1)
        else:
            self.selected_index = 0

    def render(self) -> None:
        """Render the local library menu."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("ListenScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    @staticmethod
    def item_icon_key(key: str) -> str:
        """Return the icon key used for each Listen landing row."""

        if key == "playlists":
            return "playlist"
        if key == "recent":
            return "music_note"
        return "listen"

    def on_select(self, data=None) -> None:
        """Open the selected local library action."""
        if not self.items:
            return

        selected = self.items[self.selected_index]
        if selected.key == "playlists":
            self.request_route("open_playlists")
            return
        if selected.key == "recent":
            self.request_route("open_recent")
            return
        if selected.key == "shuffle" and self._shuffle_all():
            self.request_route("shuffle_started")
            return

    def _resolve_music_service(self) -> LocalMusicService | None:
        """Resolve the local music service from the constructor or owning app."""

        if self.music_service is not None:
            return self.music_service
        if self.app is None:
            return None
        getter = getattr(self.app, "get_music_library", None)
        if callable(getter):
            resolved = getter()
            if isinstance(resolved, LocalMusicService):
                self.music_service = resolved
                return resolved
        fallback = getattr(self.app, "local_music_service", None)
        if isinstance(fallback, LocalMusicService):
            self.music_service = fallback
            return fallback
        return None

    def _shuffle_all(self) -> bool:
        """Start shuffle playback through services when the app seam is available."""

        if self.app is not None:
            services = getattr(self.app, "services", None)
            if services is not None and hasattr(services, "call"):
                try:
                    return bool(
                        services.call(
                            "music",
                            "shuffle_all",
                            ShuffleAllCommand(),
                        )
                    )
                except Exception:
                    return False
        music_service = self._resolve_music_service()
        if music_service is not None:
            if music_service.shuffle_all():
                return True
        return False

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Advance through the local music menu with wraparound."""
        if not self.items:
            return
        self.selected_index = (self.selected_index + 1) % len(self.items)

    def on_up(self, data=None) -> None:
        """Move selection up."""
        if not self.items:
            return
        self.selected_index = (self.selected_index - 1) % len(self.items)

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.on_advance()
