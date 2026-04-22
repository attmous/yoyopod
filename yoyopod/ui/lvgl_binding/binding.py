"""Low-level cffi binding for the native YoyoPod LVGL shim."""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from cffi import FFI
from loguru import logger

from .scenes import (
    AskSceneMixin,
    CallsSceneMixin,
    HubSceneMixin,
    ListenSceneMixin,
    NowPlayingSceneMixin,
    PlaylistSceneMixin,
    PowerSceneMixin,
    StatusBarSceneMixin,
    TalkSceneMixin,
)

SHIM_CDEF = """
typedef void (*yoyopod_lvgl_flush_cb_t)(
    int32_t x,
    int32_t y,
    int32_t width,
    int32_t height,
    const unsigned char * pixel_data,
    uint32_t byte_length,
    void * user_data
);

int yoyopod_lvgl_init(void);
void yoyopod_lvgl_shutdown(void);
int yoyopod_lvgl_register_display(
    int32_t width,
    int32_t height,
    uint32_t buffer_pixel_count,
    yoyopod_lvgl_flush_cb_t flush_cb,
    void * user_data
);
int yoyopod_lvgl_register_input(void);
void yoyopod_lvgl_tick_inc(uint32_t ms);
uint32_t yoyopod_lvgl_timer_handler(void);
int yoyopod_lvgl_queue_key_event(int32_t key, int32_t pressed);
int yoyopod_lvgl_show_probe_scene(int32_t scene_id);
int yoyopod_lvgl_set_status_bar_state(
    int32_t network_enabled,
    int32_t network_connected,
    int32_t wifi_connected,
    int32_t signal_strength,
    int32_t gps_has_fix
);
int yoyopod_lvgl_hub_build(void);
int yoyopod_lvgl_hub_sync(
    const char * icon_key,
    const char * title,
    const char * subtitle,
    const char * footer,
    const char * time_text,
    uint32_t accent_rgb,
    int32_t selected_index,
    int32_t total_cards,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
);
void yoyopod_lvgl_hub_destroy(void);
int yoyopod_lvgl_talk_build(void);
int yoyopod_lvgl_talk_sync(
    const char * title_text,
    const char * icon_key,
    int32_t outlined,
    const char * footer,
    int32_t selected_index,
    int32_t total_cards,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_talk_destroy(void);
int yoyopod_lvgl_talk_actions_build(void);
int yoyopod_lvgl_talk_actions_sync(
    const char * contact_name,
    const char * title_text,
    const char * status_text,
    int32_t status_kind,
    const char * footer,
    const char * icon_0,
    int32_t color_kind_0,
    const char * icon_1,
    int32_t color_kind_1,
    const char * icon_2,
    int32_t color_kind_2,
    int32_t action_count,
    int32_t selected_index,
    int32_t layout_kind,
    int32_t button_size_kind,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_talk_actions_destroy(void);
int yoyopod_lvgl_listen_build(void);
int yoyopod_lvgl_listen_sync(
    const char * page_text,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * subtitle_0,
    const char * subtitle_1,
    const char * subtitle_2,
    const char * subtitle_3,
    const char * icon_0,
    const char * icon_1,
    const char * icon_2,
    const char * icon_3,
    int32_t item_count,
    int32_t selected_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb,
    const char * empty_title,
    const char * empty_subtitle
);
void yoyopod_lvgl_listen_destroy(void);
int yoyopod_lvgl_playlist_build(void);
int yoyopod_lvgl_playlist_sync(
    const char * title_text,
    const char * page_text,
    const char * status_chip_text,
    int32_t status_chip_kind,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * subtitle_0,
    const char * subtitle_1,
    const char * subtitle_2,
    const char * subtitle_3,
    const char * badge_0,
    const char * badge_1,
    const char * badge_2,
    const char * badge_3,
    const char * icon_0,
    const char * icon_1,
    const char * icon_2,
    const char * icon_3,
    int32_t item_count,
    int32_t selected_visible_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb,
    const char * empty_title,
    const char * empty_subtitle,
    const char * empty_icon_key
);
void yoyopod_lvgl_playlist_destroy(void);
int yoyopod_lvgl_now_playing_build(void);
int yoyopod_lvgl_now_playing_sync(
    const char * title_text,
    const char * artist_text,
    const char * state_text,
    const char * footer,
    int32_t progress_permille,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_now_playing_destroy(void);
int yoyopod_lvgl_incoming_call_build(void);
int yoyopod_lvgl_incoming_call_sync(
    const char * caller_name,
    const char * caller_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_incoming_call_destroy(void);
int yoyopod_lvgl_outgoing_call_build(void);
int yoyopod_lvgl_outgoing_call_sync(
    const char * callee_name,
    const char * callee_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_outgoing_call_destroy(void);
int yoyopod_lvgl_in_call_build(void);
int yoyopod_lvgl_in_call_sync(
    const char * caller_name,
    const char * duration_text,
    const char * mute_text,
    const char * footer,
    int32_t muted,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_in_call_destroy(void);
int yoyopod_lvgl_ask_build(void);
int yoyopod_lvgl_ask_sync(
    const char * icon_key,
    const char * title_text,
    const char * subtitle_text,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_ask_destroy(void);
int yoyopod_lvgl_power_build(void);
int yoyopod_lvgl_power_sync(
    const char * title_text,
    const char * page_text,
    const char * icon_key,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * item_4,
    int32_t item_count,
    int32_t current_page_index,
    int32_t total_pages,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_power_destroy(void);
void yoyopod_lvgl_clear_screen(void);
void yoyopod_lvgl_force_refresh(void);
int32_t yoyopod_lvgl_snapshot(unsigned char * output_buf, uint32_t buf_size);
const char * yoyopod_lvgl_last_error(void);
const char * yoyopod_lvgl_version(void);
"""


class LvglBindingError(RuntimeError):
    """Raised when the native LVGL shim cannot be loaded or initialized."""


class LvglBinding(
    StatusBarSceneMixin,
    HubSceneMixin,
    TalkSceneMixin,
    ListenSceneMixin,
    PlaylistSceneMixin,
    NowPlayingSceneMixin,
    CallsSceneMixin,
    AskSceneMixin,
    PowerSceneMixin,
):
    """Thin ABI-mode wrapper over the native LVGL shim."""

    KEY_NONE = 0
    KEY_RIGHT = 1
    KEY_ENTER = 2
    KEY_ESC = 3

    SCENE_CARD = 1
    SCENE_LIST = 2
    SCENE_FOOTER = 3
    SCENE_CAROUSEL = 4
    HUB_SYNC_STRING_CACHE_LIMIT = 16

    def __init__(self, library_path: Path | None = None) -> None:
        self.ffi = FFI()
        self.ffi.cdef(SHIM_CDEF)
        self.library_path = library_path or self._resolve_library_path()
        if self.library_path is None:
            raise LvglBindingError(
                "LVGL shim library not found; run scripts/lvgl_build.py on the target platform",
            )

        self.lib = self.ffi.dlopen(str(self.library_path))
        self._flush_callback = None
        self._hub_sync_string_cache: OrderedDict[str, object] = OrderedDict()
        logger.info("Loaded LVGL shim from {}", self.library_path)

    @classmethod
    def try_load(cls, library_path: Path | None = None) -> "LvglBinding | None":
        """Attempt to load the native shim without raising."""

        try:
            return cls(library_path=library_path)
        except Exception as exc:
            logger.debug("LVGL shim not available: {}", exc)
            return None

    def _resolve_library_path(self) -> Path | None:
        env_override = os.getenv("YOYOPOD_LVGL_SHIM_PATH")
        candidates: list[Path] = []
        if env_override:
            candidates.append(Path(env_override))

        base_dir = Path(__file__).resolve().parent
        candidates.extend(
            [
                base_dir / "native" / "build" / "libyoyopod_lvgl_shim.so",
                base_dir / "native" / "build" / "yoyopod_lvgl_shim.dll",
                base_dir / "native" / "build" / "libyoyopod_lvgl_shim.dylib",
                Path.cwd() / "build" / "lvgl" / "libyoyopod_lvgl_shim.so",
            ]
        )

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _pack_rgb(color: tuple[int, int, int]) -> int:
        red, green, blue = color
        return ((int(red) & 0xFF) << 16) | ((int(green) & 0xFF) << 8) | (int(blue) & 0xFF)

    def _new_char_array(self, value: str) -> object:
        return self.ffi.new("char[]", value.encode("utf-8"))

    def _get_cached_char_array(
        self,
        cache: OrderedDict[str, object],
        value: str,
        *,
        max_entries: int,
    ) -> object:
        cached = cache.get(value)
        if cached is not None:
            cache.move_to_end(value)
            return cached

        cached = self._new_char_array(value)
        cache[value] = cached
        if len(cache) > max_entries:
            cache.popitem(last=False)
        return cached

    def _raise_if_error(self, result: int) -> None:
        if result != 0:
            raise LvglBindingError(self.last_error())

    def init(self) -> None:
        if self.lib.yoyopod_lvgl_init() != 0:
            raise LvglBindingError(self.last_error())

    def shutdown(self) -> None:
        self.lib.yoyopod_lvgl_shutdown()

    def register_display(
        self, width: int, height: int, buffer_pixel_count: int, flush_callback
    ) -> None:
        callback = self.ffi.callback(
            "void(int32_t, int32_t, int32_t, int32_t, const unsigned char *, uint32_t, void *)",
            flush_callback,
        )
        result = self.lib.yoyopod_lvgl_register_display(
            width,
            height,
            buffer_pixel_count,
            callback,
            self.ffi.NULL,
        )
        if result != 0:
            raise LvglBindingError(self.last_error())
        self._flush_callback = callback

    def register_input(self) -> None:
        if self.lib.yoyopod_lvgl_register_input() != 0:
            raise LvglBindingError(self.last_error())

    def tick_inc(self, milliseconds: int) -> None:
        self.lib.yoyopod_lvgl_tick_inc(max(0, int(milliseconds)))

    def timer_handler(self) -> int:
        return int(self.lib.yoyopod_lvgl_timer_handler())

    def queue_key_event(self, key: int, pressed: bool) -> None:
        if self.lib.yoyopod_lvgl_queue_key_event(int(key), 1 if pressed else 0) != 0:
            raise LvglBindingError(self.last_error())

    def show_probe_scene(self, scene_id: int) -> None:
        if self.lib.yoyopod_lvgl_show_probe_scene(scene_id) != 0:
            raise LvglBindingError(self.last_error())

    def snapshot(self, width: int, height: int) -> bytes | None:
        """Capture the active LVGL screen to an RGB565_SWAPPED byte buffer.

        Uses lv_snapshot_take() to render the full LVGL object tree into
        a temporary buffer, then copies the pixel data out.

        Args:
            width: Display width in pixels.
            height: Display height in pixels.

        Returns:
            Bytes of RGB565_SWAPPED pixel data, or None on failure.
        """

        # 2 bytes per pixel for RGB565
        buf_size = width * height * 2
        output_buf = self.ffi.new(f"unsigned char[{buf_size}]")
        result = self.lib.yoyopod_lvgl_snapshot(output_buf, buf_size)
        if result < 0:
            logger.error("LVGL snapshot failed: {}", self.last_error())
            return None
        return bytes(self.ffi.buffer(output_buf, result))

    def clear_screen(self) -> None:
        self.lib.yoyopod_lvgl_clear_screen()

    def force_refresh(self) -> None:
        self.lib.yoyopod_lvgl_force_refresh()

    def to_bytes(self, pixel_data: object, byte_length: int) -> bytes:
        return bytes(self.ffi.buffer(pixel_data, byte_length))

    def last_error(self) -> str:
        raw = self.lib.yoyopod_lvgl_last_error()
        if raw == self.ffi.NULL:
            return "unknown LVGL shim error"
        return self.ffi.string(raw).decode("utf-8", errors="replace")

    def version(self) -> str:
        raw = self.lib.yoyopod_lvgl_version()
        if raw == self.ffi.NULL:
            return "unknown"
        return self.ffi.string(raw).decode("utf-8", errors="replace")
