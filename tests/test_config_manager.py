#!/usr/bin/env python3
"""Tests for portable audio/device configuration helpers."""

from pathlib import Path

import yaml

from yoyopod.config.manager import ConfigManager
from yoyopod.ui.display.adapters.whisplay_paths import find_whisplay_driver


def _write_yaml(base_dir: Path, relative_path: str, payload: dict) -> Path:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_audio_device_defaults(tmp_path, monkeypatch) -> None:
    """Default communication audio settings should preserve the Pi-oriented device selectors."""
    monkeypatch.delenv("YOYOPOD_PLAYBACK_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_RINGER_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_CAPTURE_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_MEDIA_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_RING_OUTPUT_DEVICE", raising=False)

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.get_playback_device_id() == "ALSA: wm8960-soundcard"
    assert config_manager.get_ringer_device_id() == "ALSA: wm8960-soundcard"
    assert config_manager.get_capture_device_id() == "ALSA: wm8960-soundcard"
    assert config_manager.get_media_device_id() == "ALSA: wm8960-soundcard"
    assert config_manager.get_ring_output_device() == "wm8960-soundcard"


def test_audio_env_overrides(tmp_path, monkeypatch) -> None:
    """Environment variables should override composed communication audio settings."""
    monkeypatch.setenv("YOYOPOD_PLAYBACK_DEVICE", "ALSA: default")
    monkeypatch.setenv("YOYOPOD_RINGER_DEVICE", "ALSA: sysdefault")
    monkeypatch.setenv("YOYOPOD_CAPTURE_DEVICE", "ALSA: hw:2,0")
    monkeypatch.setenv("YOYOPOD_MEDIA_DEVICE", "ALSA: plughw:3")
    monkeypatch.setenv("YOYOPOD_RING_OUTPUT_DEVICE", "default")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.get_playback_device_id() == "ALSA: default"
    assert config_manager.get_ringer_device_id() == "ALSA: sysdefault"
    assert config_manager.get_capture_device_id() == "ALSA: hw:2,0"
    assert config_manager.get_media_device_id() == "ALSA: plughw:3"
    assert config_manager.get_ring_output_device() == "default"


def test_whisplay_driver_path_can_come_from_env(tmp_path, monkeypatch) -> None:
    """Whisplay driver discovery should accept a configured directory path."""
    driver_dir = tmp_path / "Driver"
    driver_dir.mkdir()
    driver_file = driver_dir / "WhisPlay.py"
    driver_file.write_text("# test driver\n", encoding="utf-8")

    monkeypatch.setenv("YOYOPOD_WHISPLAY_DRIVER", str(driver_dir))

    assert find_whisplay_driver() == driver_file


def test_board_config_overlays_base_config(tmp_path, monkeypatch) -> None:
    """Board overlays should override only the settings they redefine in the canonical topology."""

    _write_yaml(
        tmp_path,
        "audio/music.yaml",
        {
            "audio": {
                "music_dir": "/srv/common-music",
                "default_volume": 72,
            }
        },
    )
    _write_yaml(
        tmp_path,
        "app/core.yaml",
        {
            "ui": {
                "theme": "dark",
            }
        },
    )
    _write_yaml(
        tmp_path,
        "device/hardware.yaml",
        {
            "power": {
                "watchdog_i2c_bus": 1,
            }
        },
    )

    board_audio_file = _write_yaml(
        tmp_path,
        "boards/radxa-cubie-a7z/audio/music.yaml",
        {
            "audio": {
                "music_dir": "/home/radxa/Music",
            }
        },
    )
    _write_yaml(
        tmp_path,
        "boards/radxa-cubie-a7z/app/core.yaml",
        {
            "ui": {
                "theme": "retro",
            }
        },
    )
    _write_yaml(
        tmp_path,
        "boards/radxa-cubie-a7z/device/hardware.yaml",
        {
            "power": {
                "watchdog_i2c_bus": 7,
            }
        },
    )

    monkeypatch.setenv("YOYOPOD_CONFIG_BOARD", "radxa-cubie-a7z")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.config_board == "radxa-cubie-a7z"
    assert config_manager.app_config_file == (
        tmp_path / "boards" / "radxa-cubie-a7z" / "app" / "core.yaml"
    )
    assert config_manager.media_music_layers[-1] == board_audio_file
    assert config_manager.app_settings.ui.theme == "retro"
    assert config_manager.get_media_settings().music.music_dir == "/home/radxa/Music"
    assert config_manager.get_default_output_volume() == 72
    assert config_manager.app_settings.power.watchdog_i2c_bus == 7


def test_missing_board_overlay_falls_back_to_base_config(tmp_path, monkeypatch) -> None:
    """Unknown or missing board overlays should leave the base composed config in place."""

    base_file = _write_yaml(
        tmp_path,
        "audio/music.yaml",
        {
            "audio": {
                "music_dir": "/srv/base-music",
            }
        },
    )
    _write_yaml(
        tmp_path,
        "app/core.yaml",
        {
            "ui": {
                "theme": "dark",
            }
        },
    )
    base_device_file = _write_yaml(
        tmp_path,
        "device/hardware.yaml",
        {
            "power": {
                "watchdog_i2c_bus": 1,
            }
        },
    )

    monkeypatch.setenv("YOYOPOD_CONFIG_BOARD", "radxa-cubie-a7z")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.app_config_file == tmp_path / "app" / "core.yaml"
    assert config_manager.media_music_layers[0] == base_file
    assert config_manager.media_music_layers[-1] == base_file
    assert config_manager.device_hardware_layers[0] == base_device_file
    assert config_manager.device_hardware_layers[-1] == base_device_file
    assert config_manager.app_settings.ui.theme == "dark"
    assert config_manager.get_media_settings().music.music_dir == "/srv/base-music"
    assert config_manager.app_settings.power.watchdog_i2c_bus == 1
