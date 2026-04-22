"""Handlers for the scaffold contacts integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoyopod.integrations.contacts.commands import (
    LookupByAddressCommand,
    MarkVoiceNotesSeenCommand,
    ReloadContactsCommand,
)


def refresh_contacts_state(app: Any, integration: Any) -> None:
    """Refresh scaffold contacts entities from the directory and voice-note source."""

    by_address = _normalize_unread_counts(
        integration.unread_voice_note_counts_by_address_provider()
        if integration.unread_voice_note_counts_by_address_provider is not None
        else {}
    )
    integration.last_unread_by_address = dict(by_address)
    app.states.set("contacts.people_count", _count_contacts(integration.directory))
    app.states.set(
        "contacts.unread_voice_notes",
        sum(by_address.values()),
        {"by_address": dict(by_address)},
    )


def lookup_by_address(integration: Any, command: LookupByAddressCommand) -> object | None:
    """Return one contact by address when present."""

    if not isinstance(command, LookupByAddressCommand):
        raise TypeError("contacts.lookup_by_address expects LookupByAddressCommand")
    return integration.directory.get_contact_by_address(command.address)


def reload_contacts(app: Any, integration: Any, command: ReloadContactsCommand) -> bool:
    """Reload the directory and mirror the latest counts into scaffold state."""

    if not isinstance(command, ReloadContactsCommand):
        raise TypeError("contacts.reload expects ReloadContactsCommand")

    result = _reload_directory(integration.directory)
    refresh_contacts_state(app, integration)
    return result


def mark_voice_notes_seen(
    app: Any,
    integration: Any,
    command: MarkVoiceNotesSeenCommand,
) -> bool:
    """Mark one peer's voice notes seen when a handler is available."""

    if not isinstance(command, MarkVoiceNotesSeenCommand):
        raise TypeError("contacts.mark_voice_notes_seen expects MarkVoiceNotesSeenCommand")

    if integration.mark_voice_notes_seen_handler is None:
        return False

    integration.mark_voice_notes_seen_handler(command.address)
    refresh_contacts_state(app, integration)
    return True


def _count_contacts(directory: object) -> int:
    get_contacts = getattr(directory, "get_contacts", None)
    if callable(get_contacts):
        return len(list(get_contacts()))
    contacts = getattr(directory, "contacts", ())
    return len(list(contacts))


def _reload_directory(directory: object) -> bool:
    reload_directory = getattr(directory, "reload", None)
    if callable(reload_directory):
        result = reload_directory()
        return True if result is None else bool(result)

    load_directory = getattr(directory, "load", None)
    if not callable(load_directory):
        raise AttributeError("Contacts directory must expose reload() or load()")
    result = load_directory()
    return True if result is None else bool(result)


def _normalize_unread_counts(raw_counts: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for address, value in raw_counts.items():
        normalized_address = str(address).strip()
        if not normalized_address:
            continue
        normalized_count = max(0, int(value))
        if normalized_count <= 0:
            continue
        counts[normalized_address] = normalized_count
    return dict(sorted(counts.items()))
