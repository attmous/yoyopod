"""Typed commands for the scaffold network integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnablePppCommand:
    """Request PPP data-session bring-up."""


@dataclass(frozen=True, slots=True)
class DisablePppCommand:
    """Request PPP data-session tear-down."""


@dataclass(frozen=True, slots=True)
class RefreshSignalCommand:
    """Query the modem once for current signal strength."""


@dataclass(frozen=True, slots=True)
class SetApnCommand:
    """Configure APN credentials for the cellular connection."""

    apn: str
    username: str = ""
    password: str = ""
