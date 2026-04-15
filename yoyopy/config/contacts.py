"""Contact models and serialization helpers for YoyoPod config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Contact:
    """Represents a VoIP contact."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        """Return the kid-facing label for the contact."""

        label = self.notes.strip()
        return label or self.name

    def __str__(self) -> str:
        return f"{self.name} ({self.sip_address})"


def contacts_from_mapping(data: dict[str, Any]) -> tuple[list[Contact], dict[int, str]]:
    """Build contacts and speed-dial data from one config mapping."""

    contacts = [
        Contact(
            name=contact_data.get("name", ""),
            sip_address=contact_data.get("sip_address", ""),
            favorite=contact_data.get("favorite", False),
            notes=contact_data.get("notes", ""),
        )
        for contact_data in data.get("contacts", [])
    ]
    return contacts, data.get("speed_dial", {})


def contacts_to_mapping(
    contacts: list[Contact],
    speed_dial: dict[int, str],
) -> dict[str, Any]:
    """Serialize contacts and speed dial back into YAML-friendly data."""

    return {
        "contacts": [
            {
                "name": contact.name,
                "sip_address": contact.sip_address,
                "favorite": contact.favorite,
                "notes": contact.notes,
            }
            for contact in contacts
        ],
        "speed_dial": speed_dial,
    }
