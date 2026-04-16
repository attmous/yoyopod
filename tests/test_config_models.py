#!/usr/bin/env python3
"""Tests for typed YAML-plus-env configuration models."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.config import ConfigManager, YoyoPodConfig, load_config_model_from_yaml


def test_app_config_defaults_do_not_require_a_file(tmp_path, monkeypatch) -> None:
    """Missing authored config should resolve to typed defaults in memory."""

    monkeypatch.delenv("YOYOPOD_MUSIC_DIR", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_SOCKET", raising=False)
    monkeypatch.delenv("YOYOPOD_MPV_BINARY", raising=False)
    monkeypatch.delenv("YOYOPOD_ALSA_DEVICE", raising=False)
    monkeypatch.delenv("YOYOPOD_AUTO_RESUME_AFTER_CALL", raising=False)
    monkeypatch.delenv("YOYOPOD_DISPLAY", raising=False)
    monkeypatch.delenv("YOYOPOD_VOICE_COMMANDS_ENABLED", raising=False)
    monkeypatch.delenv("YOYOPOD_VOSK_MODEL_PATH", raising=False)

    config_file = tmp_path / "app" / "core.yaml"
    settings = load_config_model_from_yaml(YoyoPodConfig, config_file)

    assert not config_file.exists()
    assert settings.audio.music_dir == "/home/pi/Music"
    assert settings.audio.mpv_socket == ""
    assert settings.audio.mpv_binary == "mpv"
    assert settings.audio.alsa_device == "default"
    assert settings.audio.default_volume == 100
    assert settings.audio.auto_resume_after_call is True
    assert settings.audio.speaker_test_path == "speaker-test"
    assert settings.input.ptt_navigation is True
    assert settings.input.whisplay_double_tap_ms == 300
    assert settings.input.whisplay_long_hold_ms == 800
    assert settings.voice.commands_enabled is True
    assert settings.voice.ai_requests_enabled is True
    assert settings.voice.screen_read_enabled is False
    assert settings.voice.stt_backend == "vosk"
    assert settings.voice.tts_backend == "espeak-ng"
    assert settings.voice.vosk_model_path == "models/vosk-model-small-en-us"
    assert settings.voice.sample_rate_hz == 16000
    assert settings.voice.tts_rate_wpm == 155
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
    assert settings.display.whisplay_renderer == "lvgl"
    assert settings.display.lvgl_buffer_lines == 40
    assert settings.logging.file == "logs/yoyopod.log"
    assert settings.logging.error_file == "logs/yoyopod_errors.log"
    assert settings.logging.pid_file == "/tmp/yoyopod.pid"
    assert settings.logging.rotation == "5 MB"
    assert settings.logging.retention == "3 days"
    assert settings.logging.error_rotation == "2 MB"
    assert settings.logging.error_retention == "7 days"
    assert settings.logging.enqueue is False
    assert settings.logging.backtrace is True
    assert settings.logging.diagnose is True
    assert settings.diagnostics.responsiveness_watchdog_enabled is False
    assert settings.diagnostics.responsiveness_watchdog_poll_interval_seconds == 1.0
    assert settings.diagnostics.responsiveness_stall_threshold_seconds == 5.0
    assert settings.diagnostics.responsiveness_capture_cooldown_seconds == 30.0
    assert settings.diagnostics.responsiveness_recent_input_window_seconds == 3.0
    assert settings.diagnostics.responsiveness_capture_dir == "logs/responsiveness"


def test_config_manager_app_config_merges_yaml_and_env(tmp_path, monkeypatch) -> None:
    """Environment variables should override YAML while preserving other values."""

    app_file = tmp_path / "app" / "core.yaml"
    app_file.parent.mkdir(parents=True, exist_ok=True)
    app_file.write_text(
        yaml.safe_dump(
            {
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
    audio_file = tmp_path / "audio" / "music.yaml"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_text(
        yaml.safe_dump(
            {
                "audio": {
                    "music_dir": "/srv/music",
                    "mpv_binary": "/usr/local/bin/mpv",
                    "auto_resume_after_call": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("YOYOPOD_MPV_SOCKET", "/tmp/test-mpv.sock")
    monkeypatch.setenv("YOYOPOD_ALSA_DEVICE", "hw:Loopback,0")
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
    monkeypatch.setenv("YOYOPOD_WHISPLAY_RENDERER", "lvgl")
    monkeypatch.setenv("YOYOPOD_LVGL_BUFFER_LINES", "24")
    monkeypatch.setenv("YOYOPOD_VOICE_COMMANDS_ENABLED", "false")
    monkeypatch.setenv("YOYOPOD_SCREEN_READ_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_VOSK_MODEL_PATH", "/srv/models/vosk-small")
    monkeypatch.setenv("YOYOPOD_LOG_FILE", "/var/log/yoyopod.log")
    monkeypatch.setenv("YOYOPOD_ERROR_LOG_FILE", "/var/log/yoyopod_errors.log")
    monkeypatch.setenv("YOYOPOD_PID_FILE", "/run/yoyopod.pid")
    monkeypatch.setenv("YOYOPOD_LOG_ENQUEUE", "true")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_STALL_THRESHOLD_SECONDS", "8.0")
    monkeypatch.setenv("YOYOPOD_RESPONSIVENESS_CAPTURE_DIR", "/tmp/yoyopod-watchdog")

    config_manager = ConfigManager(config_dir=str(tmp_path))
    settings = config_manager.get_app_settings()
    config_dict = config_manager.get_app_config_dict()

    assert config_manager.app_config_loaded is True
    assert settings.audio.music_dir == "/srv/music"
    assert settings.audio.mpv_socket == "/tmp/test-mpv.sock"
    assert settings.audio.mpv_binary == "/usr/local/bin/mpv"
    assert settings.audio.alsa_device == "hw:Loopback,0"
    assert settings.audio.auto_resume_after_call is False
    assert not hasattr(settings.audio, "listen_sources")
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
    assert settings.display.whisplay_renderer == "lvgl"
    assert settings.display.lvgl_buffer_lines == 24
    assert settings.voice.commands_enabled is False
    assert settings.voice.screen_read_enabled is True
    assert settings.voice.vosk_model_path == "/srv/models/vosk-small"
    assert settings.logging.level == "DEBUG"
    assert settings.logging.file == "/var/log/yoyopod.log"
    assert settings.logging.error_file == "/var/log/yoyopod_errors.log"
    assert settings.logging.pid_file == "/run/yoyopod.pid"
    assert settings.logging.enqueue is True
    assert settings.diagnostics.responsiveness_watchdog_enabled is True
    assert settings.diagnostics.responsiveness_stall_threshold_seconds == 8.0
    assert settings.diagnostics.responsiveness_capture_dir == "/tmp/yoyopod-watchdog"
    assert config_dict["audio"]["music_dir"] == "/srv/music"
    assert config_dict["audio"]["mpv_socket"] == "/tmp/test-mpv.sock"
    assert "listen_sources" not in config_dict["audio"]
    assert config_dict["display"]["hardware"] == "whisplay"
    assert config_dict["display"]["whisplay_renderer"] == "lvgl"
    assert config_dict["display"]["lvgl_buffer_lines"] == 24
    assert config_dict["voice"]["commands_enabled"] is False
    assert config_dict["voice"]["screen_read_enabled"] is True
    assert config_dict["voice"]["vosk_model_path"] == "/srv/models/vosk-small"
    assert config_dict["logging"]["file"] == "/var/log/yoyopod.log"
    assert config_dict["diagnostics"]["responsiveness_watchdog_enabled"] is True


def test_config_manager_keeps_typed_communication_audio_settings(tmp_path, monkeypatch) -> None:
    """Communication settings should stay typed while preserving existing getter behavior."""

    monkeypatch.setenv("YOYOPOD_PLAYBACK_DEVICE", "ALSA: default")
    monkeypatch.setenv("YOYOPOD_RING_OUTPUT_DEVICE", "default")
    monkeypatch.setenv("YOYOPOD_DEFAULT_VOLUME", "91")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert config_manager.get_communication_settings().audio.playback_device_id == "ALSA: default"
    assert config_manager.get_default_output_volume() == 91
    assert config_manager.get_playback_device_id() == "ALSA: default"
    assert config_manager.get_ring_output_device() == "default"


def test_config_manager_keeps_liblinphone_factory_config_path(tmp_path, monkeypatch) -> None:
    """Communication config should expose the Liblinphone factory config path with env override support."""

    monkeypatch.setenv("YOYOPOD_LIBLINPHONE_FACTORY_CONFIG", "config/custom_liblinphone_factory.conf")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().integrations.liblinphone_factory_config_path
        == "config/custom_liblinphone_factory.conf"
    )
    assert config_manager.get_voip_factory_config_path() == "config/custom_liblinphone_factory.conf"


def test_config_manager_exposes_lime_server_url(tmp_path, monkeypatch) -> None:
    """Communication config should expose the configured LIME/X3DH server URL."""

    monkeypatch.setenv("YOYOPOD_LIME_SERVER_URL", "https://lime.example.com/lime-server/lime-server.php")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().messaging.lime_server_url
        == "https://lime.example.com/lime-server/lime-server.php"
    )
    assert (
        config_manager.get_lime_server_url()
        == "https://lime.example.com/lime-server/lime-server.php"
    )


def test_config_manager_exposes_conference_factory_uri(tmp_path, monkeypatch) -> None:
    """Communication config should expose the configured conference-factory URI."""

    monkeypatch.setenv("YOYOPOD_CONFERENCE_FACTORY_URI", "sip:conference-factory@example.com")

    config_manager = ConfigManager(config_dir=str(tmp_path))

    assert (
        config_manager.get_communication_settings().messaging.conference_factory_uri
        == "sip:conference-factory@example.com"
    )
    assert config_manager.get_conference_factory_uri() == "sip:conference-factory@example.com"


def test_gpio_pin_config_from_yaml_dict():
    """GpioPin and PimoroniGpioConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppDisplayConfig,
        GpioPin,
        PimoroniGpioConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "spi_bus": 1,
            "spi_device": 0,
            "spi_speed_hz": 60000000,
            "dc": {"chip": "gpiochip0", "line": 109},
            "cs": {"chip": "gpiochip0", "line": 110},
            "backlight": {"chip": "gpiochip1", "line": 35},
            "led_r": {"chip": "gpiochip0", "line": 33},
            "led_g": {"chip": "gpiochip1", "line": 6},
            "led_b": {"chip": "gpiochip1", "line": 7},
        }
    }
    config = build_config_model(AppDisplayConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.spi_bus == 1
    assert config.pimoroni_gpio.dc == GpioPin(chip="gpiochip0", line=109)
    assert config.pimoroni_gpio.cs == GpioPin(chip="gpiochip0", line=110)
    assert config.pimoroni_gpio.backlight == GpioPin(chip="gpiochip1", line=35)
    assert config.pimoroni_gpio.led_r == GpioPin(chip="gpiochip0", line=33)


def test_gpio_input_config_from_yaml_dict():
    """PimoroniGpioInputConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppInputConfig,
        GpioPin,
        PimoroniGpioInputConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "button_a": {"chip": "gpiochip0", "line": 34},
            "button_b": {"chip": "gpiochip0", "line": 35},
            "button_x": {"chip": "gpiochip0", "line": 36},
            "button_y": {"chip": "gpiochip0", "line": 313},
        }
    }
    config = build_config_model(AppInputConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.button_a == GpioPin(chip="gpiochip0", line=34)
    assert config.pimoroni_gpio.button_y == GpioPin(chip="gpiochip0", line=313)


def test_display_config_defaults_pimoroni_gpio_to_none():
    """When no pimoroni_gpio section exists, it should default to None."""
    from yoyopod.config.models import AppDisplayConfig, build_config_model

    config = build_config_model(AppDisplayConfig, {})
    assert config.pimoroni_gpio is None
