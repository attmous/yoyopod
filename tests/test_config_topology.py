"""Focused tests for canonical config topology and people-data ownership."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.config import ConfigManager
from yoyopod.people import PeopleDirectory


def _write_yaml(base_dir: Path, relative_path: str, payload: dict) -> Path:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_config_manager_loads_communication_secrets_from_secret_file(tmp_path: Path) -> None:
    """Tracked communication config and untracked secrets should compose into one runtime model."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "communication/calling.yaml",
        {
            "calling": {
                "account": {
                    "sip_server": "sip.example.com",
                    "sip_username": "alice",
                    "sip_identity": "sip:alice@sip.example.com",
                }
            }
        },
    )
    _write_yaml(
        config_dir,
        "communication/calling.secrets.yaml",
        {
            "secrets": {
                "sip_password_ha1": "hashed-secret",
            }
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))

    assert manager.communication_config_loaded is True
    assert manager.communication_secrets_loaded is True
    assert manager.get_sip_identity() == "sip:alice@sip.example.com"
    assert manager.get_sip_password_ha1() == "hashed-secret"


def test_config_manager_rejects_secret_leak_in_tracked_calling_file(tmp_path: Path) -> None:
    """Tracked calling config must not carry SIP secrets."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "communication/calling.yaml",
        {
            "calling": {
                "account": {
                    "sip_identity": "sip:alice@sip.example.com",
                    "sip_password": "should-not-be-tracked",
                }
            }
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))

    assert manager.communication_config_loaded is False
    assert manager.communication_secrets_loaded is False
    assert manager.get_sip_identity() == ""
    assert manager.get_sip_password() == ""


def test_voice_config_composes_domain_policy_with_device_owned_selectors(tmp_path: Path) -> None:
    """Voice should read assistant policy from voice config and selectors from device config."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "voice/assistant.yaml",
        {
            "assistant": {
                "commands_enabled": False,
                "tts_backend": "dummy-tts",
                "tts_voice": "en-us",
            }
        },
    )
    _write_yaml(
        config_dir,
        "device/hardware.yaml",
        {
            "voice_audio": {
                "speaker_device_id": "plughw:CARD=SE,DEV=0",
                "capture_device_id": "plughw:CARD=SE,DEV=1",
            }
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))

    assert manager.voice_config_loaded is True
    assert manager.get_voice_settings().assistant.commands_enabled is False
    assert manager.get_voice_settings().assistant.tts_backend == "dummy-tts"
    assert manager.get_voice_settings().audio.speaker_device_id == "plughw:CARD=SE,DEV=0"
    assert manager.get_voice_settings().audio.capture_device_id == "plughw:CARD=SE,DEV=1"


def test_people_directory_bootstraps_mutable_contacts_from_seed(tmp_path: Path) -> None:
    """People data should seed mutable runtime storage instead of treating contacts as config."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "people/directory.yaml",
        {
            "contacts_file": "data/people/contacts.yaml",
            "contacts_seed_file": "config/people/contacts.seed.yaml",
        },
    )
    _write_yaml(
        config_dir,
        "people/contacts.seed.yaml",
        {
            "contacts": [
                {
                    "name": "Hagar",
                    "sip_address": "sip:mama@example.com",
                    "favorite": True,
                    "notes": "Mama",
                }
            ],
            "speed_dial": {1: "sip:mama@example.com"},
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))
    directory = PeopleDirectory.from_config_manager(manager)

    contacts_file = tmp_path / "data" / "people" / "contacts.yaml"
    assert contacts_file.exists()
    assert directory.bootstrapped_from_seed is True
    assert [contact.display_name for contact in directory.get_contacts()] == ["Mama"]
    assert directory.get_speed_dial_address(1) == "sip:mama@example.com"
