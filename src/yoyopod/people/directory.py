"""Compatibility shim for historical people-directory import path."""

from __future__ import annotations

from yoyopod.people.manager import PeopleManager

PeopleDirectory = PeopleManager

__all__ = ["PeopleDirectory", "PeopleManager"]
