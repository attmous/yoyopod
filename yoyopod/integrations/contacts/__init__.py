"""Contacts integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from yoyopod.integrations.contacts.commands import (
    LookupByAddressCommand,
    MarkVoiceNotesSeenCommand,
    ReloadContactsCommand,
)
from yoyopod.integrations.contacts.cloud_sync import build_cloud_contact
from yoyopod.integrations.contacts.directory import PeopleDirectory, PeopleManager
from yoyopod.integrations.contacts.handlers import (
    lookup_by_address,
    mark_voice_notes_seen,
    refresh_contacts_state,
    reload_contacts,
)
from yoyopod.integrations.contacts.models import (
    Contact,
    contacts_from_mapping,
    contacts_to_mapping,
)
from yoyopod.integrations.call.events import VoiceNoteSummaryChangedEvent


@dataclass(slots=True)
class ContactsIntegration:
    """Runtime handles owned by the scaffold contacts integration."""

    directory: object
    unread_voice_note_counts_by_address_provider: Callable[[], dict[str, int]] | None = None
    mark_voice_notes_seen_handler: Callable[[str], None] | None = None
    unsubscribe_voice_note_changes: Callable[[], None] | None = None
    last_unread_by_address: dict[str, int] = field(default_factory=dict)


def setup(
    app: Any,
    *,
    directory: object | None = None,
    unread_voice_note_counts_by_address_provider: Callable[[], dict[str, int]] | None = None,
    subscribe_to_voice_note_changes: (
        Callable[[Callable[[], None]], Callable[[], None] | None] | None
    ) = None,
    mark_voice_notes_seen_handler: Callable[[str], None] | None = None,
) -> ContactsIntegration:
    """Register scaffold contacts services and seed contacts state."""

    derived_provider = unread_voice_note_counts_by_address_provider
    if derived_provider is None:
        derived_provider = _derive_call_voice_note_counts_provider(app)

    derived_mark_seen_handler = mark_voice_notes_seen_handler
    if derived_mark_seen_handler is None:
        derived_mark_seen_handler = _derive_mark_voice_notes_seen_handler(app)

    integration = ContactsIntegration(
        directory=directory or _build_directory(app.config),
        unread_voice_note_counts_by_address_provider=derived_provider,
        mark_voice_notes_seen_handler=derived_mark_seen_handler,
    )
    app.integrations["contacts"] = integration
    refresh_contacts_state(app, integration)

    if subscribe_to_voice_note_changes is not None:
        integration.unsubscribe_voice_note_changes = subscribe_to_voice_note_changes(
            lambda: app.scheduler.run_on_main(lambda: refresh_contacts_state(app, integration))
        )
    elif derived_provider is not None:
        app.bus.subscribe(
            VoiceNoteSummaryChangedEvent,
            lambda event: refresh_contacts_state(app, integration),
        )

    app.services.register(
        "contacts",
        "lookup_by_address",
        lambda data: lookup_by_address(integration, data),
    )
    app.services.register(
        "contacts",
        "reload",
        lambda data: reload_contacts(app, integration, data),
    )
    app.services.register(
        "contacts",
        "mark_voice_notes_seen",
        lambda data: mark_voice_notes_seen(app, integration, data),
    )
    return integration


def teardown(app: Any) -> None:
    """Drop the scaffold contacts integration handle and detach listeners."""

    integration = app.integrations.pop("contacts", None)
    if integration is None:
        return
    if integration.unsubscribe_voice_note_changes is not None:
        integration.unsubscribe_voice_note_changes()


def _build_directory(config: object | None) -> PeopleManager:
    if config is None:
        raise ValueError("contacts setup requires app.config or an explicit directory")

    get_contacts_file = getattr(config, "get_people_contacts_file", None)
    if callable(get_contacts_file):
        get_seed_file = getattr(config, "get_people_contacts_seed_file", None)
        return PeopleManager(
            get_contacts_file(),
            contacts_seed_file=get_seed_file() if callable(get_seed_file) else None,
        )

    people = getattr(config, "people", None)
    contacts_file = getattr(people, "contacts_file", "")
    contacts_seed_file = getattr(people, "contacts_seed_file", "")
    if not contacts_file:
        raise ValueError("contacts setup requires a people.contacts_file path")
    return PeopleManager(
        contacts_file,
        contacts_seed_file=contacts_seed_file or None,
    )


def _derive_call_voice_note_counts_provider(
    app: Any,
) -> Callable[[], dict[str, int]] | None:
    call_integration = getattr(app, "integrations", {}).get("call")
    if call_integration is None:
        return None

    def _snapshot() -> dict[str, int]:
        return dict(getattr(call_integration, "last_voice_note_unread_by_address", {}))

    return _snapshot


def _derive_mark_voice_notes_seen_handler(
    app: Any,
) -> Callable[[str], None] | None:
    call_integration = getattr(app, "integrations", {}).get("call")
    if call_integration is None:
        return None
    manager = getattr(call_integration, "manager", None)
    mark_voice_notes_seen = getattr(manager, "mark_voice_notes_seen", None)
    if not callable(mark_voice_notes_seen):
        return None
    return mark_voice_notes_seen


__all__ = [
    "build_cloud_contact",
    "Contact",
    "ContactsIntegration",
    "LookupByAddressCommand",
    "MarkVoiceNotesSeenCommand",
    "PeopleDirectory",
    "PeopleManager",
    "ReloadContactsCommand",
    "contacts_from_mapping",
    "contacts_to_mapping",
    "setup",
    "teardown",
]
