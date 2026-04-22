"""Typed commands for the scaffold contacts integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LookupByAddressCommand:
    """Resolve one contact by SIP address."""

    address: str


@dataclass(frozen=True, slots=True)
class ReloadContactsCommand:
    """Reload contacts from the backing store."""


@dataclass(frozen=True, slots=True)
class MarkVoiceNotesSeenCommand:
    """Clear unread voice-note markers for one peer address."""

    address: str
