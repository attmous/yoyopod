"""Mutable people-data seams for the YoyoPod runtime."""

from yoyopod.people.directory import PeopleDirectory
from yoyopod.people.models import Contact, contacts_from_mapping, contacts_to_mapping

__all__ = [
    "Contact",
    "PeopleDirectory",
    "contacts_from_mapping",
    "contacts_to_mapping",
]
