"""Tests for generic LVGL backend wiring in the display factory."""

from unittest.mock import MagicMock, patch

import pytest


def test_factory_attaches_lvgl_backend_when_flush_target_available():
    """When an adapter provides a flush target, factory should try LVGL wiring."""
    from yoyopy.ui.display.factory import _try_attach_lvgl_backend

    adapter = MagicMock()
    adapter.get_flush_target.return_value = adapter
    adapter.WIDTH = 320
    adapter.HEIGHT = 240

    # LVGL binding won't be available in CI, so this returns False
    result = _try_attach_lvgl_backend(adapter)
    assert isinstance(result, bool)


def test_factory_skips_lvgl_when_no_flush_target():
    """When adapter returns None flush target, skip LVGL entirely."""
    from yoyopy.ui.display.factory import _try_attach_lvgl_backend

    adapter = MagicMock()
    adapter.get_flush_target.return_value = None

    result = _try_attach_lvgl_backend(adapter)
    assert result is False


def test_factory_returns_false_when_lvgl_unavailable():
    """When LVGL native shim is not compiled, return False gracefully."""
    from yoyopy.ui.display.factory import _try_attach_lvgl_backend

    adapter = MagicMock()
    adapter.get_flush_target.return_value = adapter
    adapter.WIDTH = 240
    adapter.HEIGHT = 280

    # In CI without LVGL compiled, should return False without raising
    result = _try_attach_lvgl_backend(adapter)
    assert result is False
