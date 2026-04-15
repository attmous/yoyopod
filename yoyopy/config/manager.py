"""
Configuration Manager for YoyoPod.

Manages typed app/VoIP settings and contacts from YAML configuration files.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from yoyopy.config.contacts import Contact, contacts_from_mapping, contacts_to_mapping
from yoyopy.config.layers import resolve_config_board, resolve_config_layers
from yoyopy.config.models import (
    VoIPFileConfig,
    YoyoPodConfig,
    build_config_model,
    config_to_dict,
)
from yoyopy.config.storage import (
    atomic_write_yaml,
    deep_merge_mappings,
    load_yaml_layers,
    load_yaml_mapping,
)


class ConfigManager:
    """
    Manages application configuration.

    Loads typed application and VoIP settings plus contacts from YAML files.
    """

    def __init__(
        self,
        config_dir: str = "config",
        config_board: str | None = None,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.config_board = resolve_config_board(explicit_board=config_board)
        self.app_config_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            "yoyopod_config.yaml",
        )
        self.voip_config_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            "voip_config.yaml",
        )
        self.contacts_layers = resolve_config_layers(
            self.config_dir,
            self.config_board,
            "contacts.yaml",
        )

        self.app_config_file = self.app_config_layers[-1]
        self.voip_config_file = self.voip_config_layers[-1]
        self.contacts_file = self.contacts_layers[-1]

        self.app_settings = YoyoPodConfig()
        self.voip_settings = VoIPFileConfig()
        self.app_config: dict[str, Any] = config_to_dict(self.app_settings)
        self.voip_config: dict[str, Any] = config_to_dict(self.voip_settings)
        self.contacts: list[Contact] = []
        self.speed_dial: dict[int, str] = {}

        self.app_config_loaded = False
        self.voip_config_loaded = False
        self.contacts_loaded = False

        logger.info(
            "ConfigManager initialized "
            f"(config_dir: {config_dir}, config_board: {self.config_board or 'default'})"
        )

        self.load_app_config()
        self.load_voip_config()
        self.load_contacts()

    def load_app_config(self) -> bool:
        """
        Load typed application configuration from yoyopod_config.yaml.

        Returns:
            True if loaded from file, False if defaults were used.
        """

        self.app_config_loaded = any(path.exists() for path in self.app_config_layers)
        try:
            data = load_yaml_layers(self.app_config_layers)
            self.app_settings = build_config_model(YoyoPodConfig, data)
            self.app_config = config_to_dict(self.app_settings)

            if self.app_config_loaded:
                logger.info(
                    "App configuration loaded successfully from "
                    + ", ".join(str(path) for path in self.app_config_layers if path.exists())
                )
            else:
                logger.warning(
                    "App config file not found: "
                    + ", ".join(str(path) for path in self.app_config_layers)
                )
                logger.info("Using default app configuration")

            logger.debug(f"Music directory: {self.app_settings.audio.music_dir}")
            logger.debug(f"mpv socket: {self.app_settings.audio.mpv_socket or '(default)'}")
            logger.debug(f"Display hardware: {self.app_settings.display.hardware}")
            return self.app_config_loaded
        except Exception:
            logger.exception("Error loading app config")
            self.app_settings = YoyoPodConfig()
            self.app_config = config_to_dict(self.app_settings)
            self.app_config_loaded = False
            return False

    def save_app_config(self) -> bool:
        """Persist the current typed application config to yoyopod_config.yaml.

        This is a whole-model write. Prefer targeted layer patches for UI-driven
        settings updates so env overlays and board-layer shape stay intact.
        """

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            data = config_to_dict(self.app_settings)
            atomic_write_yaml(self.app_config_file, data)
            self.app_config = data
            self.app_config_loaded = True
            logger.info("App configuration saved successfully")
            return True
        except Exception:
            logger.exception("Error saving app config")
            return False

    def _save_app_config_layer_patch(self, patch: dict[str, Any]) -> bool:
        """Persist one partial update into the active app-config layer only."""

        try:
            current = load_yaml_mapping(self.app_config_file)
            data = deep_merge_mappings(current, patch)
            atomic_write_yaml(self.app_config_file, data)
            self.app_config_loaded = True
            logger.info("App configuration layer updated successfully")
            return True
        except Exception:
            logger.exception("Error updating app config layer")
            return False

    def load_voip_config(self) -> bool:
        """
        Load typed VoIP configuration from file.

        Returns:
            True if loaded from file, False if a default file was created.
        """

        self.voip_config_loaded = any(path.exists() for path in self.voip_config_layers)
        if not self.voip_config_loaded:
            logger.warning(
                "VoIP config file not found: "
                + ", ".join(str(path) for path in self.voip_config_layers)
            )
            self._create_default_voip_config()

        try:
            data = load_yaml_layers(self.voip_config_layers)
            self.voip_settings = build_config_model(VoIPFileConfig, data)
            self.voip_config = config_to_dict(self.voip_settings)

            logger.info("VoIP configuration loaded successfully")
            logger.debug(f"SIP Server: {self.get_sip_server()}")
            logger.debug(f"SIP Identity: {self.get_sip_identity()}")
            return self.voip_config_loaded
        except Exception:
            logger.exception("Error loading VoIP config")
            self.voip_settings = VoIPFileConfig()
            self.voip_config = config_to_dict(self.voip_settings)
            return False

    def load_contacts(self) -> bool:
        """
        Load contacts from file.

        Returns:
            True if loaded successfully, False otherwise.
        """

        self.contacts_loaded = any(path.exists() for path in self.contacts_layers)
        if not self.contacts_loaded:
            logger.warning(
                "Contacts file not found: " + ", ".join(str(path) for path in self.contacts_layers)
            )
            self._create_default_contacts()
            return False

        try:
            data = load_yaml_layers(self.contacts_layers)
            self.contacts, self.speed_dial = contacts_from_mapping(data)

            logger.info(f"Loaded {len(self.contacts)} contacts")
            return True
        except Exception:
            logger.exception("Error loading contacts")
            return False

    def save_contacts(self) -> bool:
        """
        Save contacts to file.

        Returns:
            True if saved successfully, False otherwise.
        """

        try:
            data = contacts_to_mapping(self.contacts, self.speed_dial)

            with open(self.contacts_file, "w", encoding="utf-8") as handle:
                yaml.dump(data, handle, default_flow_style=False, sort_keys=False)

            logger.info("Contacts saved successfully")
            return True
        except Exception:
            logger.exception("Error saving contacts")
            return False

    def _create_default_voip_config(self) -> None:
        """Create a default typed VoIP configuration file."""

        logger.info("Creating default VoIP configuration...")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        default_config = config_to_dict(VoIPFileConfig())
        self.voip_config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.voip_config_file, "w", encoding="utf-8") as handle:
            yaml.dump(default_config, handle, default_flow_style=False, sort_keys=False)

        self.voip_settings = VoIPFileConfig()
        self.voip_config = default_config

    def _create_default_contacts(self) -> None:
        """Create a default contacts file."""

        logger.info("Creating default contacts file...")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        default_contacts = {
            "contacts": [],
            "speed_dial": {},
        }

        self.contacts_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.contacts_file, "w", encoding="utf-8") as handle:
            yaml.dump(default_contacts, handle, default_flow_style=False, sort_keys=False)

        self.load_contacts()

    def _resolve_config_board(
        self,
        *,
        explicit_board: str | None,
    ) -> str | None:
        """Resolve the active board config from args, env, or hardware detection."""
        return resolve_config_board(explicit_board=explicit_board)

    def _resolve_config_layers(self, filename: str) -> tuple[Path, ...]:
        """Return the base config file plus any matching board overlay."""
        return resolve_config_layers(self.config_dir, self.config_board, filename)

    def _load_yaml_layers(self, paths: tuple[Path, ...]) -> dict[str, Any]:
        """Load and merge YAML mappings from lowest to highest precedence."""
        return load_yaml_layers(paths)

    def get_app_settings(self) -> YoyoPodConfig:
        """Return the typed application configuration model."""

        return self.app_settings

    def set_voice_capture_device_id(self, device_id: str | None) -> bool:
        """Persist the capture device selector used by local voice interactions."""

        value = (device_id or "").strip()
        if "\n" in value or "\r" in value:
            raise ValueError("Invalid ALSA device id (contains newline)")
        if not self._save_app_config_layer_patch({"voice": {"capture_device_id": value}}):
            return False
        self.app_settings.voice.capture_device_id = value
        self.app_config.setdefault("voice", {})["capture_device_id"] = value
        return True

    def set_voice_speaker_device_id(self, device_id: str | None) -> bool:
        """Persist the playback device selector used by local voice interactions."""

        value = (device_id or "").strip()
        if "\n" in value or "\r" in value:
            raise ValueError("Invalid ALSA device id (contains newline)")
        if not self._save_app_config_layer_patch({"voice": {"speaker_device_id": value}}):
            return False
        self.app_settings.voice.speaker_device_id = value
        self.app_config.setdefault("voice", {})["speaker_device_id"] = value
        return True

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

    def get_voip_factory_config_path(self) -> str:
        """Get the Liblinphone factory-config path."""

        return self.voip_settings.account.factory_config_path

    def get_transport(self) -> str:
        """Get transport protocol."""

        return self.voip_settings.account.transport

    def get_display_name(self) -> str:
        """Get display name."""

        return self.voip_settings.account.display_name

    def get_stun_server(self) -> str:
        """Get STUN server address."""

        return self.voip_settings.network.stun_server

    def get_file_transfer_server_url(self) -> str:
        """Get the configured Liblinphone file transfer server URL."""

        return self.voip_settings.messaging.file_transfer_server_url

    def get_conference_factory_uri(self) -> str:
        """Get the configured conference-factory URI for hosted chat rooms."""

        return self.voip_settings.messaging.conference_factory_uri

    def get_lime_server_url(self) -> str:
        """Get the configured Liblinphone LIME/X3DH server URL."""

        return self.voip_settings.messaging.lime_server_url

    def get_voip_iterate_interval_ms(self) -> int:
        """Get the Liblinphone iterate cadence in milliseconds."""

        return self.voip_settings.messaging.iterate_interval_ms

    def get_message_store_dir(self) -> str:
        """Get the persistent VoIP message metadata directory."""

        return self.voip_settings.messaging.message_store_dir

    def get_voice_note_store_dir(self) -> str:
        """Get the directory used to store local voice-note files."""

        return self.voip_settings.messaging.voice_note_store_dir

    def get_voice_note_max_duration_seconds(self) -> int:
        """Get the maximum allowed voice-note duration in seconds."""

        return self.voip_settings.messaging.voice_note_max_duration_seconds

    def get_auto_download_incoming_voice_recordings(self) -> bool:
        """Return whether incoming voice-note attachments should auto-download."""

        return self.voip_settings.messaging.auto_download_incoming_voice_recordings

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

    def get_default_output_volume(self) -> int:
        """Get the shared app output volume used by music and call playback."""

        return self.app_settings.audio.default_volume

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
