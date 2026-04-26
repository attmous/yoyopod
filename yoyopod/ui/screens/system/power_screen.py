"""Setup screen renderer and interaction handling for power and care settings."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.system.lvgl import LvglPowerView
from yoyopod.ui.screens.system.power_rows import (
    PowerPage,
    _build_battery_rows,
    _build_runtime_rows,
    _build_voice_rows,
    _row_capacity_for_page,
)
from yoyopod.ui.screens.system.power_viewmodel import (
    _VOICE_PAGE_SIGNATURE_FIELDS,
    PowerScreenActions,
    PowerScreenState,
    build_power_screen_actions,
    build_power_screen_state_provider,
)
from yoyopod.ui.screens.theme import (
    INK,
    MUTED,
    SETUP,
    SURFACE_RAISED,
    draw_icon,
    render_footer,
    render_backdrop,
    render_status_bar,
    rounded_panel,
    text_fit,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.integrations.power.models import PowerSnapshot
    from yoyopod.ui.screens.view import ScreenView


@dataclass(frozen=True, slots=True)
class PowerScreenLvglPayload:
    """Pure LVGL payload derived from the current Setup controller state."""

    title_text: str
    page_text: str | None
    icon_key: str
    footer: str
    items: tuple[str, ...]
    current_page_index: int
    total_pages: int


class PowerScreen(Screen):
    """Compact Setup screen for power and device care state."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        app: Any | None = None,
        state_provider: Callable[[], PowerScreenState] | None = None,
        actions: PowerScreenActions | None = None,
    ) -> None:
        super().__init__(display, context, "PowerStatus", app=app)
        power_manager = getattr(app, "power_manager", None)
        network_manager = getattr(app, "network_manager", None)
        audio_device_catalog = getattr(app, "audio_device_catalog", None)
        config_manager = getattr(app, "config_manager", None)
        audio_volume_controller = getattr(app, "audio_volume_controller", None)
        voip_manager = getattr(app, "voip_manager", None)
        status_provider_from_app = getattr(app, "get_status", None)
        self._state_provider = (
            state_provider
            if state_provider is not None
            else build_power_screen_state_provider(
                power_manager=power_manager,
                network_manager=network_manager,
                status_provider=(
                    status_provider_from_app if callable(status_provider_from_app) else None
                ),
                playback_device_options_provider=getattr(
                    audio_device_catalog,
                    "playback_devices",
                    None,
                ),
                capture_device_options_provider=getattr(
                    audio_device_catalog,
                    "capture_devices",
                    None,
                ),
            )
        )
        self._actions = actions or build_power_screen_actions(
            network_manager=network_manager,
            refresh_voice_device_options_action=getattr(
                audio_device_catalog,
                "refresh_async",
                None,
            ),
            persist_speaker_device_action=getattr(
                config_manager,
                "set_voice_speaker_device_id",
                None,
            ),
            persist_capture_device_action=getattr(
                config_manager,
                "set_voice_capture_device_id",
                None,
            ),
            volume_up_action=getattr(audio_volume_controller, "volume_up", None),
            volume_down_action=getattr(audio_volume_controller, "volume_down", None),
            mute_action=getattr(voip_manager, "mute", None),
            unmute_action=getattr(voip_manager, "unmute", None),
        )
        self.page_index = 0
        self.selected_row = 0
        self.in_detail = False
        self._lvgl_view: "ScreenView | None" = None
        self._last_gps_query_at = 0.0
        self._gps_refresh_interval_seconds = 5.0
        self._gps_page_refresh_delay_seconds = 1.0
        self._gps_page_entered_at: float | None = None
        self._visible_tick_refresh_grace_seconds = 0.5
        self._last_prepared_refresh_at = 0.0
        self._prepared_state: PowerScreenState | None = None
        self._cached_pages: list[PowerPage] | None = None
        self._cached_pages_signature: tuple[object, ...] | None = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self.page_index = 0
        self.selected_row = 0
        self.in_detail = False
        if self._actions.refresh_voice_devices is not None:
            self._actions.refresh_voice_devices()
        self.refresh_prepared_state()
        self._sync_page_visibility_state()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL Setup view alive across transitions."""
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

        self._lvgl_view = LvglPowerView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the active Setup page."""
        lvgl_view = self._ensure_lvgl_view()
        pages = self._prepared_pages()
        if not pages:
            return
        active_page_index = self._page_index_for(pages)
        active_page = pages[active_page_index]
        if lvgl_view is not None:
            lvgl_view.sync()
            return
        raise RuntimeError("PowerScreen requires an initialized LVGL backend")

    def _page_icon_key(self, title: str) -> str:
        if title == "Power":
            return "battery"
        if title == "Time":
            return "clock"
        if title == "Voice":
            return "voice_note"
        if title == "Network":
            return "signal"
        if title == "GPS":
            return "care"
        return "care"

    @staticmethod
    def _page_subtitle(title: str) -> str:
        if title == "Power":
            return "Battery and charging"
        if title == "Network":
            return "Cellular status"
        if title == "GPS":
            return "Location fix"
        if title == "Time":
            return "RTC and alarms"
        if title == "Care":
            return "Screen and watchdog"
        if title == "Voice":
            return "Commands and audio"
        return ""

    def _page_index_for(self, pages: list[PowerPage]) -> int:
        if not pages:
            return 0
        return self.page_index % len(pages)

    @staticmethod
    def _selected_row_for_page(page: PowerPage, selected_row: int) -> int:
        if not page.rows:
            return 0
        return selected_row % len(page.rows)

    def _visible_picker_pages(
        self,
        pages: list[PowerPage],
        *,
        max_items: int,
        current_page_index: int | None = None,
    ) -> list[tuple[int, PowerPage]]:
        if not pages:
            return []

        max_items = max(1, min(max_items, len(pages)))
        active_page_index = (
            self._page_index_for(pages) if current_page_index is None else current_page_index
        )
        start_index = max(
            0,
            min(active_page_index - (max_items // 2), len(pages) - max_items),
        )
        return [(start_index + offset, pages[start_index + offset]) for offset in range(max_items)]

    def _visible_rows_for_page(
        self,
        page: PowerPage,
        *,
        max_rows: int | None = None,
    ) -> tuple[list[tuple[str, str]], int | None]:
        if max_rows is None:
            max_rows = self._row_capacity_for_page(page)

        if not page.rows:
            return [], None

        selected_row = self._selected_row_for_page(page, self.selected_row)
        if not page.interactive or len(page.rows) <= max_rows:
            return page.rows[:max_rows], (selected_row if page.interactive else None)

        start = max(0, selected_row - (max_rows - 1))
        end = min(len(page.rows), start + max_rows)
        start = max(0, end - max_rows)
        visible_rows = page.rows[start:end]
        return visible_rows, selected_row - start

    def _row_capacity_for_page(self, page: PowerPage) -> int:
        return _row_capacity_for_page(page=page, is_portrait=self.display.is_portrait())

    def _render_page_dots(self, *, total_pages: int, current_page_index: int | None = None) -> None:
        if total_pages <= 1:
            return

        active_page_index = 0 if current_page_index is None else current_page_index
        dots_width = max(0, (total_pages - 1) * 10)
        dots_x = (self.display.WIDTH - dots_width) // 2
        dots_y = self.display.HEIGHT - 42
        for index in range(total_pages):
            color = SETUP.accent if index == active_page_index else MUTED
            self.display.circle(dots_x + (index * 10), dots_y, 2, fill=color)

    def build_pages(
        self,
        *,
        snapshot: Optional["PowerSnapshot"] = None,
        status: dict[str, object] | None = None,
        state: PowerScreenState | None = None,
    ) -> list[PowerPage]:
        resolved_state = state or self._get_state()
        resolved_snapshot = snapshot if snapshot is not None else resolved_state.snapshot
        resolved_status = status if status is not None else dict(resolved_state.status)
        battery_rows = self._build_battery_rows(snapshot=resolved_snapshot)
        runtime_rows = self._build_runtime_rows(
            snapshot=resolved_snapshot,
            status=resolved_status,
        )

        pages = [PowerPage(title="Power", rows=battery_rows[:4])]
        if resolved_state.network_enabled:
            pages.append(PowerPage(title="Network", rows=self._build_network_rows(resolved_state)))
            pages.append(PowerPage(title="GPS", rows=self._build_gps_rows(resolved_state)))
        voice_interactive = not self.is_one_button_mode()
        pages.extend(
            [
                PowerPage(title="Time", rows=battery_rows[4:6] + runtime_rows[:2]),
                PowerPage(title="Care", rows=runtime_rows[2:]),
                PowerPage(
                    title="Voice",
                    rows=self._build_voice_rows(summary_mode=not voice_interactive),
                    interactive=voice_interactive,
                ),
            ]
        )
        return pages

    def lvgl_payload(self) -> PowerScreenLvglPayload:
        return self._visible_payload_for_pages(self._prepared_pages())

    def _visible_payload_for_pages(self, pages: list[PowerPage]) -> PowerScreenLvglPayload:
        if not pages:
            return PowerScreenLvglPayload(
                title_text="Setup",
                page_text=None,
                icon_key="care",
                footer="",
                items=(),
                current_page_index=0,
                total_pages=0,
            )

        active_page_index = self._page_index_for(pages)
        active_page = pages[active_page_index]
        picker_mode = not self.is_one_button_mode() and not self.in_detail

        if picker_mode:
            items = tuple(
                f"{'> ' if index == active_page_index else ''}{page.title}"
                for index, page in self._visible_picker_pages(
                    pages,
                    max_items=5,
                    current_page_index=active_page_index,
                )
            )
            title_text = "Setup"
        else:
            visible_rows, visible_selected_index = self._visible_rows_for_page(active_page)
            formatted_rows: list[str] = []
            for index, (label, value) in enumerate(visible_rows):
                row_text = f"{label}: {value}"
                if visible_selected_index is not None and index == visible_selected_index:
                    row_text = f"> {row_text}"
                formatted_rows.append(row_text)
            items = tuple(formatted_rows)
            title_text = active_page.title

        return PowerScreenLvglPayload(
            title_text=title_text,
            page_text=None,
            icon_key=self._page_icon_key(active_page.title),
            footer=self._instruction_text(active_page),
            items=items,
            current_page_index=active_page_index,
            total_pages=len(pages),
        )

    def _visible_payload_signature(
        self,
        state: PowerScreenState | None,
    ) -> PowerScreenLvglPayload:
        resolved_state = PowerScreenState() if state is None else state
        return self._visible_payload_for_pages(self.build_pages(state=resolved_state))

    def _build_voice_rows(self, *, summary_mode: bool = False) -> list[tuple[str, str]]:
        return _build_voice_rows(
            context=self.context,
            summary_mode=summary_mode,
        )

    def _build_network_rows(
        self,
        state: PowerScreenState | None = None,
    ) -> list[tuple[str, str]]:
        resolved_state = state or self._get_state()
        return list(resolved_state.network_rows or (("Status", "Disabled"),))

    def _build_gps_rows(
        self,
        state: PowerScreenState | None = None,
    ) -> list[tuple[str, str]]:
        resolved_state = state or self._get_state()
        return list(
            resolved_state.gps_rows
            or (
                ("Fix", "Disabled"),
                ("Lat", "--"),
                ("Lng", "--"),
                ("Alt", "--"),
                ("Speed", "--"),
            )
        )

    def _refresh_gps_if_due(self) -> bool:
        now = time.monotonic()
        if now - self._last_gps_query_at < self._gps_refresh_interval_seconds:
            return False

        self._last_gps_query_at = now
        try:
            coord = False if self._actions.refresh_gps is None else self._actions.refresh_gps()
        except Exception as exc:
            logger.warning("GPS refresh failed on Setup screen: {}", exc)
            return False

        if self.context is not None:
            self.context.update_network_status(gps_has_fix=bool(coord))
        return bool(coord)

    def _get_state(self) -> PowerScreenState:
        if self._prepared_state is None:
            return self.refresh_prepared_state()
        return self._prepared_state

    def refresh_prepared_state(
        self,
        *,
        allow_gps_refresh: bool = False,
    ) -> PowerScreenState:
        previous_state = self._prepared_state
        previous_payload = self._visible_payload_signature(previous_state)
        if allow_gps_refresh:
            self._refresh_gps_if_due()
        try:
            self._prepared_state = self._normalize_prepared_state(self._state_provider())
            self._last_prepared_refresh_at = time.monotonic()
        except Exception:
            self._prepared_state = PowerScreenState()
        if previous_payload != self._visible_payload_signature(self._prepared_state):
            self.mark_dirty()
        return self._prepared_state

    def refresh_for_visible_tick(self) -> None:
        if (
            self._prepared_state is not None
            and (time.monotonic() - self._last_prepared_refresh_at)
            < self._visible_tick_refresh_grace_seconds
        ):
            return
        self.refresh_prepared_state(
            allow_gps_refresh=self._gps_refresh_allowed_for_visible_tick(),
        )

    @staticmethod
    def wants_visible_tick_refresh() -> bool:
        """Return True while live Setup telemetry should keep updating on-screen."""

        return True

    def _prepared_pages(self) -> list[PowerPage]:
        if self._prepared_state is None:
            resolved_state = PowerScreenState()
        else:
            resolved_state = self._prepared_state
        voice_signature = self._voice_page_signature()
        one_button_mode = self.is_one_button_mode()
        cache_signature = self._page_cache_signature(
            state=resolved_state,
            voice_signature=voice_signature,
            one_button_mode=one_button_mode,
        )
        if self._cached_pages is not None and self._cached_pages_signature == cache_signature:
            return self._cached_pages

        self._cached_pages = self.build_pages(state=resolved_state)
        self._cached_pages_signature = cache_signature
        return self._cached_pages

    @staticmethod
    def _normalize_prepared_state(state: PowerScreenState) -> PowerScreenState:
        return PowerScreenState(
            snapshot=state.snapshot,
            status=dict(state.status),
            network_enabled=state.network_enabled,
            network_rows=tuple(state.network_rows),
            gps_rows=tuple(state.gps_rows),
            playback_devices=tuple(state.playback_devices),
            capture_devices=tuple(state.capture_devices),
        )

    def _voice_page_signature(self) -> tuple[object, ...] | None:
        if self.context is None:
            return None

        voice = self.context.voice
        return tuple(getattr(voice, field_name) for field_name in _VOICE_PAGE_SIGNATURE_FIELDS)

    @staticmethod
    def _snapshot_page_signature(snapshot: "PowerSnapshot | None") -> tuple[object, ...] | None:
        if snapshot is None:
            return None

        return (
            snapshot.available,
            snapshot.error,
            snapshot.source,
            snapshot.device.model,
            snapshot.battery.level_percent,
            snapshot.battery.charging,
            snapshot.battery.power_plugged,
            snapshot.battery.voltage_volts,
            snapshot.battery.temperature_celsius,
            snapshot.rtc.time,
            snapshot.rtc.alarm_enabled,
            snapshot.rtc.alarm_time,
            snapshot.shutdown.safe_shutdown_level_percent,
        )

    @staticmethod
    def _page_cache_signature(
        *,
        state: PowerScreenState,
        voice_signature: tuple[object, ...] | None,
        one_button_mode: bool,
    ) -> tuple[object, ...]:
        return (
            PowerScreen._snapshot_page_signature(state.snapshot),
            tuple(sorted(state.status.items(), key=lambda item: item[0])),
            state.network_enabled,
            state.network_rows,
            state.gps_rows,
            state.playback_devices,
            state.capture_devices,
            voice_signature,
            one_button_mode,
        )

    def _current_page_title(self) -> str | None:
        pages = self._prepared_pages()
        if not pages:
            return None
        return pages[self._page_index_for(pages)].title

    def _refresh_after_page_change(self) -> None:
        # Show cached GPS rows immediately and only poll again after the page has
        # stayed visible long enough to justify a modem round-trip.
        self.refresh_prepared_state()
        self._sync_page_visibility_state()

    def _sync_page_visibility_state(self) -> None:
        if self._current_page_title() != "GPS":
            self._gps_page_entered_at = None
            return

        if self._gps_page_entered_at is None:
            self._gps_page_entered_at = time.monotonic()

    def _gps_refresh_allowed_for_visible_tick(self) -> bool:
        self._sync_page_visibility_state()
        if self._gps_page_entered_at is None:
            return False

        return (
            time.monotonic() - self._gps_page_entered_at
        ) >= self._gps_page_refresh_delay_seconds

    def _get_snapshot(self) -> Optional["PowerSnapshot"]:
        return self._get_state().snapshot

    def _get_status(self) -> dict[str, object]:
        return dict(self._get_state().status)

    def _build_battery_rows(self, *, snapshot: Optional["PowerSnapshot"]) -> list[tuple[str, str]]:
        return _build_battery_rows(snapshot=snapshot)

    def _build_runtime_rows(
        self,
        *,
        snapshot: Optional["PowerSnapshot"],
        status: dict[str, object],
    ) -> list[tuple[str, str]]:
        return _build_runtime_rows(
            snapshot=snapshot,
            status=status,
        )

    def _instruction_text(self, page: PowerPage) -> str:
        if self.is_one_button_mode():
            return "Tap page / Hold back"
        if not self.in_detail:
            return "A open | B back | X/Y move"
        if page.interactive:
            return "A change | B back | X/Y item | L/R page"
        return "A page | B back | X/Y page"

    def prefers_simple_one_button_navigation(self) -> bool:
        return self.is_one_button_mode()

    def _active_page(self) -> PowerPage:
        pages = self._prepared_pages()
        self.page_index %= len(pages)
        page = pages[self.page_index]
        if page.rows:
            self.selected_row %= len(page.rows)
        else:
            self.selected_row = 0
        return page

    def _is_voice_page(self) -> bool:
        return self.in_detail and self._active_page().interactive

    def _select_next_row(self) -> None:
        page = self._active_page()
        if not page.rows:
            return
        self.selected_row = (self.selected_row + 1) % len(page.rows)

    def _select_previous_row(self) -> None:
        page = self._active_page()
        if not page.rows:
            return
        self.selected_row = (self.selected_row - 1) % len(page.rows)

    def _apply_voice_setting(self, direction: int = 1) -> None:
        if self.context is None:
            return

        row_index = self.selected_row
        if row_index == 0:
            self.context.configure_voice(commands_enabled=not self.context.voice.commands_enabled)
            return
        if row_index == 1:
            self.context.configure_voice(
                ai_requests_enabled=not self.context.voice.ai_requests_enabled
            )
            return
        if row_index == 2:
            self.context.configure_voice(
                screen_read_enabled=not self.context.voice.screen_read_enabled
            )
            return
        if row_index == 3:
            self._cycle_speaker_device(direction)
            return
        if row_index == 4:
            self._cycle_capture_device(direction)
            return
        if row_index == 5:
            self._apply_mic_state(not self.context.voice.mic_muted)
            return
        current = None
        if direction > 0 and self._actions.volume_up is not None:
            current = self._actions.volume_up(5)
        elif direction < 0 and self._actions.volume_down is not None:
            current = self._actions.volume_down(5)
        else:
            volume = self.context.voice.output_volume + (5 * direction)
            self.context.set_volume(max(0, min(100, volume)))
            return
        self._sync_context_output_volume(current)

    def _playback_device_options(self) -> list[str | None]:
        return [None, *self._get_state().playback_devices]

    def _capture_device_options(self) -> list[str | None]:
        return [None, *self._get_state().capture_devices]

    @staticmethod
    def _cycle_option(
        options: list[str | None],
        current: str | None,
        direction: int,
    ) -> str | None:
        if not options:
            return current
        try:
            index = options.index(current)
        except ValueError:
            index = 0
        next_index = (index + (1 if direction >= 0 else -1)) % len(options)
        return options[next_index]

    def _cycle_speaker_device(self, direction: int) -> None:
        if self.context is None:
            return
        next_device = self._cycle_option(
            self._playback_device_options(),
            self.context.voice.speaker_device_id,
            direction,
        )
        self.context.configure_voice(speaker_device_id=next_device)
        if self._actions.persist_speaker_device is not None:
            self._actions.persist_speaker_device(next_device)

    def _cycle_capture_device(self, direction: int) -> None:
        if self.context is None:
            return
        next_device = self._cycle_option(
            self._capture_device_options(),
            self.context.voice.capture_device_id,
            direction,
        )
        self.context.configure_voice(capture_device_id=next_device)
        if self._actions.persist_capture_device is not None:
            self._actions.persist_capture_device(next_device)

    def _next_page(self) -> None:
        pages = self._prepared_pages()
        if not pages:
            return
        self.page_index = (self.page_index + 1) % len(pages)
        self.selected_row = 0
        self._refresh_after_page_change()

    def _previous_page(self) -> None:
        pages = self._prepared_pages()
        if not pages:
            return
        self.page_index = (self.page_index - 1) % len(pages)
        self.selected_row = 0
        self._refresh_after_page_change()

    def on_advance(self, data=None) -> None:
        if self.is_one_button_mode():
            self._next_page()
            return
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row >= len(page.rows) - 1:
                self.selected_row = 0
            else:
                self._select_next_row()
            return
        self._next_page()

    def on_select(self, data=None) -> None:
        if self.is_one_button_mode():
            self._next_page()
            return
        if not self.in_detail:
            self.in_detail = True
            self.selected_row = 0
            return
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def on_back(self, data=None) -> None:
        if self.is_one_button_mode():
            self.request_route("back")
            return
        if self.in_detail:
            self.in_detail = False
            self.selected_row = 0
            return
        self.request_route("back")

    def on_up(self, data=None) -> None:
        if not self.in_detail:
            self._previous_page()
            return
        if self._is_voice_page():
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row == 0:
                self.selected_row = len(page.rows) - 1
            else:
                self._select_previous_row()
            return
        self._previous_page()

    def on_down(self, data=None) -> None:
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            page = self._active_page()
            if not page.rows:
                return
            if self.selected_row >= len(page.rows) - 1:
                self.selected_row = 0
            else:
                self._select_next_row()
            return
        self._next_page()

    def on_left(self, data=None) -> None:
        if not self.in_detail:
            self._previous_page()
            return
        if self._is_voice_page():
            self._apply_voice_setting(-1)
            return
        self._previous_page()

    def on_right(self, data=None) -> None:
        if not self.in_detail:
            self._next_page()
            return
        if self._is_voice_page():
            self._apply_voice_setting(+1)
            return
        self._next_page()

    def _apply_mic_state(self, muted: bool) -> None:
        if self.context is not None:
            self.context.set_mic_muted(muted)
        action = self._actions.mute if muted else self._actions.unmute
        if action is not None:
            action()

    def _sync_context_output_volume(self, volume: int | None) -> None:
        if volume is None or self.context is None:
            return
        self.context.cache_output_volume(volume)
