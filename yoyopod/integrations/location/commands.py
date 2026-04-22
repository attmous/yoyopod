"""Typed commands for the scaffold location integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestFixCommand:
    """Ask the backend for the latest GPS fix."""


@dataclass(frozen=True, slots=True)
class EnableGpsCommand:
    """Power up or enable the GPS receiver."""


@dataclass(frozen=True, slots=True)
class DisableGpsCommand:
    """Power down or disable the GPS receiver."""
