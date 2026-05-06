"""Tests for the scaffold log buffer."""

from __future__ import annotations

import pytest

from yoyopod.core import LogBuffer


def test_logbuffer_keeps_only_recent_entries() -> None:
    buffer: LogBuffer[int] = LogBuffer(maxlen=3)
    buffer.extend([1, 2, 3, 4])

    assert buffer.snapshot() == [2, 3, 4]
    assert buffer.tail(2) == [3, 4]


def test_logbuffer_requires_positive_maxlen() -> None:
    with pytest.raises(ValueError, match="positive"):
        LogBuffer(maxlen=0)
