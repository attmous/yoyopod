"""Tests for the scaffold contacts integration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.integrations.call import setup as setup_call
from yoyopod.integrations.contacts import (
    LookupByAddressCommand,
    MarkVoiceNotesSeenCommand,
    ReloadContactsCommand,
    setup,
    teardown,
)
from tests.integrations.test_call import FakeRinger, FakeVoipManager


@dataclass(slots=True)
class FakeContact:
    """Simple contact model for contacts integration tests."""

    name: str
    sip_address: str

    @property
    def display_name(self) -> str:
        return self.name


class FakeDirectory:
    """Minimal directory double backed by an in-memory contact list."""

    def __init__(self) -> None:
        self.contacts = [
            FakeContact(name="Alice", sip_address="sip:alice@example.com"),
            FakeContact(name="Bob", sip_address="sip:bob@example.com"),
        ]
        self.reload_calls = 0

    def get_contacts(self) -> list[FakeContact]:
        return list(self.contacts)

    def get_contact_by_address(self, address: str) -> FakeContact | None:
        for contact in self.contacts:
            if contact.sip_address == address:
                return contact
        return None

    def reload(self) -> bool:
        self.reload_calls += 1
        return True


class FakeVoiceNoteSummary:
    """In-memory unread-count source with subscription hooks."""

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = dict(counts)
        self._callbacks: list[Callable[[], None]] = []

    def snapshot(self) -> dict[str, int]:
        return dict(self.counts)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()

    def mark_seen(self, address: str) -> None:
        self.counts.pop(address, None)


def test_contacts_setup_seeds_people_and_unread_voice_note_state() -> None:
    app = build_test_app()
    directory = FakeDirectory()
    summary = FakeVoiceNoteSummary(
        {
            "sip:alice@example.com": 2,
            "sip:bob@example.com": 1,
        }
    )

    integration = setup(
        app,
        directory=directory,
        unread_voice_note_counts_by_address_provider=summary.snapshot,
    )

    assert integration is app.integrations["contacts"]
    assert app.states.get_value("contacts.people_count") == 2
    assert app.states.get_value("contacts.unread_voice_notes") == 3
    assert app.states.get("contacts.unread_voice_notes").attrs == {
        "by_address": {
            "sip:alice@example.com": 2,
            "sip:bob@example.com": 1,
        }
    }


def test_contacts_services_lookup_reload_and_mark_seen_refresh_state() -> None:
    app = build_test_app()
    directory = FakeDirectory()
    summary = FakeVoiceNoteSummary(
        {
            "sip:alice@example.com": 2,
            "sip:bob@example.com": 1,
        }
    )
    setup(
        app,
        directory=directory,
        unread_voice_note_counts_by_address_provider=summary.snapshot,
        mark_voice_notes_seen_handler=summary.mark_seen,
    )

    contact = app.services.call(
        "contacts",
        "lookup_by_address",
        LookupByAddressCommand(address="sip:alice@example.com"),
    )
    reloaded = app.services.call("contacts", "reload", ReloadContactsCommand())
    marked_seen = app.services.call(
        "contacts",
        "mark_voice_notes_seen",
        MarkVoiceNotesSeenCommand(address="sip:alice@example.com"),
    )

    assert contact is not None
    assert contact.display_name == "Alice"
    assert reloaded is True
    assert directory.reload_calls == 1
    assert marked_seen is True
    assert app.states.get_value("contacts.unread_voice_notes") == 1
    assert app.states.get("contacts.unread_voice_notes").attrs == {
        "by_address": {
            "sip:bob@example.com": 1,
        }
    }


def test_contacts_voice_note_subscription_refreshes_state_from_background_thread() -> None:
    app = build_test_app()
    directory = FakeDirectory()
    summary = FakeVoiceNoteSummary({"sip:alice@example.com": 1})
    setup(
        app,
        directory=directory,
        unread_voice_note_counts_by_address_provider=summary.snapshot,
        subscribe_to_voice_note_changes=summary.subscribe,
    )
    drain_all(app)

    summary.counts["sip:bob@example.com"] = 2

    worker = threading.Thread(target=summary.emit)
    worker.start()
    worker.join()

    assert app.states.get_value("contacts.unread_voice_notes") == 1

    drain_all(app)

    assert app.states.get_value("contacts.unread_voice_notes") == 3
    assert app.states.get("contacts.unread_voice_notes").attrs == {
        "by_address": {
            "sip:alice@example.com": 1,
            "sip:bob@example.com": 2,
        }
    }


def test_contacts_auto_bridge_call_voice_note_summary_when_call_integration_exists() -> None:
    app = build_test_app()
    manager = FakeVoipManager(runtime_snapshot_owned=True)
    setup_call(
        app,
        manager=manager,
        ringer=FakeRinger(),
    )
    setup(app, directory=FakeDirectory())
    drain_all(app)

    manager.voice_note_unread_by_address = {
        "sip:alice@example.com": 2,
        "sip:bob@example.com": 1,
    }
    manager.emit_message_summary(
        3,
        {
            "sip:alice@example.com": {
                "message_id": "note-1",
                "direction": "incoming",
            },
            "sip:bob@example.com": {
                "message_id": "note-2",
                "direction": "incoming",
            },
        },
    )
    drain_all(app)

    assert app.states.get_value("contacts.unread_voice_notes") == 3
    assert app.states.get("contacts.unread_voice_notes").attrs == {
        "by_address": {
            "sip:alice@example.com": 2,
            "sip:bob@example.com": 1,
        }
    }

    app.services.call(
        "contacts",
        "mark_voice_notes_seen",
        MarkVoiceNotesSeenCommand(address="sip:alice@example.com"),
    )
    drain_all(app)

    assert manager.voice_note_unread_by_address == {"sip:bob@example.com": 1}


def test_contacts_services_reject_wrong_payload_types() -> None:
    app = build_test_app()
    setup(app, directory=FakeDirectory())

    try:
        app.services.call("contacts", "lookup_by_address", {"address": "sip:alice@example.com"})
    except TypeError as exc:
        assert str(exc) == "contacts.lookup_by_address expects LookupByAddressCommand"
    else:
        raise AssertionError("contacts.lookup_by_address accepted an untyped payload")

    try:
        app.services.call("contacts", "reload", {"force": True})
    except TypeError as exc:
        assert str(exc) == "contacts.reload expects ReloadContactsCommand"
    else:
        raise AssertionError("contacts.reload accepted an untyped payload")

    try:
        app.services.call("contacts", "mark_voice_notes_seen", {"address": "sip:alice@example.com"})
    except TypeError as exc:
        assert str(exc) == "contacts.mark_voice_notes_seen expects MarkVoiceNotesSeenCommand"
    else:
        raise AssertionError("contacts.mark_voice_notes_seen accepted an untyped payload")

    teardown(app)
    assert "contacts" not in app.integrations
