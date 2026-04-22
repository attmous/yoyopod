"""Canonical location backends used by scaffold and legacy code."""

from __future__ import annotations

from yoyopod.backends.location.gps import GpsBackend, GpsReader

__all__ = ["GpsBackend", "GpsReader"]
