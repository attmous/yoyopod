"""Typed commands for the scaffold cloud integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SyncNowCommand:
    """Trigger one on-demand cloud sync roundtrip."""


@dataclass(frozen=True, slots=True)
class PublishTelemetryCommand:
    """Publish one explicit telemetry payload through the cloud transport."""

    topic_suffix: str
    payload: dict[str, Any] = field(default_factory=dict)
    qos: int = 0
