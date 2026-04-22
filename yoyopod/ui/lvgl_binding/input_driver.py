"""Main-thread LVGL input bridge."""

from __future__ import annotations

from queue import SimpleQueue

from loguru import logger

from yoyopod.ui.input import InputAction
from yoyopod.ui.lvgl_binding.backend import LvglDisplayBackend
from yoyopod.ui.lvgl_binding.binding import LvglBinding


class LvglInputBridge:
    """Queue semantic actions and translate them into LVGL key events."""

    ACTION_TO_KEY = {
        InputAction.ADVANCE: LvglBinding.KEY_RIGHT,
        InputAction.SELECT: LvglBinding.KEY_ENTER,
        InputAction.BACK: LvglBinding.KEY_ESC,
    }

    def __init__(self, backend: LvglDisplayBackend) -> None:
        self.backend = backend
        self._pending: SimpleQueue[int] = SimpleQueue()

    def enqueue_action(self, action: InputAction) -> bool:
        """Store a semantic action for later main-thread dispatch."""

        mapped_key = self.ACTION_TO_KEY.get(action)
        if mapped_key is None:
            return False
        self._pending.put(mapped_key)
        return True

    def process_pending(self) -> int:
        """Send queued actions into LVGL from the coordinator thread."""

        if not self.backend.initialized:
            return 0

        processed = 0
        while not self._pending.empty():
            key = self._pending.get()
            self.backend.queue_key_event(key, True)
            self.backend.queue_key_event(key, False)
            processed += 1

        if processed:
            logger.trace("Delivered {} queued LVGL input events", processed)
        return processed
