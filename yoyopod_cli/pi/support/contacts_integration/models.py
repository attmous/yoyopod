"""People-domain models and YAML serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Contact:
    """One mutable address-book entry used by the Talk flow."""

    name: str
    sip_address: str = ""
    phone_number: str = ""
    favorite: bool = False
    notes: str = ""
    contact_id: str = ""
    sync_origin: str = "local"
    can_call: bool = True
    can_receive: bool = True
    aliases: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Return the kid-facing label for the contact."""

        label = self.notes.strip()
        return label or self.name

    def __str__(self) -> str:
        return f"{self.name} ({self.sip_address or self.phone_number or 'no-address'})"

    def preferred_call_target(
        self,
        *,
        gsm_enabled: bool = False,
    ) -> tuple[str | None, str]:
        """Return the active call route and address for this contact."""

        if self.sip_address.strip():
            return "sip", self.sip_address.strip()
        if gsm_enabled and self.phone_number.strip():
            return "gsm", self.phone_number.strip()
        return None, ""

    def is_callable(self, *, gsm_enabled: bool = False) -> bool:
        """Return whether this contact can be called on the active device."""

        route, _ = self.preferred_call_target(gsm_enabled=gsm_enabled)
        return bool(route)


def contacts_from_mapping(data: dict[str, Any]) -> tuple[list[Contact], dict[int, str]]:
    """Build contacts and speed-dial data from one YAML-compatible mapping."""

    contacts = [
        Contact(
            name=contact_data.get("name", ""),
            sip_address=contact_data.get("sip_address", ""),
            phone_number=contact_data.get("phone_number", ""),
            favorite=contact_data.get("favorite", False),
            notes=contact_data.get("notes", ""),
            contact_id=contact_data.get("contact_id", ""),
            sync_origin=contact_data.get("sync_origin", "local"),
            can_call=contact_data.get("can_call", True),
            can_receive=contact_data.get("can_receive", True),
            aliases=_contact_aliases_from_value(contact_data.get("aliases")),
        )
        for contact_data in data.get("contacts", [])
    ]
    raw_speed_dial = data.get("speed_dial", {})
    speed_dial = {
        int(slot): str(address)
        for slot, address in raw_speed_dial.items()
        if str(slot).isdigit() and str(address).strip()
    }
    return contacts, speed_dial


def _contact_aliases_from_value(value: object) -> list[str]:
    """Return cleaned aliases when the serialized shape is list-like."""

    if not isinstance(value, (list, tuple)):
        return []
    return [str(alias).strip() for alias in value if str(alias).strip()]


def contacts_to_mapping(
    contacts: list[Contact],
    speed_dial: dict[int, str],
) -> dict[str, Any]:
    """Serialize contacts and speed dial into a YAML-friendly mapping."""

    serialized_contacts: list[dict[str, Any]] = []
    for contact in contacts:
        entry = {
            "name": contact.name,
            "sip_address": contact.sip_address,
            "favorite": contact.favorite,
            "notes": contact.notes,
        }
        if contact.phone_number:
            entry["phone_number"] = contact.phone_number
        if contact.contact_id:
            entry["contact_id"] = contact.contact_id
        if contact.sync_origin != "local":
            entry["sync_origin"] = contact.sync_origin
        if not contact.can_call:
            entry["can_call"] = contact.can_call
        if not contact.can_receive:
            entry["can_receive"] = contact.can_receive
        if contact.aliases:
            entry["aliases"] = list(contact.aliases)
        serialized_contacts.append(entry)

    return {
        "contacts": serialized_contacts,
        "speed_dial": speed_dial,
    }
