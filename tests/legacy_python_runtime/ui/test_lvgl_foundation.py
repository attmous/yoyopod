"""Focused tests for the LVGL migration foundation layer."""

from __future__ import annotations

from yoyopod.ui.input import InputAction
from yoyopod.ui.lvgl_binding import LvglDisplayBackend, LvglInputBridge


class FakeBinding:
    """Minimal native-shim double for backend tests."""

    KEY_RIGHT = 1
    KEY_ENTER = 2
    KEY_ESC = 3

    def __init__(self) -> None:
        self.init_calls = 0
        self.register_input_calls = 0
        self.shutdown_calls = 0
        self.clear_calls = 0
        self.force_refresh_calls = 0
        self.tick_calls: list[int] = []
        self.key_events: list[tuple[int, bool]] = []
        self.flush_callback = None
        self.display_args: tuple[int, int, int] | None = None

    def init(self) -> None:
        self.init_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def register_display(self, width: int, height: int, buffer_pixel_count: int, flush_callback) -> None:
        self.display_args = (width, height, buffer_pixel_count)
        self.flush_callback = flush_callback

    def register_input(self) -> None:
        self.register_input_calls += 1

    def tick_inc(self, milliseconds: int) -> None:
        self.tick_calls.append(milliseconds)

    def timer_handler(self) -> int:
        return 7

    def queue_key_event(self, key: int, pressed: bool) -> None:
        self.key_events.append((key, pressed))

    def show_probe_scene(self, scene_id: int) -> None:
        self.scene_id = scene_id

    def clear_screen(self) -> None:
        self.clear_calls += 1

    def force_refresh(self) -> None:
        self.force_refresh_calls += 1

    def to_bytes(self, pixel_data: object, byte_length: int) -> bytes:
        return bytes(pixel_data[:byte_length])


class FakeFlushTarget:
    """Minimal RGB565 flush target."""

    WIDTH = 240
    HEIGHT = 280
    simulate = False

    def __init__(self) -> None:
        self.flush_calls: list[tuple[int, int, int, int, bytes]] = []

    def draw_rgb565_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        pixel_data: bytes,
    ) -> None:
        self.flush_calls.append((x, y, width, height, pixel_data))


def test_lvgl_backend_initializes_display_and_input_bridge() -> None:
    """The LVGL backend should register both the display and input bridge."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, buffer_lines=40, binding=binding)

    assert backend.initialize() is True
    assert backend.initialized is True
    assert binding.init_calls == 1
    assert binding.register_input_calls == 1
    assert binding.display_args == (240, 280, 240 * 40)


def test_lvgl_backend_flush_callback_forwards_rgb565_regions() -> None:
    """Partial flushes should be forwarded to the flush target unchanged."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()

    assert binding.flush_callback is not None
    binding.flush_callback(5, 6, 2, 1, b"\x12\x34\x56\x78", 4, None)

    assert target.flush_calls == [(5, 6, 2, 1, b"\x12\x34\x56\x78")]


def test_lvgl_input_bridge_maps_one_button_actions_to_key_events() -> None:
    """ADVANCE/SELECT/BACK should become RIGHT/ENTER/ESC press-release pairs."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()
    bridge = LvglInputBridge(backend)

    assert bridge.enqueue_action(InputAction.ADVANCE) is True
    assert bridge.enqueue_action(InputAction.SELECT) is True
    assert bridge.enqueue_action(InputAction.BACK) is True
    assert bridge.enqueue_action(InputAction.NEXT_TRACK) is False

    assert bridge.process_pending() == 3
    assert binding.key_events == [
        (binding.KEY_RIGHT, True),
        (binding.KEY_RIGHT, False),
        (binding.KEY_ENTER, True),
        (binding.KEY_ENTER, False),
        (binding.KEY_ESC, True),
        (binding.KEY_ESC, False),
    ]


def test_lvgl_backend_pump_advances_time_and_runs_timers() -> None:
    """Coordinator-thread pumps should tick LVGL and run timer handling once."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()

    assert backend.pump(16) == 7
    assert binding.tick_calls == [16]


def test_lvgl_backend_reset_clears_the_active_scene() -> None:
    """Reset should issue a clear to the active LVGL backend."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()

    backend.reset()

    assert binding.clear_calls == 1
    assert backend.scene_generation == 1


def test_lvgl_backend_reset_clears_retained_scene_claims() -> None:
    """Reset should drop stale retained-scene ownership alongside native scene teardown."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()
    backend._retained_scene_claims["playlist"] = 123

    backend.reset()

    assert backend._retained_scene_claims == {}


def test_lvgl_backend_force_refresh_delegates_to_native_binding() -> None:
    """Force-refresh should invalidate the active LVGL scene once initialized."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()

    backend.force_refresh()

    assert binding.force_refresh_calls == 1


def test_lvgl_backend_cleanup_shuts_down_the_native_binding() -> None:
    """Cleanup should shut down the shim and mark the backend inactive."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()

    backend.cleanup()

    assert binding.shutdown_calls == 1
    assert backend.binding is None
    assert backend.initialized is False
    assert backend.scene_generation == 1


def test_lvgl_backend_cleanup_clears_retained_scene_claims() -> None:
    """Cleanup should discard retained-scene ownership before the binding is dropped."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    backend.initialize()
    backend._retained_scene_claims["playlist"] = 123

    backend.cleanup()

    assert backend._retained_scene_claims == {}


def test_lvgl_input_bridge_ignores_queued_actions_until_backend_is_ready() -> None:
    """Queued LVGL actions should not dispatch before backend initialization."""

    binding = FakeBinding()
    target = FakeFlushTarget()
    backend = LvglDisplayBackend(target, binding=binding)
    bridge = LvglInputBridge(backend)

    assert bridge.enqueue_action(InputAction.SELECT) is True
    assert bridge.process_pending() == 0
    assert binding.key_events == []

    backend.initialize()
    assert bridge.process_pending() == 1
    assert binding.key_events == [
        (binding.KEY_ENTER, True),
        (binding.KEY_ENTER, False),
    ]
