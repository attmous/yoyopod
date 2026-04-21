"""Display screenshot helpers used by signal handlers and diagnostics."""

from __future__ import annotations

from typing import Any

from loguru import logger


def _capture_screenshot(
    *,
    adapter: object | None,
    screenshot_path: str,
    app_log: Any,
    prefer_readback: bool,
) -> bool:
    """Capture a screenshot using readback-first or shadow-first method order."""

    if adapter is None:
        app_log.warning("Screenshot not available — no active display adapter")
        return False

    ordered_methods = (
        (
            ("save_screenshot_readback", "LVGL readback"),
            ("save_screenshot", "shadow buffer"),
        )
        if prefer_readback
        else (
            ("save_screenshot", "shadow buffer"),
            ("save_screenshot_readback", "LVGL readback"),
        )
    )

    for method_name, label in ordered_methods:
        save_fn = getattr(adapter, method_name, None)
        if not callable(save_fn):
            continue
        try:
            if save_fn(screenshot_path):
                app_log.info("Saved screenshot via {} -> {}", label, screenshot_path)
                return True
        except Exception:
            logger.exception("Screenshot capture failed via {}", label)
            return False

    app_log.warning("Screenshot not available — adapter does not expose a usable capture method")
    return False


def _request_screenshot_capture(
    *,
    app: object,
    screenshot_path: str,
    app_log: Any,
    prefer_readback: bool,
) -> None:
    """Queue screenshot capture onto the app loop when possible."""

    def capture_on_app_loop() -> None:
        display = getattr(app, "display", None)
        adapter = None
        if display is not None:
            get_adapter = getattr(display, "get_adapter", None)
            if callable(get_adapter):
                adapter = get_adapter()
            else:
                adapter = getattr(display, "_adapter", None)

        should_reset_shadow_sync = False
        if adapter is not None and hasattr(adapter, "_force_shadow_buffer_sync"):
            setattr(adapter, "_force_shadow_buffer_sync", True)
            should_reset_shadow_sync = True

        try:
            screen_manager = getattr(app, "screen_manager", None)
            refresh_current_screen = (
                getattr(screen_manager, "refresh_current_screen", None)
                if screen_manager is not None
                else None
            )
            if callable(refresh_current_screen):
                refresh_current_screen()

            get_ui_backend = getattr(display, "get_ui_backend", None)
            if callable(get_ui_backend):
                ui_backend = get_ui_backend()
                force_refresh = (
                    getattr(ui_backend, "force_refresh", None) if ui_backend is not None else None
                )
                if callable(force_refresh):
                    force_refresh()

            _capture_screenshot(
                adapter=adapter,
                screenshot_path=screenshot_path,
                app_log=app_log,
                prefer_readback=prefer_readback,
            )
        finally:
            if should_reset_shadow_sync:
                setattr(adapter, "_force_shadow_buffer_sync", False)

    runtime_loop = getattr(app, "runtime_loop", None)
    queue_callback = getattr(runtime_loop, "queue_main_thread_callback", None)
    if callable(queue_callback):
        queue_callback(capture_on_app_loop)
        app_log.info(
            "Queued screenshot capture request ({})",
            "readback-first" if prefer_readback else "shadow-first",
        )
        return

    legacy_queue_callback = getattr(app, "_queue_main_thread_callback", None)
    if callable(legacy_queue_callback):
        legacy_queue_callback(capture_on_app_loop)
        app_log.info(
            "Queued screenshot capture request ({})",
            "readback-first" if prefer_readback else "shadow-first",
        )
        return

    capture_on_app_loop()


__all__ = ["_capture_screenshot", "_request_screenshot_capture"]
