"""Config persistence tests for voice device selectors."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.config.manager import ConfigManager


def test_config_manager_persists_voice_device_ids(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    manager = ConfigManager(config_dir=str(cfg_dir))

    assert manager.set_voice_speaker_device_id("plughw:CARD=SE,DEV=0") is True
    assert manager.set_voice_capture_device_id("plughw:CARD=SE,DEV=0") is True

    reloaded = ConfigManager(config_dir=str(cfg_dir))
    assert reloaded.get_voice_settings().audio.speaker_device_id == "plughw:CARD=SE,DEV=0"
    assert reloaded.get_voice_settings().audio.capture_device_id == "plughw:CARD=SE,DEV=0"


def test_config_manager_allows_auto_device_ids(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    manager = ConfigManager(config_dir=str(cfg_dir))

    assert manager.set_voice_speaker_device_id(None) is True
    assert manager.set_voice_capture_device_id("") is True

    reloaded = ConfigManager(config_dir=str(cfg_dir))
    assert reloaded.get_voice_settings().audio.speaker_device_id == ""
    assert reloaded.get_voice_settings().audio.capture_device_id == ""


def test_voice_device_persistence_sets_device_hardware_loaded_only(tmp_path: Path) -> None:
    """Device-layer writes should not misreport the voice-domain load state."""

    cfg_dir = tmp_path / "config"
    manager = ConfigManager(config_dir=str(cfg_dir))

    assert manager.voice_config_loaded is False
    assert manager.device_hardware_config_loaded is False

    assert manager.set_voice_speaker_device_id("plughw:CARD=SE,DEV=0") is True

    assert manager.voice_config_loaded is False
    assert manager.device_hardware_config_loaded is True


def test_voice_device_persistence_does_not_flatten_env_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Persisting one selector should not dump env-resolved values into YAML."""

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    power_file = cfg_dir / "power" / "backend.yaml"
    power_file.parent.mkdir(parents=True, exist_ok=True)
    power_file.write_text(
        yaml.safe_dump(
            {
                "power": {
                    "watchdog_i2c_bus": 7,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOYOPOD_DEFAULT_VOLUME", "77")

    manager = ConfigManager(config_dir=str(cfg_dir))

    assert manager.set_voice_speaker_device_id("plughw:CARD=SE,DEV=0") is True

    assert yaml.safe_load(power_file.read_text(encoding="utf-8")) == {
        "power": {
            "watchdog_i2c_bus": 7,
        }
    }
    voice_file = cfg_dir / "device" / "hardware.yaml"
    persisted = yaml.safe_load(voice_file.read_text(encoding="utf-8"))
    assert persisted["voice_audio"]["speaker_device_id"] == "plughw:CARD=SE,DEV=0"
    assert "audio" not in persisted


def test_voice_device_persistence_only_updates_active_overlay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Board overlays should keep their compact shape when selectors are updated."""

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    base_file = cfg_dir / "power" / "backend.yaml"
    base_file.parent.mkdir(parents=True, exist_ok=True)
    base_file.write_text(
        yaml.safe_dump(
            {
                "power": {
                    "watchdog_i2c_bus": 1,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    overlay_dir = cfg_dir / "boards" / "rpi-zero-2w" / "device"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay_file = overlay_dir / "hardware.yaml"
    overlay_file.write_text(
        yaml.safe_dump(
            {
                "display": {
                    "brightness": 55,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOYOPOD_CONFIG_BOARD", "rpi-zero-2w")

    manager = ConfigManager(config_dir=str(cfg_dir))

    assert manager.set_voice_speaker_device_id("plughw:CARD=SE,DEV=0") is True

    assert yaml.safe_load(base_file.read_text(encoding="utf-8")) == {
        "power": {
            "watchdog_i2c_bus": 1,
        }
    }
    assert yaml.safe_load(overlay_file.read_text(encoding="utf-8")) == {
        "display": {
            "brightness": 55,
        },
        "voice_audio": {
            "speaker_device_id": "plughw:CARD=SE,DEV=0",
        }
    }
