"""Mutable people-data store backed by runtime user-state."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from yoyopod.config.storage import atomic_write_yaml, load_yaml_mapping
from yoyopod.people.models import Contact, contacts_from_mapping, contacts_to_mapping


class PeopleDirectory:
    """Load, bootstrap, query, and persist the mutable YoyoPod address book."""

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
    def from_config_manager(cls, config_manager) -> "PeopleDirectory":
        """Build one directory from the composed config manager paths."""

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
    ) -> Contact:
        """Append one contact and persist the updated address book."""

        contact = Contact(
            name=name,
            sip_address=sip_address,
            favorite=favorite,
            notes=notes,
        )
        self.contacts.append(contact)
        self.save()
        return contact

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

    def reload(self) -> bool:
        """Reload mutable people data from disk."""

        return self.load()
