"""Whisplay-focused LVGL display backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from loguru import logger

from yoyopod.ui.lvgl_binding.binding import LvglBinding, LvglBindingError


class Rgb565FlushTarget(Protocol):
    """Minimal adapter contract for receiving RGB565 partial flushes."""

    WIDTH: int
    HEIGHT: int
    simulate: bool

    def draw_rgb565_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None: ...


@dataclass(slots=True)
class LvglDisplayBackend:
    """Own LVGL init, display/input registration, and timer pumping."""

    flush_target: Rgb565FlushTarget
    buffer_lines: int = 40
    binding: LvglBinding | None = None
    initialized: bool = field(init=False, default=False)
    scene_generation: int = field(init=False, default=0)
    _retained_scene_claims: dict[str, int] = field(init=False, default_factory=dict)
    width: int = field(init=False, default=0)
    height: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.binding = self.binding or LvglBinding.try_load()
        self.width = int(self.flush_target.WIDTH)
        self.height = int(self.flush_target.HEIGHT)

    @property
    def available(self) -> bool:
        """Return True when the native shim is available."""

        return self.binding is not None

    @property
    def buffer_pixel_count(self) -> int:
        return self.width * self.buffer_lines

    def initialize(self) -> bool:
        """Initialize LVGL and register display/input bridges."""

        if self.initialized:
            return True
        if self.binding is None:
            logger.warning("LVGL backend requested but native shim is unavailable")
            return False

        try:
            self.binding.init()
            self.binding.register_display(
                self.width,
                self.height,
                self.buffer_pixel_count,
                self._flush_callback,
            )
            self.binding.register_input()
        except LvglBindingError as exc:
            logger.error("Failed to initialize LVGL backend: {}", exc)
            return False

        self.initialized = True
        logger.info(
            "LVGL backend initialized ({}x{}, buffer_lines={})",
            self.width,
            self.height,
            self.buffer_lines,
        )
        return True

    def _flush_callback(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: object,
        byte_length: int,
        _user_data: object,
    ) -> None:
        if self.binding is None:
            return
        payload = self.binding.to_bytes(pixel_data, byte_length)
        self.flush_target.draw_rgb565_region(x, y, width, height, payload)

    def tick(self, milliseconds: int) -> None:
        if not self.initialized or self.binding is None:
            return
        self.binding.tick_inc(milliseconds)

    def timer_handler(self) -> int:
        if not self.initialized or self.binding is None:
            return 0
        return self.binding.timer_handler()

    def pump(self, milliseconds: int) -> int:
        """Advance LVGL time and run timers once on the coordinator thread."""

        if not self.initialized:
            return 0
        self.tick(milliseconds)
        return self.timer_handler()

    def queue_key_event(self, key: int, pressed: bool) -> None:
        if not self.initialized or self.binding is None:
            return
        self.binding.queue_key_event(key, pressed)

    def show_probe_scene(self, scene_id: int) -> None:
        if not self.initialized or self.binding is None:
            raise LvglBindingError("LVGL backend is not initialized")
        self.binding.show_probe_scene(scene_id)

    def clear(self) -> None:
        if self.initialized and self.binding is not None:
            self.binding.clear_screen()
            self.scene_generation += 1
            self._retained_scene_claims.clear()

    def force_refresh(self) -> None:
        """Invalidate and redraw the active LVGL scene immediately."""

        if self.initialized and self.binding is not None:
            self.binding.force_refresh()

    def reset(self) -> None:
        """Clear LVGL-managed content before a hard backend handoff."""

        self.clear()

    def cleanup(self) -> None:
        if not self.initialized or self.binding is None:
            return
        self.scene_generation += 1
        self._retained_scene_claims.clear()
        self.binding.shutdown()
        self.binding = None
        self.initialized = False
