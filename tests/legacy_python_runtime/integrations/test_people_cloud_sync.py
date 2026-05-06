"""Focused tests for cloud-managed contact sync and call routing helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.integrations.contacts.directory import PeopleDirectory
from yoyopod.integrations.contacts.models import Contact


def test_cloud_contact_sync_preserves_local_contacts_and_updates_speed_dial(
    tmp_path: Path,
) -> None:
    contacts_file = tmp_path / "data" / "people" / "contacts.yaml"
    contacts_file.parent.mkdir(parents=True, exist_ok=True)
    contacts_file.write_text(
        yaml.safe_dump(
            {
                "contacts": [
                    {
                        "name": "Local Grandma",
                        "sip_address": "sip:grandma@example.com",
                        "favorite": True,
                        "notes": "Grandma",
                    },
                    {
                        "name": "Old Dashboard Mom",
                        "sip_address": "sip:old-mom@example.com",
                        "phone_number": "+1 555-0101",
                        "favorite": True,
                        "notes": "Parent",
                        "contact_id": "contact-mom",
                        "sync_origin": "cloud",
                    },
                ],
                "speed_dial": {
                    1: "sip:old-mom@example.com",
                    9: "sip:grandma@example.com",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    directory = PeopleDirectory(contacts_file)

    saved = directory.merge_cloud_contacts(
        [
            {
                "id": "contact-mom",
                "name": "Mom",
                "sip_address": "sip:mom@example.com",
                "phone_number": "+1 555-0101",
                "relationship": "parent",
                "is_primary": True,
                "can_call": True,
                "can_receive": True,
                "quick_dial": 1,
            },
            {
                "id": "contact-dad",
                "name": "Dad",
                "sip_address": "",
                "phone_number": "+1 555-0102",
                "relationship": "parent",
                "is_primary": False,
                "can_call": True,
                "can_receive": True,
                "quick_dial": 2,
            },
        ]
    )

    assert saved is True
    assert [contact.name for contact in directory.contacts] == [
        "Local Grandma",
        "Mom",
        "Dad",
    ]
    assert directory.speed_dial == {
        1: "sip:mom@example.com",
        9: "sip:grandma@example.com",
    }

    persisted = yaml.safe_load(contacts_file.read_text(encoding="utf-8"))
    assert [contact["name"] for contact in persisted["contacts"]] == [
        "Local Grandma",
        "Mom",
        "Dad",
    ]


def test_contact_prefers_sip_call_path_while_gsm_is_disabled() -> None:
    contact = Contact(
        name="Mom",
        sip_address="sip:mom@example.com",
        phone_number="+1 555-0101",
    )
    phone_only = Contact(
        name="Dad",
        phone_number="+1 555-0102",
    )

    assert contact.preferred_call_target(gsm_enabled=False) == (
        "sip",
        "sip:mom@example.com",
    )
    assert phone_only.preferred_call_target(gsm_enabled=False) == (None, "")
    assert phone_only.preferred_call_target(gsm_enabled=True) == (
        "gsm",
        "+1 555-0102",
    )


def test_cloud_contact_sync_dedupes_matching_seed_contact(tmp_path: Path) -> None:
    contacts_file = tmp_path / "data" / "people" / "contacts.yaml"
    contacts_file.parent.mkdir(parents=True, exist_ok=True)
    contacts_file.write_text(
        yaml.safe_dump(
            {
                "contacts": [
                    {
                        "name": "Hagar",
                        "sip_address": "sip:hagarmo@sip.linphone.org",
                        "favorite": True,
                        "notes": "Mama",
                    }
                ],
                "speed_dial": {
                    1: "sip:hagarmo@sip.linphone.org",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    directory = PeopleDirectory(contacts_file)
    directory.merge_cloud_contacts(
        [
            {
                "id": "contact-hagar",
                "name": "Hagar",
                "sip_address": "sip:hagarmo@sip.linphone.org",
                "phone_number": None,
                "relationship": "Mama",
                "is_primary": True,
                "can_call": True,
                "can_receive": True,
                "quick_dial": 1,
            }
        ]
    )

    assert len(directory.contacts) == 1
    assert directory.contacts[0].sync_origin == "cloud"
    assert directory.contacts[0].contact_id == "contact-hagar"
