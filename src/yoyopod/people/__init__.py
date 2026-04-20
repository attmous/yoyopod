"""Mutable people-data seams for the YoyoPod runtime."""

from yoyopod.people.manager import PeopleDirectory, PeopleManager
from yoyopod.people.cloud_sync import build_cloud_contact
from yoyopod.people.models import Contact, contacts_from_mapping, contacts_to_mapping

__all__ = [
    "build_cloud_contact",
    "Contact",
    "PeopleDirectory",
    "PeopleManager",
    "contacts_from_mapping",
    "contacts_to_mapping",
]
