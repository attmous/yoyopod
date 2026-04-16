"""Focused tests for canonical config topology and people-data ownership."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.config import ConfigManager
from yoyopod.audio import MusicConfig
from yoyopod.network import NetworkManager
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


def test_media_config_composes_domain_policy_with_device_owned_routing(tmp_path: Path) -> None:
    """Media should read policy from audio config and routing from device config."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "audio/music.yaml",
        {
            "audio": {
                "music_dir": "/srv/music",
                "default_volume": 72,
                "recent_tracks_file": "data/media/recent_tracks.json",
            }
        },
    )
    _write_yaml(
        config_dir,
        "device/hardware.yaml",
        {
            "media_audio": {
                "alsa_device": "hw:Loopback,0",
            }
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))

    assert manager.media_config_loaded is True
    assert not hasattr(manager.get_app_settings(), "audio")
    assert manager.get_media_settings().music.music_dir == "/srv/music"
    assert manager.get_media_settings().audio.alsa_device == "hw:Loopback,0"
    assert manager.get_default_output_volume() == 72
    assert MusicConfig.from_config_manager(manager).alsa_device == "hw:Loopback,0"
    assert (
        manager.resolve_runtime_path(manager.get_recent_tracks_file())
        == tmp_path / "data" / "media" / "recent_tracks.json"
    )


def test_network_config_composes_domain_owned_cellular_settings(tmp_path: Path) -> None:
    """Network should load from its canonical domain-owned config file."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "network/cellular.yaml",
        {
            "network": {
                "enabled": True,
                "serial_port": "/dev/ttyAMA0",
                "apn": "internet",
                "ppp_timeout": 45,
            }
        },
    )

    manager = ConfigManager(config_dir=str(config_dir))
    network_manager = NetworkManager.from_config_manager(manager)

    assert manager.network_config_loaded is True
    assert not hasattr(manager.get_app_settings(), "network")
    assert manager.get_network_settings().serial_port == "/dev/ttyAMA0"
    assert manager.get_runtime_settings().network.apn == "internet"
    assert network_manager.config.ppp_timeout == 45


def test_network_board_overlay_uses_domain_relative_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Board overlays should mirror the canonical network config path."""

    config_dir = tmp_path / "config"
    _write_yaml(
        config_dir,
        "network/cellular.yaml",
        {
            "network": {
                "enabled": False,
                "gps_enabled": False,
            }
        },
    )
    _write_yaml(
        config_dir,
        "boards/rpi-zero-2w/network/cellular.yaml",
        {
            "network": {
                "enabled": True,
                "gps_enabled": True,
            }
        },
    )
    monkeypatch.setenv("YOYOPOD_CONFIG_BOARD", "rpi-zero-2w")

    manager = ConfigManager(config_dir=str(config_dir))

    assert manager.get_network_settings().enabled is True
    assert manager.get_network_settings().gps_enabled is True


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
