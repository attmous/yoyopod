"""People directory manager for mutable contacts and speed-dial state."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from yoyopod.config.composition import atomic_write_yaml, load_yaml_mapping
from yoyopod.integrations.contacts.cloud_sync import build_cloud_contact
from yoyopod.integrations.contacts.models import (
    Contact,
    contacts_from_mapping,
    contacts_to_mapping,
)


class PeopleManager:
    """Load, bootstrap, query, and persist the mutable YoYoPod address book."""

    def __init__(
        self,
        contacts_file: str | Path,
        *,
        contacts_seed_file: str | Path | None = None,
    ) -> None:
        self.contacts_file = Path(contacts_file)
        self.contacts_seed_file = (
            Path(contacts_seed_file) if contacts_seed_file is not None else None
        )
        self.contacts: list[Contact] = []
        self.speed_dial: dict[int, str] = {}
        self.loaded = False
        self.bootstrapped_from_seed = False
        self.load()

    @classmethod
    def from_config_manager(cls, config_manager) -> "PeopleManager":
        """Build one manager from the composed config manager paths."""

        return cls(
            config_manager.get_people_contacts_file(),
            contacts_seed_file=config_manager.get_people_contacts_seed_file(),
        )

    def _bootstrap_payload(self) -> dict[str, object]:
        """Return the first payload written into mutable people state."""

        if self.contacts_seed_file is not None and self.contacts_seed_file.exists():
            self.bootstrapped_from_seed = True
            return load_yaml_mapping(self.contacts_seed_file)
        self.bootstrapped_from_seed = False
        return {"contacts": [], "speed_dial": {}}

    def load(self) -> bool:
        """Load contacts from mutable user-state, bootstrapping from a seed if needed."""

        if not self.contacts_file.exists():
            payload = self._bootstrap_payload()
            atomic_write_yaml(self.contacts_file, payload)

        try:
            payload = load_yaml_mapping(self.contacts_file)
            self.contacts, self.speed_dial = contacts_from_mapping(payload)
            self.loaded = True
            logger.info(
                "Loaded {} contacts from {}",
                len(self.contacts),
                self.contacts_file,
            )
            return True
        except Exception:
            logger.exception("Error loading people directory from {}", self.contacts_file)
            self.contacts = []
            self.speed_dial = {}
            self.loaded = False
            return False

    def save(self) -> bool:
        """Persist the current mutable address book to user-state."""

        try:
            atomic_write_yaml(
                self.contacts_file,
                contacts_to_mapping(self.contacts, self.speed_dial),
            )
            return True
        except Exception:
            logger.exception("Error saving people directory to {}", self.contacts_file)
            return False

    def get_contacts(self, favorites_only: bool = False) -> list[Contact]:
        """Return the current contact list."""

        if favorites_only:
            return [contact for contact in self.contacts if contact.favorite]
        return list(self.contacts)

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[Contact]:
        """Return contacts that can be called on the currently enabled transports."""

        return [
            contact for contact in self.contacts if contact.is_callable(gsm_enabled=gsm_enabled)
        ]

    def get_local_contacts(self) -> list[Contact]:
        """Return contacts that are not managed by cloud sync."""

        return [contact for contact in self.contacts if contact.sync_origin != "cloud"]

    def get_contact_by_name(self, name: str) -> Contact | None:
        """Return one contact matched by source name."""

        for contact in self.contacts:
            if contact.name.lower() == name.lower():
                return contact
        return None

    def get_contact_by_address(self, sip_address: str) -> Contact | None:
        """Return one contact matched by SIP address."""

        for contact in self.contacts:
            if contact.sip_address == sip_address:
                return contact
        return None

    def add_contact(
        self,
        name: str,
        sip_address: str,
        favorite: bool = False,
        notes: str = "",
        aliases: list[str] | None = None,
    ) -> Contact:
        """Append one contact and persist the updated address book."""

        contact = Contact(
            name=name,
            sip_address=sip_address,
            favorite=favorite,
            notes=notes,
            aliases=list(aliases or []),
        )
        self.contacts.append(contact)
        self.save()
        return contact

    def get_contact_by_alias(self, alias: str) -> Contact | None:
        """Return one contact matched by name, display name, notes, or alias."""

        normalized = " ".join(alias.strip().lower().split())
        if not normalized:
            return None
        for contact in self.contacts:
            labels = {
                contact.name,
                contact.display_name,
                contact.notes,
                *contact.aliases,
            }
            if normalized in {" ".join(label.strip().lower().split()) for label in labels if label}:
                return contact
        return None

    def remove_contact(self, name: str) -> bool:
        """Remove one contact by source name."""

        contact = self.get_contact_by_name(name)
        if contact is None:
            return False
        self.contacts.remove(contact)
        self.save()
        return True

    def update_contact(self, name: str, **kwargs) -> bool:
        """Update one contact by source name and persist the result."""

        contact = self.get_contact_by_name(name)
        if contact is None:
            return False

        for key, value in kwargs.items():
            if hasattr(contact, key):
                setattr(contact, key, value)

        self.save()
        return True

    def get_speed_dial_address(self, number: int) -> str | None:
        """Return the SIP address stored for one speed-dial slot."""

        return self.speed_dial.get(number)

    def set_speed_dial(self, number: int, sip_address: str) -> None:
        """Assign one SIP address to a speed-dial slot and persist it."""

        self.speed_dial[number] = sip_address
        self.save()

    @staticmethod
    def _contact_identity(contact: Contact) -> tuple[str, str, str]:
        """Return a normalized identity tuple for dedupe decisions."""

        return (
            contact.name.strip().lower(),
            contact.sip_address.strip().lower(),
            contact.phone_number.strip(),
        )

    def merge_cloud_contacts(self, entries: list[dict[str, object]]) -> bool:
        """Replace the cloud-managed contact subset while preserving local contacts."""

        existing_cloud_addresses = {
            contact.sip_address.strip()
            for contact in self.contacts
            if contact.sync_origin == "cloud" and contact.sip_address.strip()
        }
        merged_cloud_contacts: list[Contact] = []
        merged_cloud_identities: set[tuple[str, str, str]] = set()
        updated_speed_dial = {
            int(slot): address
            for slot, address in self.speed_dial.items()
            if address not in existing_cloud_addresses
        }

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            contact = build_cloud_contact(entry)
            if contact is None:
                continue
            merged_cloud_contacts.append(contact)
            merged_cloud_identities.add(self._contact_identity(contact))

            quick_dial = entry.get("quick_dial")
            if isinstance(quick_dial, int) and 1 <= quick_dial <= 9:
                route, address = contact.preferred_call_target(gsm_enabled=False)
                if route == "sip" and address:
                    updated_speed_dial[quick_dial] = address

        local_contacts = [
            contact
            for contact in self.contacts
            if contact.sync_origin != "cloud"
            and self._contact_identity(contact) not in merged_cloud_identities
        ]

        self.contacts = local_contacts + merged_cloud_contacts
        self.speed_dial = dict(sorted(updated_speed_dial.items()))
        logger.info(
            "Merged {} cloud contacts into {} (preserved {} local contacts)",
            len(merged_cloud_contacts),
            self.contacts_file,
            len(local_contacts),
        )
        return self.save()

    def reload(self) -> bool:
        """Reload mutable people data from disk."""

        return self.load()


PeopleDirectory = PeopleManager
