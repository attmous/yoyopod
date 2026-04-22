"""People directory configuration model."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


@dataclass(slots=True)
class PeopleDirectoryConfig:
    """Authored paths that define where mutable people data lives."""

    contacts_file: str = config_value(
        default="data/people/contacts.yaml",
        env="YOYOPOD_PEOPLE_CONTACTS_FILE",
    )
    contacts_seed_file: str = config_value(
        default="config/people/contacts.seed.yaml",
        env="YOYOPOD_PEOPLE_CONTACTS_SEED_FILE",
    )
