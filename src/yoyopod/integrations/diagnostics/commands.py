"""Typed commands for the scaffold diagnostics integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    """Write one scaffold diagnostics snapshot to disk."""

    reason: str
    tail_lines: int = 50
