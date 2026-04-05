#!/usr/bin/env python3
"""Tests for typed YAML-plus-env configuration models."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopy.config import ConfigManager, YoyoPodConfig, load_config_model_from_yaml


def test_app_config_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing yoyopod_config.yaml should resolve to typed defaults in memory."""

    monkeypatch.delenv("YOYOPOD_MOPIDY_HOST", raising=False)
    monkeypatch.delenv("YOYOPOD_MOPIDY_PORT", raising=False)
    monkeypatch.delenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", raising=False)
    monkeypatch.delenv("YOYOPOD_DISPLAY", raising=False)

    config_file = tmp_path / "yoyopod_config.yaml"
    settings = load_config_model_from_yaml(YoyoPodConfig, config_file)

    assert not config_file.exists()
    assert settings.audio.mopidy_host == "localhost"
    assert settings.audio.mopidy_port == 6680
    assert settings.audio.listen_sources == ["local"]
    assert settings.audio.auto_resume_after_call is True
    assert settings.audio.speaker_test_path == "speaker-test"
    assert settings.input.ptt_navigation is True
    assert settings.input.whisplay_double_tap_ms == 300
    assert settings.input.whisplay_long_hold_ms == 800
    assert settings.power.enabled is True
    assert settings.power.backend == "pisugar"
    assert settings.power.transport == "auto"
    assert settings.power.socket_path == "/tmp/pisugar-server.sock"
    assert settings.power.tcp_port == 8423
    assert settings.power.low_battery_warning_percent == 20.0
    assert settings.power.low_battery_warning_cooldown_seconds == 300.0
    assert settings.power.auto_shutdown_enabled is True
    assert settings.power.critical_shutdown_percent == 10.0
    assert settings.power.shutdown_delay_seconds == 15.0
    assert settings.power.shutdown_command == "sudo -n shutdown -h now"
    assert settings.power.shutdown_state_file == "data/last_shutdown_state.json"
    assert settings.power.watchdog_enabled is False
    assert settings.power.watchdog_timeout_seconds == 60
    assert settings.power.watchdog_feed_interval_seconds == 15.0
    assert settings.power.watchdog_i2c_bus == 1
    assert settings.power.watchdog_i2c_address == 0x57
    assert settings.display.hardware == "auto"


def test_config_manager_app_config_merges_yaml_and_env(tmp_path, monkeypatch) -> None:
    """Environment variables should override YAML while preserving other values."""

    config_file = tmp_path / "yoyopod_config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "audio": {
                    "mopidy_host": "mopidy.local",
                    "mopidy_port": 7000,
                    "listen_sources": ["spotify", "local"],
                    "auto_resume_after_call": True,
                },
                "display": {
                    "hardware": "pimoroni",
                },
                "logging": {
                    "level": "DEBUG",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("YOYOPOD_MOPIDY_PORT", "7788")
    monkeypatch.setenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", "false")
    monkeypatch.setenv("YOYOPOD_WHISPLAY_DOUBLE_TAP_MS", "260")
    monkeypatch.setenv("YOYOPOD_WHISPLAY_LONG_HOLD_MS", "900")
    monkeypatch.setenv("YOYOPOD_POWER_TRANSPORT", "tcp")
    monkeypatch.setenv("YOYOPOD_PISUGAR_PORT", "9001")
    monkeypatch.setenv("YOYOPOD_LOW_BATTERY_WARNING_PERCENT", "17.5")
    monkeypatch.setenv("YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT", "8.5")
    monkeypatch.setenv("YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS", "22.0")
    monkeypatch.setenv("YOYOPOD_POWER_SHUTDOWN_COMMAND", "sudo -n poweroff")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS", "0x58")
    monkeypatch.setenv("YOYOPOD_DISPLAY", "whisplay")

    config_manager = ConfigManager(config_dir=str(tmp_path))
    settings = config_manager.get_app_settings()
    config_dict = config_manager.get_app_config_dict()

    assert config_manager.app_config_loaded is True
    assert settings.audio.mopidy_host == "mopidy.local"
    assert settings.audio.mopidy_port == 7788
    assert settings.audio.listen_sources == ["spotify", "local"]
    assert settings.audio.auto_resume_after_call is False
    assert settings.input.whisplay_double_tap_ms == 260
    assert settings.input.whisplay_long_hold_ms == 900
    assert settings.power.transport == "tcp"
    assert settings.power.tcp_port == 9001
    assert settings.power.low_battery_warning_percent == 17.5
    assert settings.power.critical_shutdown_percent == 8.5
    assert settings.power.shutdown_delay_seconds == 22.0
    assert settings.power.shutdown_command == "sudo -n poweroff"
    assert settings.power.watchdog_enabled is True
    assert settings.power.watchdog_timeout_seconds == 90
    assert settings.power.watchdog_feed_interval_seconds == 30.0
    assert settings.power.watchdog_i2c_address == 0x58
    assert settings.display.hardware == "whisplay"
    assert settings.logging.level == "DEBUG"
    assert config_dict["audio"]["mopidy_port"] == 7788
    assert config_dict["display"]["hardware"] == "whisplay"


def test_config_manager_keeps_typed_voip_audio_settings(tmp_path, monkeypatch) -> None:
    """VoIP settings should stay typed while preserving existing getter behavior."""

    monkeypatch.setenv("YOYOPOD_PLAYBACK_DEVICE", "ALSA: default")
    monkeypatch.setenv("YOYOPOD_RING_OUTPUT_DEVICE", "default")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.voip_settings.audio.playback_device_id == "ALSA: default"
    assert config_manager.get_playback_device_id() == "ALSA: default"
    assert config_manager.get_ring_output_device() == "default"
