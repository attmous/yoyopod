"""Compatibility shim for the relocated display screenshot helpers."""

from yoyopod.ui.display.screenshot import _capture_screenshot, _request_screenshot_capture

__all__ = ["_capture_screenshot", "_request_screenshot_capture"]
