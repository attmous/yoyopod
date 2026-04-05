"""
Configuration Manager for YoyoPod.

Manages typed app/VoIP settings and contacts from YAML configuration files.
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from yoyopy.config.models import (
    VoIPFileConfig,
    YoyoPodConfig,
    config_to_dict,
    load_config_model_from_yaml,
)


@dataclass
class Contact:
    """Represents a VoIP contact."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    def __str__(self) -> str:
        return f"{self.name} ({self.sip_address})"


class ConfigManager:
    """
    Manages application configuration.

    Loads typed application and VoIP settings plus contacts from YAML files.
    """

    def __init__(self, config_dir: str = "config") -> None:
        self.config_dir = Path(config_dir)
        self.app_config_file = self.config_dir / "yoyopod_config.yaml"
        self.voip_config_file = self.config_dir / "voip_config.yaml"
        self.contacts_file = self.config_dir / "contacts.yaml"

        self.app_settings = YoyoPodConfig()
        self.voip_settings = VoIPFileConfig()
        self.app_config: dict[str, Any] = config_to_dict(self.app_settings)
        self.voip_config: dict[str, Any] = config_to_dict(self.voip_settings)
        self.contacts: list[Contact] = []
        self.speed_dial: dict[int, str] = {}

        self.app_config_loaded = False
        self.voip_config_loaded = False
        self.contacts_loaded = False

        logger.info(f"ConfigManager initialized (config_dir: {config_dir})")

        self.load_app_config()
        self.load_voip_config()
        self.load_contacts()

    def load_app_config(self) -> bool:
        """
        Load typed application configuration from yoyopod_config.yaml.

        Returns:
            True if loaded from file, False if defaults were used.
        """

        self.app_config_loaded = self.app_config_file.exists()
        try:
            self.app_settings = load_config_model_from_yaml(YoyoPodConfig, self.app_config_file)
            self.app_config = config_to_dict(self.app_settings)

            if self.app_config_loaded:
                logger.info("App configuration loaded successfully")
            else:
                logger.warning(f"App config file not found: {self.app_config_file}")
                logger.info("Using default app configuration")

            logger.debug(f"Mopidy host: {self.app_settings.audio.mopidy_host}")
            logger.debug(f"Display hardware: {self.app_settings.display.hardware}")
            return self.app_config_loaded
        except Exception as exc:
            logger.error(f"Error loading app config: {exc}")
            self.app_settings = YoyoPodConfig()
            self.app_config = config_to_dict(self.app_settings)
            self.app_config_loaded = False
            return False

    def load_voip_config(self) -> bool:
        """
        Load typed VoIP configuration from file.

        Returns:
            True if loaded from file, False if a default file was created.
        """

        self.voip_config_loaded = self.voip_config_file.exists()
        if not self.voip_config_loaded:
            logger.warning(f"VoIP config file not found: {self.voip_config_file}")
            self._create_default_voip_config()

        try:
            self.voip_settings = load_config_model_from_yaml(VoIPFileConfig, self.voip_config_file)
            self.voip_config = config_to_dict(self.voip_settings)

            logger.info("VoIP configuration loaded successfully")
            logger.debug(f"SIP Server: {self.get_sip_server()}")
            logger.debug(f"SIP Identity: {self.get_sip_identity()}")
            return self.voip_config_loaded
        except Exception as exc:
            logger.error(f"Error loading VoIP config: {exc}")
            self.voip_settings = VoIPFileConfig()
            self.voip_config = config_to_dict(self.voip_settings)
            return False

    def load_contacts(self) -> bool:
        """
        Load contacts from file.

        Returns:
            True if loaded successfully, False otherwise.
        """

        self.contacts_loaded = self.contacts_file.exists()
        if not self.contacts_loaded:
            logger.warning(f"Contacts file not found: {self.contacts_file}")
            self._create_default_contacts()
            return False

        try:
            with open(self.contacts_file, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

            self.contacts = [
                Contact(
                    name=contact_data.get("name", ""),
                    sip_address=contact_data.get("sip_address", ""),
                    favorite=contact_data.get("favorite", False),
                    notes=contact_data.get("notes", ""),
                )
                for contact_data in data.get("contacts", [])
            ]
            self.speed_dial = data.get("speed_dial", {})

            logger.info(f"Loaded {len(self.contacts)} contacts")
            return True
        except Exception as exc:
            logger.error(f"Error loading contacts: {exc}")
            return False

    def save_contacts(self) -> bool:
        """
        Save contacts to file.

        Returns:
            True if saved successfully, False otherwise.
        """

        try:
            data = {
                "contacts": [
                    {
                        "name": contact.name,
                        "sip_address": contact.sip_address,
                        "favorite": contact.favorite,
                        "notes": contact.notes,
                    }
                    for contact in self.contacts
                ],
                "speed_dial": self.speed_dial,
            }

            with open(self.contacts_file, "w", encoding="utf-8") as handle:
                yaml.dump(data, handle, default_flow_style=False, sort_keys=False)

            logger.info("Contacts saved successfully")
            return True
        except Exception as exc:
            logger.error(f"Error saving contacts: {exc}")
            return False

    def _create_default_voip_config(self) -> None:
        """Create a default typed VoIP configuration file."""

        logger.info("Creating default VoIP configuration...")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        default_config = config_to_dict(VoIPFileConfig())
        with open(self.voip_config_file, "w", encoding="utf-8") as handle:
            yaml.dump(default_config, handle, default_flow_style=False, sort_keys=False)

        self.voip_settings = VoIPFileConfig()
        self.voip_config = default_config

    def _create_default_contacts(self) -> None:
        """Create a default contacts file."""

        logger.info("Creating default contacts file...")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        default_contacts = {
            "contacts": [
                {
                    "name": "Echo Test Service",
                    "sip_address": "sip:echo@sip.linphone.org",
                    "favorite": True,
                    "notes": "Linphone echo test",
                }
            ],
            "speed_dial": {
                1: "sip:echo@sip.linphone.org",
            },
        }

        with open(self.contacts_file, "w", encoding="utf-8") as handle:
            yaml.dump(default_contacts, handle, default_flow_style=False, sort_keys=False)

        self.load_contacts()

    def get_app_settings(self) -> YoyoPodConfig:
        """Return the typed application configuration model."""

        return self.app_settings

    def get_app_config_dict(self) -> dict[str, Any]:
        """Return the plain-dict form of the application configuration."""

        return config_to_dict(self.app_settings)

    def get_sip_server(self) -> str:
        """Get SIP server address."""

        return self.voip_settings.account.sip_server

    def get_sip_username(self) -> str:
        """Get SIP username."""

        return self.voip_settings.account.sip_username

    def get_sip_password(self) -> str:
        """Get SIP password."""

        return self.voip_settings.account.sip_password

    def get_sip_password_ha1(self) -> str:
        """Get SIP password HA1 hash."""

        return self.voip_settings.account.sip_password_ha1

    def get_sip_identity(self) -> str:
        """Get SIP identity."""

        return self.voip_settings.account.sip_identity

    def get_transport(self) -> str:
        """Get transport protocol."""

        return self.voip_settings.account.transport

    def get_display_name(self) -> str:
        """Get display name."""

        return self.voip_settings.account.display_name

    def get_stun_server(self) -> str:
        """Get STUN server address."""

        return self.voip_settings.network.stun_server

    def get_linphonec_path(self) -> str:
        """Get linphonec executable path."""

        return self.voip_settings.linphonec_path

    def get_auto_answer(self) -> bool:
        """Get auto-answer setting."""

        return self.voip_settings.auto_answer

    def get_call_timeout(self) -> int:
        """Get call timeout in seconds."""

        return self.voip_settings.call_timeout

    def get_playback_device_id(self) -> str:
        """Get the ALSA playback device id for Linphone."""

        return self.voip_settings.audio.playback_device_id

    def get_ringer_device_id(self) -> str:
        """Get the ALSA ringer device id for Linphone."""

        return self.voip_settings.audio.ringer_device_id or self.get_playback_device_id()

    def get_capture_device_id(self) -> str:
        """Get the ALSA capture device id for Linphone."""

        return self.voip_settings.audio.capture_device_id

    def get_media_device_id(self) -> str:
        """Get the ALSA media device id for Linphone."""

        return self.voip_settings.audio.media_device_id or self.get_playback_device_id()

    def get_mic_gain(self) -> int:
        """Get the configured microphone gain (0-100)."""

        return self.voip_settings.audio.mic_gain

    def get_speaker_volume(self) -> int:
        """Get the configured speaker volume (0-100)."""

        return self.voip_settings.audio.speaker_volume

    def get_ring_output_device(self) -> str:
        """Get the output device for the speaker-test ring tone helper."""

        ring_output = self.voip_settings.audio.ring_output_device
        if ring_output:
            return ring_output

        playback_device = self.get_playback_device_id()
        if playback_device.startswith("ALSA:"):
            return playback_device.split(":", 1)[1].strip()
        return playback_device or "default"

    def get_contacts(self, favorites_only: bool = False) -> list[Contact]:
        """Get the current contact list."""

        if favorites_only:
            return [contact for contact in self.contacts if contact.favorite]
        return self.contacts

    def get_listen_sources(self) -> list[str]:
        """Return the configured music sources for the Listen browser."""

        sources = self.app_settings.audio.listen_sources
        return list(sources) if sources else ["local"]

    def get_contact_by_name(self, name: str) -> Optional[Contact]:
        """Get a contact by display name."""

        for contact in self.contacts:
            if contact.name.lower() == name.lower():
                return contact
        return None

    def get_contact_by_address(self, sip_address: str) -> Optional[Contact]:
        """Get a contact by SIP address."""

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
        """Add a new contact and persist it to disk."""

        contact = Contact(
            name=name,
            sip_address=sip_address,
            favorite=favorite,
            notes=notes,
        )
        self.contacts.append(contact)
        self.save_contacts()
        logger.info(f"Added contact: {contact}")
        return contact

    def remove_contact(self, name: str) -> bool:
        """Remove a contact by name."""

        contact = self.get_contact_by_name(name)
        if contact is None:
            return False

        self.contacts.remove(contact)
        self.save_contacts()
        logger.info(f"Removed contact: {contact}")
        return True

    def update_contact(self, name: str, **kwargs) -> bool:
        """Update a contact by name."""

        contact = self.get_contact_by_name(name)
        if contact is None:
            return False

        for key, value in kwargs.items():
            if hasattr(contact, key):
                setattr(contact, key, value)

        self.save_contacts()
        logger.info(f"Updated contact: {contact}")
        return True

    def get_speed_dial_address(self, number: int) -> Optional[str]:
        """Get SIP address for a speed dial number."""

        return self.speed_dial.get(number)

    def set_speed_dial(self, number: int, sip_address: str) -> None:
        """Assign a SIP address to a speed dial number."""

        self.speed_dial[number] = sip_address
        self.save_contacts()
        logger.info(f"Set speed dial {number} to {sip_address}")

    def reload(self) -> None:
        """Reload all configuration from disk."""

        logger.info("Reloading configuration...")
        self.load_app_config()
        self.load_voip_config()
        self.load_contacts()
